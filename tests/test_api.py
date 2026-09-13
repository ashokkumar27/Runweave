import pytest
from httpx import ASGITransport, AsyncClient

from agent_runtime.api import create_app
from agent_runtime.schemas import AgentConfig, RunCreate
from agent_runtime.store import Problem, require_retry_safe_effect


async def make_run(store, key="test", tools=None, session_id=None, prompt="add 2 3"):
    agent = await store.agent(
        AgentConfig(name="test", provider="fake", model="deterministic", tools=tools or ["add"])
    )
    return await store.submit(RunCreate(agent_id=agent.id, session_id=session_id, input=prompt), key)


async def test_auth_contract_idempotency_and_snapshot(store):
    app = create_app(store, "test-key")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for headers in [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "test-key"}]:
            assert (await client.post("/v1/sessions", headers=headers)).status_code == 401
        client.headers["Authorization"] = "Bearer test-key"
        config = {"name": "demo", "provider": "fake", "model": "deterministic"}
        agent = (await client.post("/v1/agents", json=config)).json()
        body = {"agent_id": agent["id"], "input": "add 2 3"}
        assert (await client.post("/v1/runs", json=body)).status_code == 422
        response = await client.post("/v1/runs", json=body, headers={"Idempotency-Key": "one"})
        assert response.status_code == 202
        run = response.json()
        duplicate = await client.post("/v1/runs", json=body, headers={"Idempotency-Key": "one"})
        assert duplicate.json()["id"] == run["id"]
        conflict = await client.post(
            "/v1/runs", json={**body, "input": "other"}, headers={"Idempotency-Key": "one"}
        )
        assert conflict.status_code == 409
        assert (
            await client.put(f"/v1/agents/{agent['id']}", json={**config, "instructions": "changed"})
        ).status_code == 200
        assert (await client.get(f"/v1/runs/{run['id']}")).json()["config"]["instructions"] != "changed"
        assert (await client.get("/v1/runs/missing")).status_code == 404
        bad = await client.post("/v1/agents", json={**config, "provider": "openai", "model": "invented"})
        assert bad.status_code == 422
        public = str(app.openapi())
        assert "pydantic_ai" not in public and "temporalio" not in public


async def test_sse_replay_and_terminal_reconnect(store):
    run = await make_run(store)
    await store.load(run.id)
    await store.cancel(run.id)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(store, "test")),
        base_url="http://test",
        headers={"Authorization": "Bearer test"},
    ) as client:
        all_events = await client.get(f"/v1/runs/{run.id}/events")
        assert "id: 1\n" in all_events.text and "run.cancelled" in all_events.text
        replay = await client.get(f"/v1/runs/{run.id}/events", headers={"Last-Event-ID": "1"})
        assert "id: 1\n" not in replay.text and "id: 2\n" in replay.text
        done = await client.get(f"/v1/runs/{run.id}/events", headers={"Last-Event-ID": "3"})
        assert done.text == ""
        assert (
            await client.get(f"/v1/runs/{run.id}/events", headers={"Last-Event-ID": "bad"})
        ).status_code == 400


async def test_approval_effect_replay_and_terminal_guard(store):
    run = await make_run(store, tools=["record_note"])
    approval = {"id": "call", "tool": "record_note", "arguments": {"text": "hello"}}
    await store.awaiting(run.id, [approval])
    await store.decide(run.id, "call", True)
    await store.decide(run.id, "call", True)
    with pytest.raises(Problem):
        await store.decide(run.id, "call", False)
    assert await store.record_note(run.id, "call", "hello") == "Note recorded"
    assert await store.record_note(run.id, "call", "hello") == "Note recorded"
    with pytest.raises(Problem):
        await store.record_note(run.id, "call", "different")
    await store.cancel(run.id)
    assert await store.finish(run.id, "completed", output={"answer": "late"}) == "cancelled"
    events = await store.events(run.id)
    assert sum(e.type == "tool.effect_committed" for e in events) == 1
    assert sum(e.type in {"run.cancelled", "run.completed"} for e in events) == 1


async def test_session_admission_and_limits(store):
    run = await make_run(store)
    with pytest.raises(Problem) as exc:
        await store.submit(RunCreate(agent_id=run.agent_id, session_id=run.session_id, input="next"), "next")
    assert exc.value.status == 409
    store.max_active = 1
    with pytest.raises(Problem) as exc:
        await make_run(store, key="limited")
    assert exc.value.status == 429


def test_unsafe_external_effect_rejected():
    with pytest.raises(ValueError, match="reconciliation"):
        require_retry_safe_effect(idempotency_supported=False, reconciler_available=False)
