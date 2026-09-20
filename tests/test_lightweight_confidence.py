import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from agent_runtime.model_adapter import request_context
from scripts import lightweight_budget as guard
from scripts.lightweight_fixtures import config, fixture


def context(name, i=0):
    return dict(
        scenario=name,
        run_id=(name if i < 6 else name + "-child" + str((i - 6) // 3))
        if name == "parallel"
        else name + "-child",
        root_id=name,
        operation_id=str(i),
        attempt_id=str(i),
    )


def test_concurrent_caps_identity_and_restart(tmp_path):
    path = tmp_path / "campaign.sqlite"
    guard.initialize(path)
    for name in guard.MANIFEST["scenario_limits"]:
        guard.admit(path, name, name)

    def reserve(job):
        name, i = job
        try:
            guard.reserve(path, context(name, i), guard.MANIFEST["scenario_caps"][name])
            return True
        except RuntimeError:
            return False

    jobs = [(name, i) for name, n in guard.MANIFEST["scenario_limits"].items() for i in range(n + 3)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, jobs)) == 32
    assert guard.initialize(path) == 32
    with sqlite3.connect(path) as db:
        assert (
            dict(db.execute("SELECT scenario,count(*) FROM attempts GROUP BY scenario"))
            == guard.MANIFEST["scenario_limits"]
        )
        for table in ["attempts", "admissions", "terminals", "manifest"]:
            if table == "terminals":
                db.execute("INSERT INTO terminals VALUES ('bug','failed')")
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(f"DELETE FROM {table}")
    moved = tmp_path / "moved.sqlite"
    shutil.copy(path, moved)
    shutil.copy(path.with_suffix(".started"), moved.with_suffix(".started"))
    with pytest.raises(RuntimeError):
        guard.validate(moved)
    path.unlink()
    with pytest.raises(RuntimeError):
        guard.initialize(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["unknown", "body_unknown", "http_failure", "success"])
async def test_transport_latches_and_enforcement(tmp_path, outcome):
    path = tmp_path / "guard.sqlite"
    guard.initialize(path)
    guard.admit(path, "bug", "bug")
    sent = []

    class BrokenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"partial"
            raise httpx.ReadError("synthetic unknown body")

    async def send(request):
        sent.append(request)
        if outcome == "body_unknown":
            return httpx.Response(200, stream=BrokenBody())
        if outcome == "unknown":
            raise httpx.ReadError("synthetic unknown")
        return httpx.Response(500 if outcome == "http_failure" else 200, json={})

    token = request_context.set(context("bug"))
    try:
        async with httpx.AsyncClient(transport=guard.Transport(path, httpx.MockTransport(send))) as client:
            body = dict(model="gpt-5.6-luna", reasoning={"effort": "none"}, max_output_tokens=1024)
            for mutation in [
                {"model": "other"},
                {"max_output_tokens": 1025},
                {"reasoning": {"effort": "low"}},
            ]:
                with pytest.raises(RuntimeError):
                    await client.post(guard.MANIFEST["endpoint"], json={**body, **mutation})
            assert not sent
            if outcome in {"unknown", "body_unknown"}:
                with pytest.raises(httpx.ReadError):
                    await client.post(guard.MANIFEST["endpoint"], json=body)
            else:
                await client.post(guard.MANIFEST["endpoint"], json=body)
            if outcome == "success":
                guard.finish(path, "bug", "failed")
            with pytest.raises(RuntimeError):
                await client.post(guard.MANIFEST["endpoint"], json=body)
            with pytest.raises(RuntimeError if outcome == "success" else sqlite3.IntegrityError):
                guard.admit(path, "bug", "new-root")
    finally:
        request_context.reset(token)
    assert len(sent) == guard.validate(path) == 1


def test_fixed_fixtures_and_production_ceiling():
    for name in guard.MANIFEST["scenario_limits"]:
        cfg = config(name)
        assert cfg.general.limits.total_tokens == 16000
        assert cfg.max_tokens == guard.MANIFEST["scenario_caps"][name]
    assert (
        fixture("csv")["files"]["input.csv"] == b"name,amount\n Alice , 7 \nBob,-2\nCara,\nDan,oops\nEve,9\n"
    )
    assert fixture("csv")["expected"]["summary.csv"] == b"valid_rows,rejected_rows,total\n3,2,14\n"


def test_unknown_process_restart_latches_before_another_send(tmp_path):
    path = tmp_path / "restart.sqlite"
    guard.initialize(path)
    guard.admit(path, "recovery", "recovery")
    guard.reserve(path, context("recovery"), 1024)
    assert guard.reconcile_unknown(path) == 1
    assert guard.reconcile_unknown(path) == 0
    with pytest.raises(RuntimeError, match="ambiguous"):
        guard.reserve(path, context("recovery", 1), 1024)
    assert guard.validate(path) == 1


def test_retained_http_oracles_reject_tampering():
    """Replay HTTP evidence, retaining original outcomes; no runtime action bypass."""
    import copy
    import json
    from pathlib import Path

    from scripts.lightweight_confidence import oracle

    path = Path("var/acceptance/lightweight-confidence-v1/preflight-gate.json")
    if not path.exists():
        pytest.skip("Campaign-specific retained HTTP evidence unavailable")
    report = json.loads(path.read_text())
    for original in report["scenarios"]:
        if original["name"] == "parallel":
            assert oracle(original)
            continue
        assert not oracle(original)
        stale = copy.deepcopy(original)
        for receipt in stale["verifications"]["items"]:
            receipt["fresh"] = False
        assert oracle(stale)
        damaged = copy.deepcopy(original)
        preserved = fixture(original["name"])["preserve"]
        target = preserved[0] if preserved else next(iter(damaged["downloads"]))
        damaged["downloads"][target]["matches"] = False
        assert oracle(damaged)
