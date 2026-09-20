import pytest
from test_general_integration import backend
from test_general_semantic import complete, stub, submit

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("command_count", [1, 4])
async def test_failure_observation_repair_and_verified_completion(pg_store, monkeypatch, command_count):
    def action(context, i):
        if i == 0:
            return complete()  # Real failing check must feed the next decision.
        if i == 1:
            observed = str(context["observations"]) + str(context["last_result"])
            assert "AssertionError" in observed
            assert ("test_main.py" if command_count == 1 else "from main import value") in observed
            assert "exit_code" in observed and "cwd" in observed
            assert any(v["outcome"] == "fail" for v in context["verification_state"])
            return {"kind": "write", "files": [{"path": "main.py", "content_base64": "dmFsdWUgPSAxMgo="}]}
        assert any(a["result"].get("changed") for a in context["observations"]["actions"] if a["result"])
        return complete()

    calls = stub(monkeypatch, action)
    async with backend(pg_store, monkeypatch) as (client, temporal):
        ws = await client.workspace_create(
            {"main.py": b"value = 0\n", "test_main.py": b"from main import value\nassert value == 12\n"}
        )
        task = {
            "outcome": "Fix value",
            "constraints": ["Preserve test_main.py"],
            "criteria": [
                {
                    "id": "output",
                    "statement": "Correct value",
                    "evidence_policy": "check",
                    "checks": [
                        {"id": "check", "kind": "command", "argv": ["python", "test_main.py"]},
                        {"id": "bytes", "kind": "bytes", "path": "main.py", "expected": "dmFsdWUgPSAxMgo="},
                    ],
                }
            ],
        }
        if command_count == 4:
            task["criteria"][0]["checks"] = [
                {
                    "id": f"command{i}",
                    "kind": "command",
                    "argv": ["python", "-c", f"from main import value; assert {expression}"],
                }
                for i, expression in enumerate(
                    ["value == 12", "value > 0", "value // 3 == 4", "value * 2 == 24"]
                )
            ]
        run = await submit(client, ["workspace_write", "workspace_verify"], ws, task)
        result = await client.wait(run.id, timeout=80)
        assert result.status == "completed", (result.error, await client.operations(run.id))
        assert (await client.task(run.id))["assessment"]["accepted"]
        receipts = (await client.verifications(run.id))["items"]
        assert any(v["outcome"] == "fail" and not v["fresh"] for v in receipts)
        expected_checks = (
            {"check", "bytes", "runtime.syntax"}
            if command_count == 1
            else {"command0", "command1", "command2", "command3", "runtime.syntax"}
        )
        assert {v["check_id"] for v in receipts if v["fresh"] and v["outcome"] == "pass"} == expected_checks
        assert (
            await client.workspace_read(ws["workspace_id"], result.workspace["revision_id"], "test_main.py")
            == b"from main import value\nassert value == 12\n"
        )
        assert (
            await client.workspace_read(ws["workspace_id"], result.workspace["revision_id"], "main.py")
            == b"value = 12\n"
        )
        assert len(calls) == 3
        from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
        from temporalio.worker import Replayer

        from agent_runtime.general_workflow import GeneralWorkflow

        history = await temporal.get_workflow_handle("run:" + run.id).fetch_history()
        await Replayer(workflows=[GeneralWorkflow], plugins=[PydanticAIPlugin()]).replay_workflow(history)


async def test_invalid_sdk_output_then_write_and_verified_completion(pg_store, monkeypatch):
    def action(context, i):
        if i == 0:
            return {"kind": "write", "files": "invalid"}
        if i == 1:
            assert context["last_result"]["error"] == "invalid_semantic_output"
            return {"kind": "write", "files": [{"path": "main.py", "content_base64": "dmFsdWUgPSAxMgo="}]}
        return complete()

    calls = stub(monkeypatch, action)
    async with backend(pg_store, monkeypatch) as (client, temporal):
        ws = await client.workspace_create({"main.py": b"value = 0\n"})
        run = await submit(
            client,
            ["workspace_write", "workspace_verify"],
            ws,
            {
                "outcome": "Correct value",
                "criteria": [
                    {
                        "id": "output",
                        "statement": "Exact value",
                        "evidence_policy": "check",
                        "checks": [
                            {
                                "id": "bytes",
                                "kind": "bytes",
                                "path": "main.py",
                                "expected": "dmFsdWUgPSAxMgo=",
                            }
                        ],
                    }
                ],
            },
        )
        result = await client.wait(run.id, timeout=60)
        assert result.status == "completed", (result.error, await client.operations(run.id))
        assert (await client.task(run.id))["assessment"]["accepted"]
        assert len(calls) == 3
        assert (await client.budget(run.id))["v3"]["counters"]["model_attempts"] == 3
        assert {
            v["check_id"]
            for v in (await client.verifications(run.id))["items"]
            if v["fresh"] and v["outcome"] == "pass"
        } == {"bytes", "runtime.syntax"}
        from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
        from temporalio.worker import Replayer

        from agent_runtime.general_workflow import GeneralWorkflow

        history = await temporal.get_workflow_handle("run:" + run.id).fetch_history()
        await Replayer(workflows=[GeneralWorkflow], plugins=[PydanticAIPlugin()]).replay_workflow(history)
