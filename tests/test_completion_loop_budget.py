import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts import completion_loop_budget as guard
from scripts.completion_loop_fixtures import config, fixture


def test_campaign_72_physical_calls_nontransferable_and_terminal(tmp_path):
    path = tmp_path / "completion.sqlite"
    guard.initialize(path)
    for name in guard.MANIFEST["scenario_limits"]:
        guard.admit(path, name, name)

    def attempt(job):
        name, i = job
        try:
            guard.reserve(
                path,
                dict(scenario=name, run_id=name, root_id=name, operation_id=str(i), attempt_id=str(i)),
                guard.MANIFEST["scenario_caps"][name],
            )
            return True
        except RuntimeError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert (
            sum(
                pool.map(
                    attempt,
                    [
                        (n, i)
                        for n, limit in guard.MANIFEST["scenario_limits"].items()
                        for i in range(limit + 2)
                    ],
                )
            )
            == 72
        )
    assert guard.initialize(path) == 72
    with sqlite3.connect(path) as db:
        assert (
            dict(db.execute("SELECT scenario,count(*) FROM attempts GROUP BY scenario"))
            == guard.MANIFEST["scenario_limits"]
        )
    guard.finish(path, "bug", "failed")
    with pytest.raises(RuntimeError, match="terminal"):
        guard.admit(path, "bug", "another-root")


def test_clarified_requirements_are_public_and_caps_explicit():
    assert fixture("bug")["task"]["constraints"] == ["Preserve these files byte-for-byte: test_main.py"]
    assert fixture("recovery")["task"]["constraints"] == [
        "Preserve these files byte-for-byte: report.py, inputs.csv"
    ]
    assert "exactly 12" in fixture("direct")["prompt"]
    assert "valid_rows,rejected_rows,total" in fixture("csv")["prompt"]
    for name, limit in guard.MANIFEST["scenario_limits"].items():
        c = config(name)
        assert c.general.limits.model_attempts == limit
        assert c.general.limits.total_tokens == 16000
        assert c.model == "gpt-5.6-luna" and c.max_tokens <= 2048
        assert c.general.delegation is None or name == "parallel"
