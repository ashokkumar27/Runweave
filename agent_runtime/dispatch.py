"""Post-commit delivery and reconciliation; safe across process death at every await."""

import asyncio
from datetime import timedelta

from sqlalchemy import select
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from .db import OutboxRow, RunRow
from .store import TERMINAL


class Dispatcher:
    def __init__(self, store, client, task_queue):
        self.store, self.client, self.task_queue = store, client, task_queue

    async def once(self):
        async with self.store.database.sessions() as db:
            ids = list(
                await db.scalars(select(OutboxRow.id).where(OutboxRow.delivered.is_(False)).limit(100))
            )
        for item_id in ids:
            async with self.store.database.sessions.begin() as db:
                item = await db.scalar(
                    select(OutboxRow).where(OutboxRow.id == item_id).with_for_update(skip_locked=True)
                )
                if item is None or item.delivered:
                    continue
                handle = self.client.get_workflow_handle(f"run:{item.run_id}")
                if item.kind == "start":
                    run = await db.get(RunRow, item.run_id)
                    try:
                        await self.client.start_workflow(
                            "RunWorkflow",
                            item.run_id,
                            id=f"run:{item.run_id}",
                            task_queue=self.task_queue,
                            execution_timeout=timedelta(
                                seconds=run.config["timeout_seconds"] + run.approval_wait_seconds + 180
                            ),
                            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                        )
                    except WorkflowAlreadyStartedError:
                        pass
                else:
                    try:
                        if item.kind == "cancel":
                            await handle.cancel()
                        else:
                            await handle.signal("decision", item.payload)
                    except RPCError as exc:
                        if exc.status != RPCStatusCode.NOT_FOUND:
                            raise
                        # Start may not yet have been delivered. Do not lose a command.
                        start = await db.get(OutboxRow, f"start:{item.run_id}")
                        if start is None or not start.delivered:
                            continue
                        status = await db.scalar(select(RunRow.status).where(RunRow.id == item.run_id))
                        if status not in TERMINAL:
                            continue
                item.delivered = True
        await self.reconcile()

    async def reconcile(self):
        # Covers workflow execution timeouts/failed workflow tasks and crashes during finalization.
        async with self.store.database.sessions() as db:
            ids = list(await db.scalars(select(RunRow.id).where(RunRow.status.not_in(TERMINAL))))
        for run_id in ids:
            try:
                desc = await self.client.get_workflow_handle(f"run:{run_id}").describe()
            except RPCError as exc:
                if exc.status == RPCStatusCode.NOT_FOUND:
                    continue
                raise
            if desc.status in {
                WorkflowExecutionStatus.FAILED,
                WorkflowExecutionStatus.TIMED_OUT,
                WorkflowExecutionStatus.TERMINATED,
                WorkflowExecutionStatus.CANCELED,
                WorkflowExecutionStatus.COMPLETED,
            }:
                status = "cancelled" if desc.status == WorkflowExecutionStatus.CANCELED else "failed"
                await self.store.finish(run_id, status, error="workflow_closed_without_result")

    async def run(self):
        while True:
            try:
                await self.once()
            except Exception:
                # Leave delivery pending. No exception bodies (which can contain input) in logs.
                import logging

                logging.getLogger(__name__).warning("Dispatch unavailable; will retry")
            await asyncio.sleep(0.5)
