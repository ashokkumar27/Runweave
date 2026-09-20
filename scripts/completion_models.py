"""Exact completion fixtures, three models, two immutable phases; default is unpaid SDK/backend preflight."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from scripts import lightweight_confidence as harness
from scripts.completion_loop_fixtures import config, fixture
from scripts.completion_models_budget import PHASES, profile
from scripts.model_comparison import digest
from scripts.model_comparison_audit import normalized, sha


def snapshot():
    return {
        "sources": {
            str(p): digest(p)
            for pattern in ("agent_runtime/*.py", "scripts/*.py", "config/*.json", "uv.lock")
            for p in Path().glob(pattern)
        },
        "fixtures": {
            name: {
                "fixture": {
                    **fixture(name),
                    **{k: {p: b.hex() for p, b in fixture(name)[k].items()} for k in ("files", "expected")},
                },
                "config": config(name).model_dump(mode="json"),
            }
            for name in ("bug", "csv", "recovery", "direct", "parallel")
        },
    }


def parity(directory, report):
    wire = Path(report["wire_path"])
    records = [json.loads(line) for line in wire.read_text().splitlines()]
    result = {}
    for name in ("bug", "csv", "recovery", "direct", "parallel"):
        initial = [
            r
            for r in records
            if r["context"]["scenario"] == name
            and r["context"]["run_id"] == r["context"]["root_id"]
            and r["context"]["operation_id"].endswith(":model:0")
        ]
        hashes = {r["body"]["model"]: sha(normalized(r["body"])) for r in initial}
        result[name] = {
            "models": hashes,
            "normalized_equal": len(hashes) == 3 and len(set(hashes.values())) == 1,
        }
    harness.save(directory / "preflight-parity.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    guard = profile(args.phase)
    directory = Path("var/acceptance") / args.phase
    directory.mkdir(parents=True, exist_ok=True)
    historical = [Path("AGENTS.md"), Path("/tmp/agent-runtime-acceptance-budget.sqlite")]
    historical += [
        p for p in Path("var/acceptance").rglob("*") if p.is_file() and not any(x in str(p) for x in PHASES)
    ]
    historical += [p for p in Path("docs").rglob("*") if p.is_file()]
    target = directory / "preserved-before.json"
    if target.exists():
        preserved = json.loads(target.read_text())
        assert all(digest(Path(p)) == h for p, h in preserved.items()), "Historical evidence changed"
    else:
        preserved = {str(p): digest(p) for p in historical if p.exists()}
        harness.save(target, preserved)
    registration = next(
        r for r in json.loads(Path("config/models.json").read_text()) if r["model"] == guard.MODELS[0]
    )
    registry = directory / "models.json"
    registrations = [{**registration, "model": m, "upstream_model": m} for m in guard.MODELS]
    if registry.exists():
        assert json.loads(registry.read_text()) == registrations
    else:
        harness.save(registry, registrations)
    frozen = snapshot()
    if args.live:
        gate = json.loads((directory / "preflight-gate.json").read_text())
        assert gate["verified_source"] == frozen
        assert len(gate["scenarios"]) == 15 and all(s["status"] == "passed" for s in gate["scenarios"])
        assert all(
            v["normalized_equal"]
            for v in json.loads((directory / "preflight-parity.json").read_text()).values()
        )
        target = directory / "live-source.json"
        if target.exists():
            raise RuntimeError("Phase already frozen; no blind resubmission")
        harness.save(target, frozen)
    harness.fixture, harness.config = fixture, config
    try:
        result = asyncio.run(
            harness.execute(
                args.live,
                directory=directory,
                ledger_path=directory.with_suffix(".sqlite"),
                campaign_guard=guard,
                registry=registry,
            )
        )
        if not args.live and result == 0:
            gate_path = directory / "preflight-gate.json"
            gate = json.loads(gate_path.read_text())
            wire = str(Path(gate["source_evidence"]).with_suffix(".wire.jsonl"))
            gate.update(verified_source=frozen, wire_path=wire)
            harness.save(gate_path, gate)
            assert all(v["normalized_equal"] for v in parity(directory, gate).values()), (
                "Initial payload mismatch"
            )
        return result
    finally:
        after = {p: digest(Path(p)) for p in preserved}
        harness.save(directory / "preserved-after.json", after)
        assert after == preserved


if __name__ == "__main__":
    raise SystemExit(main())
