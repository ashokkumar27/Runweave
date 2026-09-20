"""No-paid audit of retained exact wire payloads and public comparison evidence."""

import argparse
import copy
import hashlib
import json
import sqlite3
from pathlib import Path

from scripts import model_comparison_budget as guard
from scripts.lightweight_confidence import save
from scripts.model_comparison import DIRECTORY, LEDGER


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def normalized(body):
    body = copy.deepcopy(body)
    body.pop("model")
    for item in body["input"]:
        if item.get("role") == "user" and isinstance(item.get("content"), str):
            context = json.loads(item["content"])
            for key in ("available_child_budget", "remaining"):
                if isinstance(context.get(key), dict):
                    context[key]["active_seconds"] = "<clock>"
            item["content"] = json.dumps(context, sort_keys=True)
    return body


def audit(mode):
    report = json.loads((DIRECTORY / (mode + ".json")).read_text())
    records = [json.loads(line) for line in (DIRECTORY / (mode + ".wire.jsonl")).read_text().splitlines()]
    result = {"mode": mode, "initial_payloads": {}, "calls": [], "cells": []}
    for name in guard.LIMITS:
        initial = [
            r
            for r in records
            if r["context"]["scenario"] == name and r["context"]["operation_id"].endswith(":model:0")
        ]
        result["initial_payloads"][name] = {
            "models": [r["body"]["model"] for r in initial],
            "exact_sha256": {r["body"]["model"]: sha(r["body"]) for r in initial},
            "normalized_sha256": {r["body"]["model"]: sha(normalized(r["body"])) for r in initial},
            "normalized_equal": len({sha(normalized(r["body"])) for r in initial}) == 1,
            "excluded_fields": ["model", "input[0].content.available_child_budget.active_seconds"],
        }
    for r in records:
        contexts = [
            json.loads(i["content"])
            for i in r["body"]["input"]
            if i.get("role") == "user" and isinstance(i.get("content"), str)
        ]
        actions = []
        for o in r.get("response", {}).get("output", []):
            if o.get("type") == "function_call":
                try:
                    actions.append(json.loads(o["arguments"]))
                except (KeyError, ValueError):
                    actions.append({"unparsed_arguments": True})
        result["calls"].append(
            {
                **r["context"],
                "model": r["body"]["model"],
                "projected_context": contexts,
                "context_sha256": sha(contexts),
                "instructions": r["body"]["instructions"],
                "instructions_sha256": sha(r["body"]["instructions"]),
                "wire_schema": r["body"]["tools"],
                "wire_schema_sha256": sha(r["body"]["tools"]),
                "raw_decisions": actions,
                "usage": r.get("response", {}).get("usage"),
                "http_status": r.get("status_code"),
            }
        )
    for cell in report["scenarios"]:
        own = [r for r in result["calls"] if r["root_id"] == cell.get("run_id")]
        usage = {
            k: sum((r["usage"] or {}).get(k, 0) for r in own)
            for k in ["input_tokens", "output_tokens", "total_tokens"]
        }
        operations = cell.get("operations", {}).get("items", [])
        decisions = [{"id": o["id"], "result": o.get("result")} for o in operations if ":model:" in o["id"]]
        result["cells"].append(
            {
                "cell": cell["cell"],
                "status": cell["status"],
                "availability": cell.get("model_availability"),
                "physical_calls": cell.get("calls_after", 0) - cell["calls_before"],
                "usage": usage,
                "accepted": cell.get("run", {}).get("status") == "completed",
                "downloads": cell.get("downloads"),
                "oracle_errors": cell.get("oracle_errors"),
                "runtime_decisions": decisions,
                "fresh_verifications": [
                    v
                    for v in cell.get("verifications", {}).get("items", [])
                    if v["fresh"] and v["outcome"] == "pass"
                ],
            }
        )
    prior = Path("var/acceptance/lightweight-confidence-v1/preflight-gate.json")
    proof = json.loads(prior.read_text())
    result["retained_parallel_proof"] = {
        "path": str(prior),
        "sha256": hashlib.sha256(prior.read_bytes()).hexdigest(),
        "reservation_measurements": proof["reservation_measurements"],
        "scenarios": [s for s in proof["scenarios"] if s["name"] == "parallel"],
        "interpretation": "Left: 5874 + 1005 = 6879 > 6208. Right: 5880 + 1008 = 6888 > 6208. Parent: 8494 + 8493 = 16987 > 16000. No new parallel execution.",
    }
    result["omissions"] = {
        "csv": "Checks project kind/argv/path, omit expected bytes. summary.csv headers valid_rows,rejected_rows,total are not specified to the model.",
        "recovery": "files lists inputs.csv; last_result includes exit_code and output names, but not downloaded command stdout/stderr text.",
        "history": "previous_turns means prior user turns, not prior actions within this root. Only last_result survives in each current context. Explicit remaining root model attempts are absent; available_child_budget is a distinct child allocation and report_only is present.",
    }
    if mode == "live":
        with sqlite3.connect(LEDGER) as db:
            result["ledger_attempts"] = [
                dict(zip([d[0] for d in cursor.description], row))
                for cursor in [db.execute("SELECT * FROM attempts")]
                for row in cursor
            ]
            result["ledger_outcomes"] = db.execute("SELECT * FROM outcomes").fetchall()
            result["terminals"] = db.execute("SELECT * FROM terminals").fetchall()
        assert len(result["ledger_attempts"]) == report["physical_calls"] <= 60
        assert len(records) <= report["physical_calls"]
        result["missing_wire_outcomes"] = report["physical_calls"] - len(records)
    save(DIRECTORY / (mode + "-audit.json"), result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["preflight", "live"], default="preflight")
    args = parser.parse_args()
    result = audit(args.mode)
    print(
        json.dumps(
            {
                "cells": len(result["cells"]),
                "calls": len(result["calls"]),
                "parity": {k: v["normalized_equal"] for k, v in result["initial_payloads"].items()},
            }
        )
    )


if __name__ == "__main__":
    main()
