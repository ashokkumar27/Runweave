"""Retained live responses, real Responses SDK, fake transport, authoritative backend."""

import copy
import json
from pathlib import Path

import httpx
import pytest
from test_general_integration import backend
from test_general_semantic import http_client, submit
from test_model_adapter import registration

from agent_runtime.general_runtime import general_step
from agent_runtime.model_adapter import build_model
from scripts.completion_loop_fixtures import fixture

CAPTURE = json.loads((Path(__file__).parent / "fixtures/completion-models-responses.json").read_text())


def sdk_replay(monkeypatch, sequence):
    contexts = []
    monkeypatch.setenv("ADAPTER_TEST_KEY", "offline-test-key")
    # Real SDK serialization; every constructed client has an in-memory transport.
    monkeypatch.setattr("pydantic_ai.models.ALLOW_MODEL_REQUESTS", True)

    async def respond(request):
        body = json.loads(await request.aread())
        assert body["parallel_tool_calls"] is False
        context = json.loads(body["input"][0]["content"])
        contexts.append(context)
        item = sequence(context, len(contexts) - 1)
        if isinstance(item, str):
            output = copy.deepcopy(CAPTURE[item]["output"])
        else:
            output = [
                {
                    "type": "function_call",
                    "id": "fc_stub",
                    "call_id": "call_stub",
                    "arguments": json.dumps({"action": item}),
                    "status": "completed",
                }
            ]
        for o in output:
            if o["type"] == "function_call":
                o["name"] = body["tools"][0]["name"]
        return httpx.Response(
            200,
            json={
                "id": "resp_stub",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": body["model"],
                "output": output,
                "usage": {"input_tokens": 300, "output_tokens": 100, "total_tokens": 400},
            },
        )

    monkeypatch.setattr(
        "agent_runtime.general_runtime.build_model",
        lambda _: build_model(
            registration("openai_responses", "https://api.openai.com/v1"),
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ),
    )
    return contexts


@pytest.mark.parametrize("capture", ["invalid_check", "invalid_criteria"])
async def test_captured_selector_error_is_repairable(store, monkeypatch, capture):
    sdk_replay(monkeypatch, lambda *_: capture)
    f = fixture("csv")
    async with http_client(store) as client:
        workspace = await client.workspace_create(f["files"])
        run = await submit(client, f["tools"], workspace, f["task"])
        assert (await general_step({"run_id": run.id, "completion_loop": 2}))["rejected"]
        ops = (await client.operations(run.id))["items"]
        assert len(ops) == 1 and ops[0]["result"] is None
        assert (await client.budget(run.id))["v3"]["counters"]["tool_attempts"] == 0


@pytest.mark.integration
@pytest.mark.parametrize("name", ["csv", "recovery"])
async def test_captured_failure_repairs_with_real_backend(pg_store, monkeypatch, name):
    def sequence(context, i):
        if name == "csv":
            if i < 3:
                if i == 2:
                    assert context["last_result"]["error"] == "invalid_semantic_output"
                return ["csv_write", "invalid_check", "multiple_checks"][i]
            assert context["last_result"]["error"] == "multiple_semantic_outputs"
        else:
            if i < 2:
                return ["recovery_failed", "recovery_uncommitted"][i]
            if i == 2:
                effect = context["last_result"]["workspace_effect"]
                assert effect == {
                    "commit_requested": False,
                    "persisted": False,
                    "changed_paths": ["result.csv"],
                }
                assert "result.csv" not in context["files"]
                action = json.loads(CAPTURE["recovery_uncommitted"]["output"][0]["arguments"])["action"]
                return {**action, "commit": True}
            assert context["last_result"]["workspace_effect"]["persisted"]
        return {"kind": "complete", "answer": "Verified."}

    contexts = sdk_replay(monkeypatch, sequence)
    f = fixture(name)
    async with backend(pg_store, monkeypatch) as (client, temporal):
        workspace = await client.workspace_create(f["files"])
        run = await submit(client, f["tools"], workspace, f["task"])
        result = await client.wait(run.id, timeout=80)
        assert result.status == "completed", (result.error, await client.operations(run.id))
        assert len(contexts) == 4
        for p, expected in {**f["expected"], **{p: f["files"][p] for p in f["preserve"]}}.items():
            assert (
                await client.workspace_read(workspace["workspace_id"], result.workspace["revision_id"], p)
                == expected
            )
        assert (await client.task(run.id))["assessment"]["accepted"]
        checks = (await client.verifications(run.id))["items"]
        assert {v["check_id"] for v in checks if v["fresh"] and v["outcome"] == "pass"} == {
            "runtime.syntax",
            *[s["id"] for s in f["task"]["criteria"][0]["checks"]],
        }
        from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
        from temporalio.worker import Replayer

        from agent_runtime.general_workflow import GeneralWorkflow

        history = await temporal.get_workflow_handle("run:" + run.id).fetch_history()
        await Replayer(workflows=[GeneralWorkflow], plugins=[PydanticAIPlugin()]).replay_workflow(history)
