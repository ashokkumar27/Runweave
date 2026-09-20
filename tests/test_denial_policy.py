from pydantic_ai import ToolDenied

from agent_runtime.workflow import RunWorkflow, partition_approvals


def test_partition_preserves_eligible_batch_and_refuses_changed_calls():
    calls = [
        {"id": "new-same", "tool": "record_note", "arguments": {"text": "original"}},
        {"id": "other", "tool": "future_write", "arguments": {}},
        {"id": "new-changed", "tool": "record_note", "arguments": {"text": "changed"}},
    ]
    eligible, refused = partition_approvals(calls, {"record_note"})
    assert eligible == [calls[1]]
    assert set(refused) == {"new-same", "new-changed"}
    assert all(isinstance(v, ToolDenied) for v in refused.values())
    assert partition_approvals(calls, set()) == (calls, {})


async def test_duplicate_signals_cannot_change_decision():
    workflow = RunWorkflow()
    await workflow.decision({"id": "call", "approved": False})
    await workflow.decision({"id": "call", "approved": True})
    assert workflow.decisions == {"call": False}


async def test_server_resumes_repeated_denials_without_publishing(monkeypatch):
    from types import SimpleNamespace

    from pydantic_ai import DeferredToolRequests
    from pydantic_ai.messages import ToolCallPart

    from agent_runtime import workflow as module
    from agent_runtime.schemas import Answer

    calls, writes = [], []
    coordinator = RunWorkflow()

    async def run(*args, **kwargs):
        calls.append(kwargs)
        index = len(calls) - 1
        if index:
            result = kwargs["deferred_tool_results"].approvals[f"call-{index - 1}"]
            assert result is False if index == 1 else isinstance(result, ToolDenied)
        output = (
            DeferredToolRequests(
                approvals=[
                    ToolCallPart(
                        "record_note",
                        {"text": "same" if index < 2 else "changed"},
                        tool_call_id=f"call-{index}",
                    )
                ]
            )
            if index < 3
            else Answer(answer="finished", value=5)
        )
        return SimpleNamespace(output=output, all_messages=lambda: [])

    async def io(fn, arg):
        writes.append((fn.__name__, arg))

    async def wait(approvals):
        coordinator.decisions[approvals[0]["id"]] = False

    monkeypatch.setattr(module.agent, "run", run)
    monkeypatch.setattr(module.workflow, "patched", lambda _: True)
    monkeypatch.setattr(module, "io", io)
    monkeypatch.setattr(coordinator, "wait_for_approval", wait)
    await coordinator.execute(
        {
            "id": "run",
            "input": "note",
            "history": [],
            "registration_id": "fake",
            "total_tokens_limit": 16000,
            "config": {
                "max_tool_calls": 5,
                "max_requests": 6,
                "max_tokens": 512,
                "instructions": "",
                "tools": ["record_note", "add"],
            },
        }
    )
    assert [name for name, _ in writes] == ["await_approval", "resume_run", "finish_run"]
    assert writes[-1][1]["status"] == "completed"
    assert len({id(call["usage"]) for call in calls}) == 1
