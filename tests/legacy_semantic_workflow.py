"""Deterministic v3 coordination; all I/O and model interpretation live in activities."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="GeneralWorkflow")
class LegacySemanticWorkflow:
    def __init__(self):
        self.decisions = {}

    @workflow.signal
    def decision(self, value: dict):
        self.decisions[value["id"]] = value["approved"]

    async def call(self, name, value, seconds=90):
        return await workflow.execute_activity(
            name,
            value,
            start_to_close_timeout=timedelta(seconds=seconds),
            retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=2)),
        )

    @workflow.run
    async def run(self, run_id: str):
        children = {}
        semantic = workflow.patched("v3-semantic-completion-v1")
        try:
            state = await self.call("general_state", run_id)
            active = state["policy"]["limits"]["active_seconds"]
            approval_remaining = state["approval_wait_seconds"]
            previous = workflow.now()
            while True:
                state = await self.call("general_state", run_id)
                active = state["active_remaining"]
                if active <= 0:
                    await self.call("general_stop", {"run_id": run_id, "code": "run_timeout"})
                    return
                decision = await self.call(
                    "general_step",
                    {
                        "run_id": run_id,
                    }
                    if semantic
                    else run_id,
                    min(90, max(1, active)),
                )
                if decision["decision"]["action"]["kind"] == "complete" and children:
                    await asyncio.gather(*children.values(), return_exceptions=True)
                payload = {"run_id": run_id, **decision}
                if (
                    semantic
                    and decision.get("semantic")
                    and decision["decision"]["action"]["kind"] == "complete"
                ):
                    while True:
                        prepared = await self.call("general_completion", payload)
                        if prepared.get("stale"):
                            await self.call(
                                "general_stop", {"run_id": run_id, "code": "stale_completion_phase"}
                            )
                            return
                        result = await self.call("general_action", prepared)
                        if result.get("command"):
                            await self.call("general_command", {"run_id": run_id, **result}, 85)
                        if prepared["final"]:
                            break
                else:
                    result = await self.call("general_action", payload)
                if result.get("approval"):
                    state = await self.call("general_state", run_id)
                    approval_remaining = state["approval_wait_seconds"]
                    start = workflow.now()
                    try:
                        await workflow.wait_condition(
                            lambda: result["approval"] in self.decisions,
                            timeout=timedelta(seconds=approval_remaining),
                        )
                    except TimeoutError:
                        await self.call("general_stop", {"run_id": run_id, "code": "approval_timeout"})
                        return
                    elapsed = (workflow.now() - start).total_seconds()
                    approval_remaining -= elapsed
                    previous += timedelta(seconds=elapsed)
                    if approval_remaining <= 0:
                        await self.call("general_stop", {"run_id": run_id, "code": "approval_timeout"})
                        return
                    result = await self.call("general_action", payload)
                if result.get("command"):
                    await self.call("general_command", {"run_id": run_id, **result}, 85)
                if result.get("children"):
                    for cid in result["children"]:
                        children[cid] = await workflow.start_child_workflow(
                            "GeneralWorkflow", cid, id="run:" + cid, task_queue=workflow.info().task_queue
                        )
                        if result["sequential"]:
                            await children[cid]
                if result.get("join"):
                    await asyncio.gather(*(children[c] for c in result["join"] if c in children))
                state = await self.call("general_state", run_id)
                if state["status"] in {"completed", "failed", "cancelled"}:
                    return
        except asyncio.CancelledError:
            for child in children.values():
                child.cancel()
            raise
        except Exception as exc:
            code = getattr(getattr(exc, "cause", None), "message", "execution_stopped")
            if code not in {
                "budget_exhausted",
                "no_progress",
                "context_limit",
                "run_timeout",
                "sandbox_unavailable",
            }:
                code = "execution_stopped"
            await self.call("general_stop", {"run_id": run_id, "code": code})
