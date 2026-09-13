"""Deterministic coordination only. All storage/model/tool I/O is in activities."""

import asyncio
import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    import annotated_types  # noqa: F401 -- preload validation dependencies for sandbox replay
    from pydantic_ai import DeferredToolRequests, DeferredToolResults
    from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow
    from pydantic_ai.exceptions import UsageLimitExceeded
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    from pydantic_ai.usage import RunUsage, UsageLimits

    from .activities import await_approval, finish_run, load_run, resume_run
    from .runtime import Deps, agent


async def io(fn, arg):
    return await workflow.execute_activity(
        fn,
        arg,
        start_to_close_timeout=timedelta(seconds=15),
        schedule_to_close_timeout=timedelta(seconds=60),
        retry_policy=RetryPolicy(maximum_attempts=4),
    )


@workflow.defn
class RunWorkflow(PydanticAIWorkflow):
    __pydantic_ai_agents__ = [agent]

    def __init__(self):
        self.decisions: dict[str, bool] = {}

    @workflow.signal
    async def decision(self, data: dict):
        # Immutable decisions in PostgreSQL; duplicate outbox delivery is harmless.
        self.decisions.setdefault(data["id"], data["approved"])

    @workflow.run
    async def run(self, run_id: str):
        try:
            data = await io(load_run, run_id)
            if data["status"] in {"completed", "failed", "cancelled"}:
                return
            if not data["model_available"]:
                await io(
                    finish_run, {"run_id": run_id, "status": "failed", "error": "provider_not_configured"}
                )
                return
            config = data["config"]
            # Includes approval waiting and every retry; uses Temporal's deterministic clock.
            async with asyncio.timeout(config["timeout_seconds"]):
                await self.execute(data)
        except asyncio.CancelledError:
            await asyncio.shield(io(finish_run, {"run_id": run_id, "status": "cancelled"}))
            raise
        except UsageLimitExceeded:
            await io(finish_run, {"run_id": run_id, "status": "failed", "error": "usage_limit"})
        except TimeoutError:
            await io(finish_run, {"run_id": run_id, "status": "failed", "error": "run_timeout"})
        except Exception:
            # Never persist raw provider/tool exceptions, prompts or credentials in public errors.
            await io(finish_run, {"run_id": run_id, "status": "failed", "error": "execution_failed"})

    async def execute(self, data):
        config, run_id = data["config"], data["id"]
        history = ModelMessagesTypeAdapter.validate_python(data["history"])
        usage = RunUsage()
        prompt, deferred = data["input"], None
        for _ in range(config["max_tool_calls"] + 1):
            result = await agent.run(
                prompt,
                model=f"{config['provider']}:{config['model']}",
                instructions=config["instructions"],
                deps=Deps(run_id, config["tools"]),
                message_history=history,
                deferred_tool_results=deferred,
                usage=usage,
                usage_limits=UsageLimits(
                    request_limit=config["max_requests"],
                    tool_calls_limit=config["max_tool_calls"],
                    total_tokens_limit=16000,
                ),
                model_settings={"max_tokens": config["max_tokens"], "timeout": 30},
            )
            history = result.all_messages()
            if not isinstance(result.output, DeferredToolRequests):
                serialized = ModelMessagesTypeAdapter.dump_python(history, mode="json")
                # Bound session history and Temporal payloads; refuse silent truncation.
                if len(json.dumps(serialized)) > 250_000:
                    await io(
                        finish_run, {"run_id": run_id, "status": "failed", "error": "session_history_limit"}
                    )
                    return
                await io(
                    finish_run,
                    {
                        "run_id": run_id,
                        "status": "completed",
                        "output": result.output.model_dump(),
                        "history": serialized,
                        "usage": {
                            "requests": usage.requests,
                            "tool_calls": usage.tool_calls,
                            "input_tokens": usage.input_tokens,
                            "output_tokens": usage.output_tokens,
                        },
                    },
                )
                return
            approvals = [
                {"id": call.tool_call_id, "tool": call.tool_name, "arguments": call.args_as_dict()}
                for call in result.output.approvals
            ]
            if not approvals or result.output.calls:
                raise ValueError("Unsupported deferred tool request")
            await io(await_approval, {"run_id": run_id, "approvals": approvals})
            await workflow.wait_condition(lambda: all(a["id"] in self.decisions for a in approvals))
            deferred = DeferredToolResults(approvals={a["id"]: self.decisions[a["id"]] for a in approvals})
            await io(resume_run, run_id)
            prompt = None
        await io(finish_run, {"run_id": run_id, "status": "failed", "error": "tool_budget_exhausted"})
