"""Completion-loop-v1: exact-fixture SDK preflight then one authorized live campaign."""

import argparse
import asyncio
import json
from pathlib import Path

from scripts import completion_loop_budget as guard
from scripts import lightweight_confidence as harness
from scripts.completion_loop_fixtures import config, fixture
from scripts.model_comparison import digest

DIRECTORY = Path("var/acceptance/completion-loop-v1")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    paths = [
        Path("AGENTS.md"),
        Path("/tmp/agent-runtime-acceptance-budget.sqlite"),
        *Path("var/acceptance").glob("*.sqlite"),
        *Path("var/acceptance").glob("*.started"),
        *Path("docs").glob("acceptance-*.json"),
        *Path("docs/fixtures").rglob("*"),
        Path("scripts/lightweight_fixtures.py"),
    ]
    preserved = {str(p): digest(p) for p in paths if p.is_file() and "completion-loop-v1" not in str(p)}
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    target = DIRECTORY / "preserved-before.json"
    if target.exists():
        assert json.loads(target.read_text()) == preserved
    else:
        harness.save(target, preserved)
    sources = {
        str(p): digest(p)
        for p in [
            *Path("agent_runtime").glob("*.py"),
            *Path("scripts").glob("*.py"),
            *Path("config").glob("*.json"),
        ]
    }
    frozen = {
        "sources": sources,
        "fixtures": {
            name: {
                "prompt": fixture(name)["prompt"],
                "task": fixture(name)["task"],
                "files": {p: b.hex() for p, b in fixture(name)["files"].items()},
                "expected": {p: b.hex() for p, b in fixture(name)["expected"].items()},
                "config": config(name).model_dump(mode="json"),
            }
            for name in guard.MANIFEST["scenario_limits"]
        },
    }
    if args.live:
        assert json.loads((DIRECTORY / "preflight-source.json").read_text()) == frozen, (
            "Code/fixtures changed since preflight"
        )
        gate = json.loads((DIRECTORY / "preflight-gate.json").read_text())
        assert len(gate["scenarios"]) == 5 and all(s["status"] == "passed" for s in gate["scenarios"])
        assert gate.get("verified_source") == frozen, "Passing preflight belongs to different code/fixtures"
        harness.save(DIRECTORY / "live-source.json", frozen)
    else:
        harness.save(DIRECTORY / "preflight-source.json", frozen)
    harness.fixture, harness.config = fixture, config
    try:
        result = asyncio.run(
            harness.execute(
                args.live,
                directory=DIRECTORY,
                ledger_path=DIRECTORY.with_suffix(".sqlite"),
                campaign_guard=guard,
            )
        )
        if not args.live and result == 0:
            gate_path = DIRECTORY / "preflight-gate.json"
            gate = json.loads(gate_path.read_text())
            harness.save(gate_path, {**gate, "verified_source": frozen})
        return result
    finally:
        after = {p: digest(Path(p)) for p in preserved}
        harness.save(DIRECTORY / "preserved-after.json", after)
        assert after == preserved


if __name__ == "__main__":
    raise SystemExit(main())
