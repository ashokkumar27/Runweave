import json

import httpx
import pytest
from pydantic_ai import Agent as ModelAgent
from sqlalchemy import select

from agent_runtime.activities import load_run
from agent_runtime.api import create_app
from agent_runtime.db import RegistrationRow
from agent_runtime.model_adapter import build_model
from agent_runtime.registry import Registration, Registry
from agent_runtime.runtime import Deps, agent, configure_store
from agent_runtime.schemas import AgentConfig, Answer, RunCreate
from agent_runtime.store import Store
from scripts.auth_diagnostic import safe_error


def entry(**updates):
    return {
        "provider": "local",
        "model": "small",
        "adapter": "openai_chat",
        "upstream_model": "org/model-v1",
        "endpoint": "http://backend.invalid/v1",
        "auth": "none",
        "credential_env": None,
        "tool_calling": True,
        "max_output_tokens": 2048,
        "total_tokens_limit": 8000,
        **updates,
    }


async def test_config_only_models_validation_and_private_contract(store):
    store.registry = Registry([entry(), entry(model="large", upstream_model="org/model-v2")])
    app = create_app(store, "test")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer test"},
    ) as client:
        for name in ["small", "large"]:
            config = {"name": "custom", "provider": "local", "model": name}
            response = await client.post("/v1/agents", json=config)
            assert response.status_code == 201
            saved = response.json()
            created = await client.post(
                "/v1/runs",
                json={"agent_id": saved["id"], "input": "hello"},
                headers={"Idempotency-Key": name},
            )
            assert created.status_code == 202
            run = created.json()
            await store.cancel(run["id"])
            events = await client.get(f"/v1/runs/{run['id']}/events")
            assert "registration_id" not in run  # Model selection remains private; tool IDs are public.
            for private in [
                "backend.invalid",
                "org/model",
                "credential_env",
                "endpoint",
                "approval_wait_seconds",
            ]:
                assert private not in response.text + created.text + events.text + json.dumps(app.openapi())
        for invalid in [{"model": "unknown"}, {"provider": "unknown"}, {"max_tokens": 4096}]:
            assert (await client.post("/v1/agents", json={**config, **invalid})).status_code == 422
            assert (
                await client.put(f"/v1/agents/{saved['id']}", json={**config, **invalid})
            ).status_code == 422
        store.registry = Registry([entry(model="large", tool_calling=False)])
        assert (await client.post("/v1/agents", json=config)).status_code == 422
        result = await client.post(
            "/v1/runs",
            json={"agent_id": saved["id"], "input": "hello"},
            headers={"Idempotency-Key": "incompatible"},
        )
        assert result.status_code == 422
        store.registry = Registry([entry(model="other")])
        result = await client.post(
            "/v1/runs",
            json={"agent_id": saved["id"], "input": "hello"},
            headers={"Idempotency-Key": "removed"},
        )
        assert result.status_code == 422


async def test_registration_retained_after_restart_and_edit(store, monkeypatch):
    old = entry(adapter="fake", endpoint=None)
    store.registry = Registry([old])
    saved = await store.agent(AgentConfig(name="pin", provider="local", model="small"))
    run = await store.submit(RunCreate(agent_id=saved.id, input="add 2 3"), "pin")
    original = await store.load(run.id)
    restarted = Store(
        store.database, registry=Registry([entry(adapter="fake", endpoint=None, upstream_model="changed")])
    )
    configure_store(restarted)
    newer = await restarted.submit(RunCreate(agent_id=saved.id, input="add 2 3"), "new")
    assert (await restarted.load(newer.id))["registration_id"] != original["registration_id"]
    registration = await restarted.registration(original["registration_id"])
    assert registration.upstream_model == "org/model-v1"
    seen = []
    from agent_runtime import runtime

    original_build = runtime.build_model

    def build(value):
        seen.append(value.identity)
        return original_build(value)

    monkeypatch.setattr(runtime, "build_model", build)
    result = await agent.run(
        "add 2 3", model=f"registry:{original['registration_id']}", deps=Deps(run.id, ["add"])
    )
    assert result.output.value == 5
    assert seen == [original["registration_id"]]
    async with store.database.sessions() as db:
        assert len(list(await db.scalars(select(RegistrationRow)))) == 2


