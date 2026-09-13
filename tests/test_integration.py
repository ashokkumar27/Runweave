"""Real services. Poll observable state with deadlines; no guessed startup sleeps."""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from sqlalchemy import func, select
from temporalio.client import Client
from temporalio.worker import Worker

from agent_runtime.activities import ACTIVITIES
from agent_runtime.db import NoteRow, OutboxRow
from agent_runtime.dispatch import Dispatcher
from agent_runtime.runtime import configure_store
from agent_runtime.schemas import AgentConfig, RunCreate
from agent_runtime.store import Problem
from agent_runtime.workflow import RunWorkflow

pytestmark = pytest.mark.integration


async def wait_status(store, run_id, statuses, seconds=45):
    async with asyncio.timeout(seconds):
        while True:
            run = await store.get(run_id)
            if run.status in statuses:
                return run
            if run.status in {"completed", "failed", "cancelled"}:
                raise AssertionError(f"Unexpected run result: {run.status}, {run.error}")
            await asyncio.sleep(0.05)


async def submit(store, prompt="add 2 3", tools=None, session_id=None, **kwargs):
    saved = await store.agent(
        AgentConfig(
            name="integration", provider="fake", model="deterministic", tools=tools or ["add"], **kwargs
        )
    )
    return await store.submit(RunCreate(agent_id=saved.id, input=prompt, session_id=session_id), uuid4().hex)


async def client():
    return await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"), plugins=[PydanticAIPlugin()]
    )


@asynccontextmanager
async def working(store):
    configure_store(store)
    temporal = await client()
    queue = f"test-{uuid4().hex}"
    dispatch = Dispatcher(store, temporal, queue)
    async with Worker(temporal, task_queue=queue, workflows=[RunWorkflow], activities=ACTIVITIES):
        task = asyncio.create_task(dispatch.run())
        try:
            yield temporal, dispatch
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_durable_flow_session_and_mcp(pg_store):
    async with working(pg_store):
        run = await submit(pg_store)
        result = await wait_status(pg_store, run.id, {"completed"})
        assert result.output.value == 5
        next_run = await submit(pg_store, "previous", session_id=run.session_id)
        continued = await wait_status(pg_store, next_run.id, {"completed"})
        assert continued.output.value == 5
        mcp = await submit(pg_store, "temperature:100", tools=["convert_temperature"])
        converted = await wait_status(pg_store, mcp.id, {"completed"})
        assert converted.output.value == 212
        events = await pg_store.events(mcp.id)
        assert any(e.type == "tool.completed" for e in events)


async def test_postgres_concurrent_submission_and_terminal_race(pg_store):
    agent = await pg_store.agent(AgentConfig(name="race", provider="fake", model="deterministic"))
    body = RunCreate(agent_id=agent.id, input="add 2 3")
    runs = await asyncio.gather(*(pg_store.submit(body, "same") for _ in range(12)))
    assert len({r.id for r in runs}) == 1
    run = runs[0]
    await asyncio.gather(
        pg_store.cancel(run.id), pg_store.finish(run.id, "completed", output={"answer": "5", "value": 5})
    )
    events = await pg_store.events(run.id)
    assert sum(e.type in {"run.completed", "run.cancelled"} for e in events) == 1
    session = await pg_store.session()
    body = RunCreate(agent_id=agent.id, session_id=session.id, input="add 1 2")
    attempts = await asyncio.gather(
        *(pg_store.submit(body, f"unique-{i}") for i in range(5)), return_exceptions=True
    )
    assert sum(not isinstance(r, Exception) for r in attempts) == 1
    assert all(isinstance(r, Problem) and r.status == 409 for r in attempts if isinstance(r, Exception))


async def test_dispatch_ack_loss_and_cancel_before_start(pg_store):
    temporal = await client()
    queue = f"test-{uuid4().hex}"
    dispatch = Dispatcher(pg_store, temporal, queue)
    run = await submit(pg_store)
    await dispatch.once()
    async with pg_store.database.sessions.begin() as db:
        item = await db.get(OutboxRow, f"start:{run.id}")
        item.delivered = False  # Start succeeded; process died before DB acknowledgement.
    await dispatch.once()
    await pg_store.cancel(run.id)
    await dispatch.once()
    async with Worker(temporal, task_queue=queue, workflows=[RunWorkflow], activities=ACTIVITIES):
        handle = temporal.get_workflow_handle(f"run:{run.id}")
        try:
            await asyncio.wait_for(handle.result(), 30)
        except Exception:
            pass
    assert (await pg_store.get(run.id)).status == "cancelled"
    assert not any(e.type == "tool.started" for e in await pg_store.events(run.id))


