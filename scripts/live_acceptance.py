"""Opt-in isolated full HTTP acceptance. Paid requests require --live.

Reuse --budget-file across targeted reruns; never reset it to extend a campaign.
Only synthetic prompts/results are written to the evidence artifact.
"""

import argparse
import asyncio
import json
import os
import secrets
import socket
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine
from temporalio.client import Client as TemporalClient

from agent_runtime.client import Client, ClientError
from agent_runtime.db import Database, NoteRow
from agent_runtime.schemas import AgentConfig
from agent_runtime.store import Store

NOTE = "SYNTHETIC incident INC-042: cooling sensor exceeded threshold at 14:05 UTC; inspection scheduled. No real incident."


def attempts(path):
    if not path.exists():
        return 0
    with sqlite3.connect(path) as db:
        if not db.execute("SELECT name FROM sqlite_master WHERE name='attempts'").fetchone():
            return 0
        return db.execute("SELECT count(*) FROM attempts").fetchone()[0]


async def execute(args):
    budget = Path(args.budget_file).resolve()
    budget.parent.mkdir(parents=True, exist_ok=True)
    if budget.is_symlink():
        raise RuntimeError("Budget file cannot be a symlink")
    env = {**os.environ, "PYDANTIC_AI_NO_BANNER": "1"}
    env.pop("ANTHROPIC_API_KEY", None)
    if args.live:
        local = dotenv_values(".env.local", interpolate=False)
        env["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY") or local.get("OPENAI_API_KEY") or ""
        if not env["OPENAI_API_KEY"]:
            raise RuntimeError("Existing OpenAI credential required")
    else:
        env.pop("OPENAI_API_KEY", None)
    schema = "acceptance_" + uuid4().hex
    key = secrets.token_urlsafe(32)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env.update(
        DATABASE_SCHEMA=schema,
        TASK_QUEUE=schema,
        API_KEY=key,
        ACCEPTANCE_BUDGET_FILE=str(budget),
        APPROVAL_WAIT_SECONDS="180",
    )
    url = env.get("DATABASE_URL", "postgresql+asyncpg://agents:local-development-only@localhost:5432/agents")
    admin = create_async_engine(url)
    database = Database(url, schema)
    store = Store(database)
    api = worker = None
    report = {"mode": "live" if args.live else "fake", "attempts_before": attempts(budget), "scenarios": {}}
    temporal = await TemporalClient.connect(env.get("TEMPORAL_ADDRESS", "localhost:7233"))
    run_ids = []

    async def start_worker():
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "scripts.acceptance_worker",
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def notes(run_id):
        async with database.sessions() as db:
            return list((await db.scalars(select(NoteRow.text).where(NoteRow.run_id == run_id))).all())

    async def save_run(client, agent_id, prompt, **kwargs):
        run = await client.submit(agent_id, prompt, **kwargs)
        run_ids.append(run.id)
        return run

    async def completed(client, run):
        result = await client.wait(run.id, timeout=150, stop_at_approval=False)
        assert result.status == "completed", f"Run ended {result.status}: {result.error}"
        return result

    async def evidence(name, action):
        try:
            report["scenarios"][name] = {"status": "passed", **await action()}
        except Exception as exc:
            # Keep only safe classes; model/provider exceptions may contain secrets.
            report["scenarios"][name] = {
                "status": "failed",
                "error_type": type(exc).__name__,
                "location": f"{Path(exc.__traceback__.tb_next.tb_frame.f_code.co_filename).name}:{exc.__traceback__.tb_next.tb_lineno}"
                if exc.__traceback__.tb_next
                else "scenario",
            }
        print(json.dumps({name: report["scenarios"][name]}), flush=True)
        Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
        Path(args.evidence).write_text(json.dumps(report, indent=2) + "\n")

    try:
        async with admin.begin() as conn:
            await conn.execute(text(f"CREATE SCHEMA {schema}"))
        await database.create_test_schema()
        api_env = {k: v for k, v in env.items() if k not in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}}
        api = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "uvicorn",
            "agent_runtime.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            env=api_env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        worker = await start_worker()
        async with Client(f"http://127.0.0.1:{port}", key) as client:
            async with asyncio.timeout(40):
                while True:
                    try:
                        if (await client.readiness())["ready"]:
                            break
                    except ClientError:
                        pass
                    await asyncio.sleep(0.2)
            config = AgentConfig(
                name="synthetic acceptance",
                provider="openai" if args.live else "fake",
                model="gpt-5.6-luna" if args.live else "deterministic",
                max_tokens=512,
                max_requests=6,
                max_tool_calls=6,
                timeout_seconds=120,
                tools=["add", "record_note", "convert_temperature"],
                instructions="Follow the supplied task exactly. Use the requested tools. Return concise structured answers. Preserve exact note text. Use session history for follow-ups.",
            )
            agent = await client.create_agent(config)

            async def conversion():
                if not args.live:
                    mcp = await save_run(client, agent.id, "temperature:100")
                    assert (await completed(client, mcp)).output.value == 212
                prompt = (
                    "Use convert_temperature via MCP for 20 Celsius and 30 Celsius to Fahrenheit. "
                    "Then use add on the two Fahrenheit results. Return the sum in value."
                    if args.live
                    else "add 68 86"
                )
                run = await save_run(client, agent.id, prompt)
                first = client.watch(run.id)
                event = await anext(first)
                await first.aclose()  # Real socket disconnect, before waiting for completion.
                result = await completed(client, run)
                replay = [e async for e in client.watch(run.id, cursor=event.id)]
                ids = [event.id] + [e.id for e in replay]
                persisted = await store.events(run.id)
                assert ids == [e.id for e in persisted] and ids == sorted(set(ids))
                assert persisted[-1].type == "run.completed"
                assert result.output.value == 154
                if args.live:
                    tools = [e.data.get("tool") for e in persisted if e.type == "tool.completed"]
                    assert tools.count("convert_temperature") == 2 and tools.count("add") == 1
                follow = await save_run(
                    client,
                    agent.id,
                    "What was the final sum from the previous task? Return it in value without calling tools."
                    if args.live
                    else "previous",
                    session_id=run.session_id,
                )
                remembered = await completed(client, follow)
                assert remembered.output.value == result.output.value
                return {
                    "run_id": run.id,
                    "sum": result.output.value,
                    "followup": remembered.output.model_dump(),
                    "sse_ids": ids,
                    "events": [e.model_dump(mode="json") for e in persisted],
                }

            async def approval():
                nonlocal worker
                prompt = (
                    f"Call record_note exactly once with text exactly: {NOTE}"
                    if args.live
                    else f"note:{NOTE}"
                )
                submission_key = uuid4().hex
                run = await save_run(client, agent.id, prompt, idempotency_key=submission_key)
                assert (await client.submit(agent.id, prompt, idempotency_key=submission_key)).id == run.id
                try:
                    await client.submit(agent.id, "conflicting input", idempotency_key=submission_key)
                    raise AssertionError("Conflicting reuse accepted")
                except ClientError:
                    pass
                pending = await client.wait(run.id)
                assert pending.status == "awaiting_approval" and len(pending.approvals) == 1
                call = pending.approvals[0]
                assert call.arguments == {"text": NOTE}
                assert await notes(run.id) == []
                async with asyncio.timeout(20):
                    while True:
                        history = await temporal.get_workflow_handle(f"run:{run.id}").fetch_history()
                        if any(
                            e.HasField("timer_started_event_attributes")
                            and e.timer_started_event_attributes.start_to_fire_timeout.seconds >= 170
                            for e in history.events
                        ):
                            break
                        await asyncio.sleep(0.1)
                worker.kill()
                await worker.wait()
                await client.decide(run.id, call.id, True)
                await client.decide(run.id, call.id, True)
                try:
                    await client.decide(run.id, call.id, False)
                    raise AssertionError("Conflicting decision accepted")
                except ClientError:
                    pass
                assert await notes(run.id) == []
                worker = await start_worker()
                result = await completed(client, run)
                assert await notes(run.id) == [NOTE]
                events = await store.events(run.id)
                assert sum(e.type == "tool.effect_committed" for e in events) == 1
                return {
                    "run_id": run.id,
                    "exact_note": NOTE,
                    "effects_before_approval": 0,
                    "effects_while_worker_down": 0,
                    "effects_after_restart": 1,
                    "durable_timer_observed": True,
                    "worker_exit": "SIGKILL",
                    "output": result.output.model_dump(),
                }

            async def denial():
                prompt = (
                    "Call record_note with text exactly: SYNTHETIC denied incident."
                    if args.live
                    else "note:SYNTHETIC denied incident."
                )
                run = await save_run(client, agent.id, prompt)
                pending = await client.wait(run.id)
                assert pending.status == "awaiting_approval"
                await client.decide(run.id, pending.approvals[0].id, False)
                result = await completed(client, run)
                assert await notes(run.id) == []
                assert not any(e.type == "tool.effect_committed" for e in await store.events(run.id))
                events = await store.events(run.id)
                rounds = sum(e.type == "approval.required" for e in events)
                assert rounds == 1
                return {
                    "run_id": run.id,
                    "prompt": prompt,
                    "terminal_status": result.status,
                    "approval_rounds": rounds,
                    "notes": 0,
                    "effects": 0,
                    "output": result.output.model_dump(),
                }

            async def clauses():
                run = await save_run(
                    client,
                    agent.id,
                    "Synthetic contract: Clause A requires notice 30 days before termination. Clause B requires notice 60 days before termination for the same agreement and circumstances. Identify the conflict, referencing both clauses and numbers. Do not use tools.",
                )
                result = await completed(client, run)
                answer = result.output.answer.lower()
                assert all(term in answer for term in ["30", "60", "clause a", "clause b"])
                assert any(term in answer for term in ["conflict", "inconsistent", "contradict"])
                follow = await save_run(
                    client,
                    agent.id,
                    "Amend Clause B to require 30 days notice instead. Does the conflict remain? Explain briefly using both clauses. Do not use tools.",
                    session_id=run.session_id,
                )
                resolved = await completed(client, follow)
                answer = resolved.output.answer.lower()
                assert "30" in answer and any(
                    term in answer
                    for term in ["no conflict", "resolved", "no longer", "consistent", "not remain"]
                )
                return {
                    "run_id": run.id,
                    "conflict": result.output.model_dump(),
                    "amendment": resolved.output.model_dump(),
                }

            async def cancellation():
                fake = await client.create_agent(
                    config.model_copy(update={"provider": "fake", "model": "deterministic"})
                )
                run = await save_run(client, fake.id, "note:SYNTHETIC cancel")
                assert (await client.wait(run.id)).status == "awaiting_approval"
                await client.cancel(run.id)
                assert (await client.wait(run.id)).status == "cancelled"
                assert await notes(run.id) == []
                return {"run_id": run.id, "status_after_cancel": "cancelled", "effects": 0}

            for name, action in [
                ("conversion", conversion),
                ("approval", approval),
                ("denial", denial),
                ("clauses", clauses),
                ("cancellation", cancellation),
            ]:
                if name == "clauses" and not args.live:
                    continue
                if args.scenario != "all" and args.scenario != name:
                    continue
                await evidence(name, action)
    finally:
        # Cancel only this harness's workflows; application operations stay on HTTP above.
        for run_id in run_ids:
            try:
                await temporal.get_workflow_handle(f"run:{run_id}").cancel()
            except Exception:
                pass
        for process in [worker, api]:
            if process and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 10)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        await database.close()
        async with admin.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await admin.dispose()
        report["attempts_after"] = attempts(budget)
        report["attempt_limit"] = 20
        report["isolated_schema_removed"] = True
        Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
        Path(args.evidence).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"attempts_used": report["attempts_after"], "limit": 20}), flush=True)
    return (
        0 if report["scenarios"] and all(s["status"] == "passed" for s in report["scenarios"].values()) else 1
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--campaign", choices=["historic", "toolkits-subagents-v1", "general-runtime-v3"], default="historic"
    )
    parser.add_argument("--budget-file", default="/tmp/agent-runtime-acceptance-budget.sqlite")
    parser.add_argument("--evidence", default="docs/acceptance.json")
    parser.add_argument(
        "--scenario",
        choices=[
            "all",
            "conversion",
            "approval",
            "denial",
            "clauses",
            "cancellation",
            "documents",
            "csv",
            "repository",
            "controls",
            "simple",
            "project-revise",
            "dynamic-specialists",
            "data-task",
            "recovery-or-retry",
        ],
        default="all",
    )
    parser.add_argument(
        "--retry-scenario", choices=["simple", "project-revise", "dynamic-specialists", "data-task"]
    )
    parser.add_argument(
        "--resume-data-run",
        help="Import retained data artifact into a NEW verification task (not workflow resumption or fresh generation)",
    )
    args = parser.parse_args()
    try:
        if args.campaign == "general-runtime-v3":
            from scripts.general_acceptance import execute as general_execute

            if args.budget_file == "/tmp/agent-runtime-acceptance-budget.sqlite":
                args.budget_file = "var/acceptance/general-runtime-v3.sqlite"
            return asyncio.run(general_execute(args))
        if args.campaign == "toolkits-subagents-v1":
            from scripts.toolkit_acceptance import execute as toolkit_execute

            if args.budget_file == "/tmp/agent-runtime-acceptance-budget.sqlite":
                args.budget_file = "var/acceptance/toolkits-subagents-v1.sqlite"
            return asyncio.run(toolkit_execute(args))
        return asyncio.run(execute(args))
    except Exception as exc:
        print(f"Acceptance setup failed ({type(exc).__name__}; details suppressed)")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