@pytest.mark.parametrize("auth", ["none", "env"])
async def test_compatible_chat_request_uses_explicit_upstream_and_no_auth(monkeypatch, auth):
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-secret-must-not-be-used")
    monkeypatch.setenv("CUSTOM_MODEL_KEY", "configured-test-key")
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "ambient-admin")
    monkeypatch.setenv("OPENAI_ORG_ID", "ambient-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "ambient-project")
    requests = []

    def respond(request):
        requests.append(request)
        assert str(request.url) == "http://backend.invalid/v1/chat/completions"
        if auth == "none":
            assert "authorization" not in request.headers
        else:
            assert request.headers["authorization"] == "Bearer configured-test-key"
        assert not request.headers.get("openai-organization")
        assert not request.headers.get("openai-project")
        body = json.loads(request.content)
        assert body["model"] == "org/model-v1"
        assert body["tools"][0]["type"] == "function"
        return httpx.Response(
            200,
            json={
                "id": "chat-1",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "answer",
                                    "type": "function",
                                    "function": {
                                        "name": body["tools"][0]["function"]["name"],
                                        "arguments": '{"answer":"5","value":5}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    monkeypatch.setattr("pydantic_ai.models.ALLOW_MODEL_REQUESTS", True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = build_model(
            Registration(**entry(auth=auth, credential_env="CUSTOM_MODEL_KEY" if auth == "env" else None)),
            http_client=client,
        )
        assert model.client.max_retries == 0
        result = await ModelAgent(model, output_type=Answer).run("answer")
        assert result.output.value == 5
    assert len(requests) == 1


async def test_required_credentials_sanitized_and_no_fallback(store, monkeypatch):
    monkeypatch.delenv("CUSTOM_MODEL_KEY", raising=False)
    registration = Registration(**entry(auth="env", credential_env="CUSTOM_MODEL_KEY"))
    store.registry = Registry([registration])
    saved = await store.agent(AgentConfig(name="missing", provider="local", model="small"))
    run = await store.submit(RunCreate(agent_id=saved.id, input="hello"), "missing")
    data = await load_run(run.id)
    assert data["model_available"] is False
    assert "CUSTOM_MODEL_KEY" not in json.dumps(data) and "backend.invalid" not in json.dumps(data)
    with pytest.raises(ValueError, match="^provider_not_configured$"):
        build_model(registration)
    with pytest.raises(ValueError, match="Unknown registration"):
        await agent.run("hello", model="openai:invented", deps=Deps(run.id, []))


@pytest.mark.parametrize(
    "change",
    [
        {"endpoint": None},
        {"endpoint": "https://user:secret@host/v1"},
        {"endpoint": "https://host/v1?key=secret"},
        {"auth": "env"},
        {"credential_env": "OPENAI_API_KEY"},
        {"total_tokens_limit": 128},
        {"adapter": "unknown"},
    ],
)
def test_invalid_registry_connection_rejected(change):
    with pytest.raises(ValueError):
        Registry([entry(**change)])


@pytest.mark.parametrize(
    "body",
    [
        {"code": "invalid_api_key", "type": "invalid_request_error"},
        {"error": {"code": "invalid_api_key", "type": "invalid_request_error"}},
    ],
)
def test_safe_diagnostic_both_error_shapes(body):
    assert safe_error(body) == ("invalid_api_key", "invalid_request_error")
    assert safe_error({"error": {"code": ["secret"], "type": {"secret": "secret"}}, "message": "secret"}) == (
        "unclassified",
        "unclassified",
    )
