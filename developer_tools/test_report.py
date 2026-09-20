import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("dev_report", Path(__file__).with_name("report.py"))
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def fixture():
    return {
        "mode": "live",
        "physical_calls": 3,
        "scenarios": [
            {
                "cell": "gpt-5.6-luna/recovery",
                "model": "gpt-5.6-luna",
                "status": "passed",
                "run": {"status": "completed"},
                "task": {"assessment": {"accepted": True}},
                "calls_before": 0,
                "calls_after": 3,
                "budget": {"reported_tokens": 800},
                "operations": {
                    "items": [
                        {"id": "action:0", "status": "complete", "result": {"exit_code": 1}},
                        {"id": "action:1", "status": "complete", "result": {"exit_code": 0}},
                    ],
                    "next_cursor": None,
                },
                "verifications": {"items": [{"outcome": "pass", "fresh": True}], "next_cursor": None},
            }
        ],
    }


def test_recovered_failure_does_not_change_success():
    cell = report.summarize(fixture())["cells"][0]
    assert cell["status"] == "passed" and cell["accepted"] is True
    assert cell["first_recorded_failure"]["failure"] == "command_nonzero_exit"
    assert cell["calls"] == 3 and cell["fresh_pass_receipts"] == 1
    assert not cell["evidence_incomplete"]


def test_missing_and_paginated_evidence_stays_unknown():
    data = fixture()
    cell = data["scenarios"][0]
    cell.pop("calls_after")
    cell.pop("budget")
    cell["operations"]["next_cursor"] = "next"
    summary = report.summarize(data)["cells"][0]
    assert summary["calls"] is None and summary["reported_tokens"] is None
    assert summary["evidence_incomplete"]
    assert report.summarize({"scenarios": [{}]})["cells"][0]["evidence_incomplete"]


def test_raw_content_and_secret_like_metadata_are_never_printed():
    data = fixture()
    cell = data["scenarios"][0]
    secret = "sk-proj-PRIVATE-CONTENT"
    cell.update(cell=secret, model=secret, reason=secret, oracle_errors=[secret])
    cell["run"].update(error=secret, output=secret)
    cell["operations"]["items"][0] = {
        "id": secret,
        "status": "failed",
        "result": {"error": secret, "stdout": secret},
        "diagnostics": {"failure_type": secret, "validation_feedback": secret},
    }
    summary = report.summarize(data, selected=secret)
    assert secret not in json.dumps(summary)
    assert secret not in report.render(summary)


def test_cell_selection_and_recent_trace_are_bounded():
    data = fixture()
    summary = report.summarize(data, "gpt-5.6-luna/recovery", recent=1)
    assert len(summary["cells"][0]["recent_operations"]) == 1
    with pytest.raises(ValueError):
        report.summarize(data, "missing")


def test_reader_is_non_mutating_and_rejects_partial_json(tmp_path):
    path = tmp_path / "evidence.json"
    original = json.dumps(fixture()).encode()
    path.write_bytes(original)
    assert report.read_evidence(path)["physical_calls"] == 3
    assert path.read_bytes() == original
    path.write_text('{"scenarios":')
    with pytest.raises(ValueError):
        report.read_evidence(path)


def test_test_log_only_returns_final_counts(tmp_path):
    path = tmp_path / "pytest.log"
    path.write_text("secret traceback\n2 failed, 5 passed in 1.23s\n")
    assert report.test_summary(path) == {"failed": 2, "passed": 5}
    path.write_text("still running; secret traceback\n")
    assert report.test_summary(path) == {"status": "no_final_summary"}
