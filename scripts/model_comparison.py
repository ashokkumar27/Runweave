"""One immutable, bounded live comparison; default uses the real SDK with fake transport."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from scripts import model_comparison_budget as guard
from scripts.lightweight_confidence import execute, save
from scripts.lightweight_fixtures import config, fixture

DIRECTORY = Path("var/acceptance/lightweight-model-comparison-v1")
LEDGER = DIRECTORY.with_suffix(".sqlite")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    preserved = [Path("AGENTS.md"), Path("/tmp/agent-runtime-acceptance-budget.sqlite")]
    for campaign in ("general-runtime-v3", "lightweight-confidence-v1", "toolkits-subagents-v1"):
        preserved.extend(Path("var/acceptance/" + campaign + suffix) for suffix in (".sqlite", ".started"))
    snapshot = {str(p): digest(p) for p in preserved}
    before = DIRECTORY / "preserved-before.json"
    if before.exists():
        assert json.loads(before.read_text()) == snapshot, "Preserved files changed"
    else:
        save(before, snapshot)
    registration = next(
        r for r in json.loads(Path("config/models.json").read_text()) if r["model"] == guard.MODELS[0]
    )
    registry = DIRECTORY / "models.json"
    registrations = [{**registration, "model": m, "upstream_model": m} for m in guard.MODELS]
    if registry.exists():
        assert json.loads(registry.read_text()) == registrations
    else:
        save(registry, registrations)
    sources = [
        *Path("agent_runtime").glob("*.py"),
        *Path("config").glob("*.json"),
        Path("scripts/lightweight_fixtures.py"),
    ]
    frozen = {"sources": {str(p): digest(p) for p in sources}, "fixtures": {}}
    for name in guard.LIMITS:
        f = fixture(name)
        f = {
            **f,
            "files": {p: v.hex() for p, v in f["files"].items()},
            "expected": {p: v.hex() for p, v in f["expected"].items()},
        }
        frozen["fixtures"][name] = {
            "fixture": f,
            "config": config(name).model_dump(mode="json"),
            "sha256": hashlib.sha256(json.dumps(f, sort_keys=True).encode()).hexdigest(),
        }
    path = DIRECTORY / "frozen-inputs.json"
    if path.exists():
        assert json.loads(path.read_text()) == frozen, "Original source or fixture changed"
    else:
        save(path, frozen)
    return registry, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    registry, snapshot = freeze()
    if args.live:
        preflight = json.loads((DIRECTORY / "preflight-gate.json").read_text())
        audit = json.loads((DIRECTORY / "preflight-audit.json").read_text())
        assert {s["cell"] for s in preflight["scenarios"]} == set(guard.MANIFEST["scenario_limits"])
        assert len(preflight["scenarios"]) == 12 and all(
            s["status"] == "passed" for s in preflight["scenarios"]
        )
        assert all(
            v["normalized_equal"] and set(v["models"]) == set(guard.MODELS)
            for v in audit["initial_payloads"].values()
        )
        execution = {
            str(p): digest(p)
            for p in [
                *Path("scripts").glob("model_comparison*.py"),
                Path("scripts/lightweight_budget.py"),
                Path("scripts/lightweight_confidence.py"),
                Path("scripts/acceptance_worker.py"),
                Path("scripts/lightweight_stub_worker.py"),
            ]
        }
        target = DIRECTORY / "execution-source-hashes.json"
        if target.exists():
            assert json.loads(target.read_text()) == execution
        else:
            save(target, execution)
    try:
        return asyncio.run(
            execute(
                args.live, directory=DIRECTORY, ledger_path=LEDGER, campaign_guard=guard, registry=registry
            )
        )
    finally:
        after = {p: digest(Path(p)) for p in snapshot}
        save(DIRECTORY / "preserved-after.json", after)
        assert after == snapshot, "Historical ledger or AGENTS changed"


if __name__ == "__main__":
    raise SystemExit(main())
