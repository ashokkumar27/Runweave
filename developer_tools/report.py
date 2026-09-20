"""Read saved acceptance evidence; print bounded diagnostics without raw model/tool content."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024
STATUSES = {
    "passed",
    "failed",
    "blocked",
    "running",
    "pending",
    "queued",
    "complete",
    "completed",
    "cancelled",
}
STOP_CODES = {
    "budget_exhausted",
    "no_progress",
    "execution_stopped",
    "model_execution_failed",
    "task_blocked",
    "context_limit",
    "run_timeout",
    "approval_timeout",
    "sandbox_unavailable",
    "workflow_closed_without_result",
    "stale_completion_phase",
    "capability_not_authorized",
    "invalid_selector",
    "child_grant_denied",
    "invalid_source_evidence",
}
ACTION_KINDS = {
    "read",
    "write",
    "command",
    "verify",
    "invoke",
    "complete",
    "blocked",
    "discover",
    "assign",
    "join",
    "merge",
    "inspect",
    "source",
    "patch",
    "plan",
}


def obj(value):
    return value if isinstance(value, dict) else {}


def items(value):
    return value if isinstance(value, list) else []


def number(value):
    return value if type(value) is int and value >= 0 else None


def label(value):
    # Metadata only. Suppress secret-like or arbitrary free-form text even in identifier fields.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,100}", value):
        return "unknown"
    if re.search(r"sk[-_]|secret|password|bearer|token|api[-_]?key", value, re.I):
        return "redacted"
    return value


def status(value):
    return value if isinstance(value, str) and value in STATUSES else "unknown"


def code(value, fallback="unknown"):
    return value if isinstance(value, str) and value in STOP_CODES else fallback


def operation_summary(raw, index):
    operation = obj(raw)
    result = obj(operation.get("result"))
    diagnostics = obj(operation.get("diagnostics"))
    action = obj(result.get("action"))
    kind = action.get("kind")
    failure = None
    if result.get("error"):
        failure = code(result["error"], "operation_error")
    elif diagnostics.get("validation_errors") or diagnostics.get("validation_feedback"):
        failure = "validation_feedback"
    elif diagnostics.get("failure_type"):
        failure = "model_or_runtime_error"
    elif operation.get("status") == "failed":
        failure = "operation_failed"
    elif type(result.get("exit_code")) is int and result["exit_code"] != 0:
        failure = "command_nonzero_exit"
    elif result.get("outcome") == "fail":
        failure = "check_failed"
    elif result.get("accepted") is False:
        failure = "completion_rejected"
    return {
        "index": index,
        "id": label(operation.get("id")),
        "status": status(operation.get("status")),
        "action": kind if isinstance(kind, str) and kind in ACTION_KINDS else None,
        "exit_code": result.get("exit_code") if type(result.get("exit_code")) is int else None,
        "failure": failure,
    }


def summarize(data, selected=None, recent=5):
    if not isinstance(data, dict) or not isinstance(data.get("scenarios"), list):
        raise ValueError("Expected an acceptance report with a scenarios array.")
    rows = []
    for index, raw in enumerate(data["scenarios"]):
        cell = obj(raw)
        identity = cell.get("cell") or cell.get("name")
        if selected is not None and identity != selected:
            continue
        run, budget = obj(cell.get("run")), obj(cell.get("budget"))
        page = obj(cell.get("operations"))
        operations = [operation_summary(o, i) for i, o in enumerate(items(page.get("items")))]
        before, after = number(cell.get("calls_before")), number(cell.get("calls_after"))
        calls = after - before if before is not None and after is not None and after >= before else None
        checks = obj(cell.get("verifications"))
        assessment = obj(obj(cell.get("task")).get("assessment"))
        accepted = assessment.get("accepted")
        failures = [o for o in operations if o["failure"]]
        row = {
            "cell": label(identity),
            "model": label(cell.get("model")),
            "status": status(cell.get("status")),
            "run_status": status(run.get("status")),
            "accepted": accepted if type(accepted) is bool else None,
            "calls": calls,
            "reported_tokens": number(budget.get("reported_tokens")),
            "stop": code(run.get("stop_reason") or run.get("error") or cell.get("reason")),
            "first_recorded_failure": failures[0] if failures else None,
            "fresh_pass_receipts": sum(
                obj(v).get("fresh") is True and obj(v).get("outcome") == "pass"
                for v in items(checks.get("items"))
            ),
            "evidence_incomplete": "items" not in page
            or page.get("next_cursor") is not None
            or "items" not in checks
            or checks.get("next_cursor") is not None,
            "evidence_pointer": f"/scenarios/{index}",
        }
        if selected is not None:
            row["recent_operations"] = operations[-recent:] if recent else []
        rows.append(row)
    if selected is not None and not rows:
        raise ValueError("Cell not found; use an exact cell identifier from the summary.")
    return {
        "mode": data.get("mode") if data.get("mode") in ("live", "preflight", "fake") else "unknown",
        "recorded_cells": len(rows),
        "outcomes": dict(Counter(row["status"] for row in rows)),
        "campaign_physical_calls": number(data.get("physical_calls")),
        "cells": rows,
    }


def read_evidence(path):
    with path.open("rb") as source:
        encoded = source.read(MAX_BYTES + 1)
    if len(encoded) > MAX_BYTES:
        raise ValueError("Evidence exceeds the 64 MiB read limit; select a smaller saved report.")
    try:
        return json.loads(encoded)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Evidence is incomplete or invalid JSON; retry after its writer finishes.") from exc


def test_summary(path):
    with path.open("rb") as source:
        source.seek(0, 2)
        source.seek(max(0, source.tell() - 65536))
        lines = source.read().decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        if re.search(r"\bin \d+(?:\.\d+)?s", line):
            counts = re.findall(r"(\d+) (passed|failed|errors?|skipped|deselected|xfailed|xpassed)\b", line)
            if counts:
                return {key: int(value) for value, key in counts}
    return {"status": "no_final_summary"}


def render(report):
    lines = [f"{report['mode']}: {report['recorded_cells']} recorded cells; {report['outcomes']}"]
    lines.append("cell | result | calls | tokens | first recorded failure | stop")
    for row in report["cells"]:
        failure = row["first_recorded_failure"]
        detail = f"{failure['failure']} at operation[{failure['index']}]" if failure else "none recorded"
        lines.append(
            f"{row['cell']} | {row['status']} | {row['calls']} | {row['reported_tokens']} | {detail} | {row['stop']}"
        )
        if "recent_operations" in row:
            lines.append(
                f"  evidence {row['evidence_pointer']}; fresh pass receipts: {row['fresh_pass_receipts']}"
            )
            for op in row["recent_operations"]:
                lines.append(
                    f"  operation[{op['index']}] {op['action'] or '-'} {op['status']} {op['failure'] or ''}"
                )
        if row["evidence_incomplete"]:
            lines.append("  Partial evidence: operation/check records are absent or paginated.")
    if "test_logs" in report:
        lines.extend(f"test log {i + 1}: {value}" for i, value in enumerate(report["test_logs"]))
    lines.append(
        "First recorded failure is an observation, not a root-cause finding. None means unavailable."
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--cell", help="Exact model/task cell; includes a short recent-operation trace")
    parser.add_argument("--recent", type=int, choices=range(11), default=5, metavar="0..10")
    parser.add_argument("--test-log", type=Path, action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = summarize(read_evidence(args.evidence), args.cell, args.recent)
        if args.test_log:
            report["test_logs"] = [test_summary(path) for path in args.test_log]
    except (OSError, ValueError):
        parser.exit(2, "Cannot summarize: check the report path/format, selected cell and test-log paths.\n")
    print(json.dumps(report, indent=2) if args.json else render(report))


if __name__ == "__main__":
    main()
