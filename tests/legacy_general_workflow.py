"""Representative pre-correction v3 coordination, for retained-history replay testing."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="GeneralWorkflow")
class LegacyGeneralWorkflow:
    async def call(self, name, value, seconds=90):
        return await workflow.execute_activity(
            name,
            value,
            start_to_close_timeout=timedelta(seconds=seconds),
            retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=2)),
        )

    @workflow.run
    async def run(self, run_id: str):
        state = await self.call("general_state", run_id)
        while True:
            state = await self.call("general_state", run_id)
            decision = await self.call("general_step", run_id, min(90, max(1, state["active_remaining"])))
            await self.call("general_action", {"run_id": run_id, **decision})
            state = await self.call("general_state", run_id)
            if state["status"] in {"completed", "failed", "cancelled"}:
                return
