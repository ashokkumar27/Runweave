import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from agent_runtime.registry import Registration, load_registry
from scripts.acceptance_worker import BoundedTransport, BudgetExceeded, reserve


def test_budget_atomic_persistent(tmp_path):
    path = str(tmp_path / "budget.db")

    def attempt(_):
        try:
            reserve(path)
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(30))) == 20
    with pytest.raises(BudgetExceeded):
        reserve(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 20


async def test_transport_counts_failure_and_rejects_out_of_bounds(tmp_path):
    path = str(tmp_path / "budget.db")

    def fail(request):
        raise httpx.ReadError("ambiguous")

    async with httpx.AsyncClient(transport=BoundedTransport(path, httpx.MockTransport(fail))) as client:
        body = {"model": "gpt-5.6-luna", "max_output_tokens": 512, "reasoning": {"effort": "none"}}
        with pytest.raises(httpx.ReadError):
            await client.post("https://api.openai.com/v1/responses", json=body)
        with pytest.raises(BudgetExceeded):
            await client.post("https://api.openai.com/v1/responses", json={**body, "max_output_tokens": 513})
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1


def test_old_registration_identity_and_immutable_reasoning():
    registration = load_registry().entries[("openai", "gpt-5.6-luna")]
    assert registration.reasoning_effort == "none"
    old = registration.model_dump(exclude={"reasoning_effort"})
    identity = hashlib.sha256(json.dumps(old, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert Registration.model_validate(old).identity == identity
    assert registration.identity != identity
    with pytest.raises(ValueError):
        registration.reasoning_effort = "high"


async def test_snapshotted_reasoning_survives_registry_edit(store, monkeypatch):
    from agent_runtime import runtime
    from agent_runtime.model_adapter import build_model
    from agent_runtime.registry import Registry
    from agent_runtime.schemas import AgentConfig, RunCreate
    from agent_runtime.store import Store

    original = load_registry().entries[("openai", "gpt-5.6-luna")]
    store.registry = Registry([original.model_dump()])
    saved = await store.agent(AgentConfig(name="reasoning", provider="openai", model="gpt-5.6-luna"))
    run = await store.submit(RunCreate(agent_id=saved.id, input="synthetic"), "reasoning")
    identity = (await store.load(run.id))["registration_id"]
    restarted = Store(
        store.database, registry=Registry([{**original.model_dump(), "reasoning_effort": "high"}])
    )
    runtime.configure_store(restarted)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-only")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as http:
        monkeypatch.setattr(
            runtime, "build_model", lambda registration: build_model(registration, http_client=http)
        )
        model = await runtime.resolve_registration(None, "registry:" + identity)
        assert model.settings["openai_reasoning_effort"] == "none"
        async with model:
            pass
