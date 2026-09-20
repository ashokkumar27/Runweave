import sqlite3

import httpx
import pytest

from agent_runtime.model_adapter import request_context
from scripts.completion_models_budget import PHASES, profile


@pytest.mark.parametrize("phase", PHASES)
def test_phase_caps_local_children_terminals_and_binding(tmp_path, phase):
    guard = profile(phase)
    path = tmp_path / "phase.sqlite"
    guard.initialize(path)
    assert sum(guard.MANIFEST["scenario_limits"].values()) == 216
    assert len(guard.MANIFEST["scenario_limits"]) == 15
    for cell, limit in guard.MANIFEST["scenario_limits"].items():
        guard.admit(path, cell, cell)
        cap = guard.MANIFEST["scenario_caps"][cell]
        ctx = dict(scenario=cell, root_id=cell, run_id=cell, operation_id="op", attempt_id="attempt")
        with pytest.raises(RuntimeError, match="Unadmitted"):
            guard.reserve(path, {**ctx, "root_id": "other"}, cap)
        used = 0
        if cell.endswith("/parallel"):
            child = {**ctx, "run_id": cell + "-child"}
            for _ in range(4):
                guard.reserve(path, child, cap)
            used = 4
            with pytest.raises(RuntimeError, match="local allocation"):
                guard.reserve(path, child, cap)
        for _ in range(limit - used):
            guard.reserve(path, ctx, cap)
        with pytest.raises(RuntimeError, match="exhausted"):
            guard.reserve(path, ctx, cap)
        guard.finish(path, cell, "failed")
        with pytest.raises(RuntimeError, match="terminal"):
            guard.admit(path, cell, "new-root")
    assert guard.validate(path) == 216
    with sqlite3.connect(path) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM attempts")
    with pytest.raises(RuntimeError, match="identity"):
        profile(next(p for p in PHASES if p != phase)).validate(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unknown", "refusal", "http"])
async def test_physical_failure_latch_and_exact_wire_policy(tmp_path, failure):
    guard = profile(PHASES[0])
    path = tmp_path / "phase.sqlite"
    guard.initialize(path)
    model = guard.MODELS[1]
    guard.admit(path, model + "/parallel", "root")
    sends = []

    async def send(request):
        sends.append(request)
        if failure == "unknown":
            raise httpx.ReadError("unknown")
        return httpx.Response(
            403 if failure == "http" else 200,
            json={"output": [{"content": [{"type": "refusal"}]}] if failure == "refusal" else []},
        )

    token = request_context.set(
        dict(scenario="parallel", run_id="child", root_id="root", operation_id="op", attempt_id="attempt")
    )
    body = dict(model=model, reasoning={"effort": "none"}, max_output_tokens=768)
    try:
        async with httpx.AsyncClient(
            transport=guard.Transport(path, model, httpx.MockTransport(send))
        ) as client:
            for mutation in (
                {"model": guard.MODELS[0]},
                {"reasoning": {"effort": "low"}},
                {"max_output_tokens": 1024},
            ):
                with pytest.raises(RuntimeError):
                    await client.post(guard.MANIFEST["endpoint"], json={**body, **mutation})
            try:
                await client.post(guard.MANIFEST["endpoint"], json=body)
            except httpx.ReadError:
                pass
            with pytest.raises(RuntimeError):
                await client.post(guard.MANIFEST["endpoint"], json=body)
        assert len(sends) == guard.validate(path) == 1
    finally:
        request_context.reset(token)