async def test_approval_survives_hard_worker_restart(pg_store, tmp_path):
    queue = f"restart-{uuid4().hex}"
    env = {
        **os.environ,
        "DATABASE_URL": pg_store.test_url,
        "DATABASE_SCHEMA": pg_store.test_schema,
        "TASK_QUEUE": queue,
    }
    # Remove provider credentials: this subprocess test must never make a paid call.
    env.pop("OPENAI_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)
    log = (tmp_path / "worker.log").open("w")

    async def start():
        return await asyncio.create_subprocess_exec(
            sys.executable, "-m", "agent_runtime.worker", env=env, stdout=log, stderr=log
        )

    process = await start()
    try:
        run = await submit(pg_store, "note:durable approval", tools=["record_note"])
        pending = await wait_status(pg_store, run.id, {"awaiting_approval"})
        process.kill()
        await process.wait()
        approval_id = pending.approvals[0].id
        await pg_store.decide(run.id, approval_id, True)
        process = await start()
        result = await wait_status(pg_store, run.id, {"completed"})
        assert result.output.answer == "Note recorded"
        async with pg_store.database.sessions() as db:
            assert (
                await db.scalar(select(func.count()).select_from(NoteRow).where(NoteRow.run_id == run.id))
                == 1
            )
        temporal = await client()
        history = await temporal.get_workflow_handle(f"run:{run.id}").fetch_history()
        from temporalio.worker import Replayer

        await Replayer(workflows=[RunWorkflow], plugins=[PydanticAIPlugin()]).replay_workflow(history)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        log.close()


async def test_approval_rejection_and_timeout(pg_store):
    async with working(pg_store):
        run = await submit(pg_store, "note:reject me", tools=["record_note"])
        pending = await wait_status(pg_store, run.id, {"awaiting_approval"})
        await pg_store.decide(run.id, pending.approvals[0].id, False)
        await wait_status(pg_store, run.id, {"completed"})
        timed = await submit(pg_store, "note:expire", tools=["record_note"], timeout_seconds=5)
        result = await wait_status(pg_store, timed.id, {"failed"})
        assert result.error == "run_timeout"
        async with pg_store.database.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(NoteRow)) == 0


async def test_effect_commit_then_activity_failure_retries_once(pg_store, monkeypatch):
    original = pg_store.record_note
    attempts = []

    async def interrupted(run_id, call_id, text):
        result = await original(run_id, call_id, text)
        attempts.append(call_id)
        if len(attempts) == 1:
            raise RuntimeError("Injected failure after effect commit before activity acknowledgement")
        return result

    monkeypatch.setattr(pg_store, "record_note", interrupted)
    async with working(pg_store):
        run = await submit(pg_store, "note:exactly once", tools=["record_note"])
        pending = await wait_status(pg_store, run.id, {"awaiting_approval"})
        await pg_store.decide(run.id, pending.approvals[0].id, True)
        await wait_status(pg_store, run.id, {"completed"})
        assert len(attempts) == 2 and len(set(attempts)) == 1
        async with pg_store.database.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(NoteRow)) == 1


async def test_cancellation_approval_race_and_budget(pg_store):
    async with working(pg_store) as (temporal, _):
        run = await submit(pg_store, "note:cancel me", tools=["record_note"])
        pending = await wait_status(pg_store, run.id, {"awaiting_approval"})
        await asyncio.gather(
            pg_store.cancel(run.id),
            pg_store.decide(run.id, pending.approvals[0].id, True),
            return_exceptions=True,
        )
        assert (await pg_store.get(run.id)).status == "cancelled"
        from temporalio.client import WorkflowExecutionStatus

        async with asyncio.timeout(20):
            while (
                await temporal.get_workflow_handle(f"run:{run.id}").describe()
            ).status == WorkflowExecutionStatus.RUNNING:
                await asyncio.sleep(0.05)
        async with pg_store.database.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(NoteRow)) == 0
        limited = await submit(pg_store, max_requests=1)
        result = await wait_status(pg_store, limited.id, {"failed"})
        assert result.error == "usage_limit"


async def test_dispatch_outage_and_closed_workflow_reconciliation(pg_store, monkeypatch):
    temporal = await client()
    dispatch = Dispatcher(pg_store, temporal, f"unstaffed-{uuid4().hex}")
    run = await submit(pg_store)
    original = temporal.start_workflow

    async def unavailable(*args, **kwargs):
        raise ConnectionError("Injected Temporal outage")

    monkeypatch.setattr(temporal, "start_workflow", unavailable)
    with pytest.raises(ConnectionError):
        await dispatch.once()
    async with pg_store.database.sessions() as db:
        assert not (await db.get(OutboxRow, f"start:{run.id}")).delivered
    monkeypatch.setattr(temporal, "start_workflow", original)
    await dispatch.once()
    await temporal.get_workflow_handle(f"run:{run.id}").terminate()
    await dispatch.reconcile()
    result = await pg_store.get(run.id)
    assert result.status == "failed"
    assert result.error == "workflow_closed_without_result"
