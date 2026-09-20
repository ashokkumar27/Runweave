"""Run one fixed lightweight-confidence-v1 campaign, or an isolated offline SDK preflight."""

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import socket
import sqlite3
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from agent_runtime.client import Client
from scripts import lightweight_budget as guard
from scripts.lightweight_fixtures import config, fixture

DIRECTORY = Path("var/acceptance/lightweight-confidence-v1")
LEDGER = Path("var/acceptance/lightweight-confidence-v1.sqlite")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


async def all_records(method, run_id):
    items, cursor = [], 0
    while True:
        page = await method(run_id, cursor=cursor)
        items.extend(page["items"])
        if page["next_cursor"] is None:
            return {"items": items, "next_cursor": None}
        cursor = page["next_cursor"]


async def collect(client, run_id, entry, directory):
    result = await client.get(run_id)
    entry.update(
        run=result.model_dump(mode="json"),
        task=await client.task(run_id),
        budget=await client.budget(run_id),
        operations=await all_records(client.operations, run_id),
        verifications=await all_records(client.verifications, run_id),
    )
    entry["events"] = [e.model_dump(mode="json") async for e in client.watch(run_id)]
    children = await client.children(run_id)
    entry["children"] = [c.model_dump(mode="json") for c in children]
    entry["child_evidence"] = {}
    for child in children:
        entry["child_evidence"][child.id] = {
            "operations": await all_records(client.operations, child.id),
            "verifications": await all_records(client.verifications, child.id),
            "task": await client.task(child.id),
            "budget": await client.budget(child.id),
            "events": [e.model_dump(mode="json") async for e in client.watch(child.id)],
        }
    f = fixture(entry["name"])
    expected = {**f["expected"], **{p: f["files"][p] for p in f["preserve"]}}
    if entry["name"] == "bug":
        expected["main.py"] = None
    entry["downloads"] = {}
    for path, wanted in expected.items():
        try:
            actual = await client.workspace_read(
                result.workspace["workspace_id"], result.workspace["revision_id"], path
            )
            target = directory / run_id / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(actual)
            entry["downloads"][path] = {
                "evidence": str(target),
                "sha256": hashlib.sha256(actual).hexdigest(),
                "matches": actual == wanted if wanted is not None else None,
            }
        except Exception as exc:
            entry["downloads"][path] = {"error": type(exc).__name__}
    entry["command_outputs"] = []
    for op in entry["operations"]["items"]:
        if (op.get("result") or {}).get("exit_code") is not None:
            record = {"operation_id": op["id"], "result": op["result"]}
            for channel in ["stdout", "stderr"]:
                try:
                    data = await client.operation_output(run_id, op["id"], channel)
                    target = directory / run_id / (op["id"].replace(":", "_") + "." + channel)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    record[channel] = str(target)
                except Exception as exc:
                    record[channel + "_error"] = type(exc).__name__
            entry["command_outputs"].append(record)


def oracle(entry):
    errors = []

    def check(ok, message):
        if not ok:
            errors.append(message)

    name = entry["name"]
    f = fixture(name)
    check(entry["run"]["status"] == "completed", "Run did not complete")
    check((entry["task"].get("assessment") or {}).get("accepted") is True, "Completion not accepted")
    for p in [*f["expected"], *f["preserve"]]:
        check(entry["downloads"].get(p, {}).get("matches") is True, "Downloaded bytes differ or absent: " + p)
    fresh = {
        v["check_id"]
        for v in entry["verifications"]["items"]
        if v["outcome"] == "pass"
        and v["fresh"]
        and v["revision_id"] == entry["run"].get("workspace", {}).get("revision_id")
    }
    check("runtime.syntax" in fresh, "No fresh final-head syntax receipt")
    for spec in f["task"]["criteria"][0]["checks"]:
        check(spec["id"] in fresh, "Missing fresh caller check: " + spec["id"])
    ops = entry["operations"]["items"]
    if name == "bug":
        # Independent download validation uses isolated AST inspection; downloaded code is never executed on host.
        import ast

        try:
            source = Path(entry["downloads"]["main.py"]["evidence"]).read_text()
            tree = ast.parse(source)
            fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "double")
            expression = fn.body[0].value
            check(
                len(fn.body) == 1 and isinstance(fn.body[0], ast.Return),
                "Independent double oracle cannot establish function body",
            )

            def evaluate(node, x):
                if isinstance(node, ast.Name) and node.id == "x":
                    return x
                if isinstance(node, ast.Constant) and type(node.value) is int:
                    return node.value
                if isinstance(node, ast.BinOp):
                    left, right = evaluate(node.left, x), evaluate(node.right, x)
                    if isinstance(node.op, ast.Mult):
                        return left * right
                    if isinstance(node.op, ast.Add):
                        return left + right
                raise ValueError("Unsupported expression")

            check(
                [evaluate(expression, x) for x in [4, -3, 0]] == [8, -6, 0],
                "Independent downloaded function behavior differs",
            )
        except Exception as exc:
            errors.append("Independent bug oracle: " + type(exc).__name__)
    if name == "recovery":
        commands = []
        by_id = {o["id"]: o for o in ops}
        for op in ops:
            action = (op.get("result") or {}).get("action", {})
            if action.get("capability") == "workspace_command":
                result = by_id.get(op["id"].replace(":model:", ":action:"), {}).get("result") or {}
                commands.append((action["arguments"]["argv"], result))
        check(
            bool(commands)
            and commands[0][0] == ["python", "report.py", "input.csv"]
            and commands[0][1].get("exit_code") != 0,
            "Wrong initial command",
        )
        outputs = entry["command_outputs"]
        check(len(outputs) >= 2 and outputs[0]["result"]["exit_code"] != 0, "First command did not fail")
        if outputs:
            diagnostic = b"".join(
                Path(outputs[0][k]).read_bytes() for k in ["stdout", "stderr"] if k in outputs[0]
            )
            check(
                b"input.csv" in diagnostic and b"No such file" in diagnostic,
                "Missing downloaded missing-file diagnostic",
            )
        corrected = [result for argv, result in commands if argv == ["python", "report.py", "inputs.csv"]]
        check(
            len(corrected) == 1 and corrected[0].get("exit_code") == 0,
            "Corrected command not observed exactly once",
        )
    if name == "direct":
        check(not entry["children"], "Unexpected children")
        check(
            not any(
                (o.get("result") or {}).get("action", {}).get("kind") in {"assign", "merge"} for o in ops
            ),
            "Unexpected assignment/merge",
        )
    if name == "parallel":
        children = entry["children"]
        check(len(children) == 2, "Exactly two actual children required")
        merges = [
            o
            for o in ops
            if (o.get("result") or {}).get("conflicts") == [] and (o.get("result") or {}).get("changed")
        ]
        check(len(merges) == 2, "Two successful merges required")
        for c in children:
            ev = entry["child_evidence"][c["id"]]
            check(c["status"] == "completed", "Child not completed")
            check(
                any((o.get("result") or {}).get("changed") for o in ev["operations"]["items"]),
                "Child did not author output",
            )
            check(
                any(v["fresh"] and v["outcome"] == "pass" for v in ev["verifications"]["items"]),
                "Child lacks fresh checks",
            )
        # A pass additionally requires exact scopes and overlapping lifecycle timestamps.
        assignments = [
            (o.get("result") or {}).get("action")
            for o in ops
            if (o.get("result") or {}).get("action", {}).get("kind") == "assign"
        ]
        check(
            len(assignments) == 1 and len(assignments[0]["assignments"]) == 2,
            "One combined assignment required",
        )
        check(
            sorted(c["effective_grants"]["write_prefixes"] for c in children)
            == [["left.txt"], ["right.txt"]],
            "Disjoint exact child output scopes required",
        )
        intervals = []
        for c in children:
            events = entry["child_evidence"][c["id"]]["events"]
            starts = [e["created_at"] for e in events if e["type"] == "run.running"]
            ends = [
                e["created_at"]
                for e in events
                if e["type"] in {"run.completed", "run.failed", "run.cancelled"}
            ]
            if starts and ends:
                intervals.append((min(starts), max(ends)))
        check(
            len(intervals) == 2 and max(a for a, b in intervals) < min(b for a, b in intervals),
            "Child lifetimes did not overlap",
        )
        check(
            not any((o.get("result") or {}).get("changed") and o not in merges for o in ops),
            "Parent-authored substitute files",
        )
    return errors


async def execute(
    live=False, *, directory=DIRECTORY, ledger_path=LEDGER, campaign_guard=guard, registry=None
):
    DIRECTORY, LEDGER, guard = directory, ledger_path, campaign_guard
    comparison = bool(guard.MANIFEST.get("models"))
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    if live:
        preflight = json.loads((DIRECTORY / "preflight-gate.json").read_text())
        if any(s["status"] != "passed" for s in preflight["scenarios"] if s["name"] != "parallel"):
            raise RuntimeError("Nonparallel SDK preflight did not pass")
        ledger = LEDGER
        output = DIRECTORY / "live.json"
        if output.exists():
            raise RuntimeError("Live campaign already invoked; reconcile retained evidence, never resubmit")
    else:
        ledger = Path(tempfile.mkdtemp(prefix="light-preflight-")) / "stub.sqlite"
        output = DIRECTORY / "preflight.json"
        if output.exists():
            output = DIRECTORY / ("preflight-" + uuid4().hex + ".json")
    guard.initialize(ledger)
    report = {
        "campaign": guard.MANIFEST,
        "mode": "live" if live else "sdk-stub",
        "ledger": str(ledger),
        "scenarios": [],
    }
    save(output, report)
    env = {**os.environ, "PYDANTIC_AI_NO_BANNER": "1"}
    for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
        env.pop(key, None)
    schema = "light_" + uuid4().hex
    env.update(
        DATABASE_SCHEMA=schema,
        TASK_QUEUE=schema,
        API_KEY=secrets.token_urlsafe(32),
        ACCEPTANCE_CAMPAIGN=guard.MANIFEST["campaign"],
        ACCEPTANCE_BUDGET_FILE=str(ledger.absolute()),
        SANDBOX_BROKER_URL="http://localhost:18091",
        SANDBOX_BROKER_KEY="v3-isolated-test-only",
    )
    if registry:
        env["MODEL_REGISTRY_FILE"] = str(registry.absolute())
    worker_env = dict(env)
    worker_env["OPENAI_API_KEY"] = (
        (
            os.environ.get("OPENAI_API_KEY")
            or dotenv_values(".env.local", interpolate=False).get("OPENAI_API_KEY")
        )
        if live
        else "offline-sdk-stub"
    )
    if not worker_env["OPENAI_API_KEY"]:
        raise RuntimeError("Authorized existing credential unavailable")
    worker_env["LIGHT_STUB_LOG"] = str(output.with_suffix(".sdk.jsonl").absolute())
    if comparison:
        worker_env["COMPARISON_WIRE_LOG"] = str(output.with_suffix(".wire.jsonl").absolute())
    processes = []
    logs = []

    async def process(*cmd, environment=env):
        log = (DIRECTORY / (schema + "-" + str(len(processes)) + ".log")).open("w")
        logs.append(log)
        p = await asyncio.create_subprocess_exec(
            sys.executable, *cmd, env=environment, stdout=log, stderr=log
        )
        processes.append(p)
        return p

    admin = create_async_engine(
        env.get("DATABASE_URL", "postgresql+asyncpg://agents:local-development-only@localhost:5432/agents")
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f"CREATE SCHEMA {schema}"))
        migration = await process("-m", "alembic", "upgrade", "head")
        if await migration.wait():
            raise RuntimeError("Isolated migration failed")
        await process("-m", "uvicorn", "agent_runtime.api:app", "--host", "127.0.0.1", "--port", str(port))
        async with Client(f"http://127.0.0.1:{port}", env["API_KEY"]) as client:
            for _ in range(100):
                try:
                    await client.models()
                    break
                except Exception:
                    await asyncio.sleep(0.1)
            unavailable = set()
            for cell in guard.MANIFEST["scenario_limits"]:
                model, name = cell.split("/") if comparison else ("gpt-5.6-luna", cell)
                entry = {
                    "name": name,
                    "model": model,
                    "cell": cell,
                    "status": "failed",
                    "calls_before": guard.validate(ledger),
                }
                report["scenarios"].append(entry)
                if model in unavailable:
                    entry.update(
                        status="blocked",
                        reason="Model incompatible on first budgeted fixture request",
                        calls_after=guard.validate(ledger),
                    )
                    guard.finish(ledger, cell, "model_incompatible")
                    save(output, report)
                    continue
                if (
                    live
                    and name == "parallel"
                    and next(s for s in preflight["scenarios"] if s["name"] == name)["status"] != "passed"
                ):
                    entry.update(
                        status="blocked",
                        reason="Real SDK reservation preflight failed; zero paid calls",
                        calls_after=guard.validate(ledger),
                    )
                    guard.finish(ledger, cell, "blocked_preflight")
                    save(output, report)
                    continue
                worker = None
                try:
                    f = fixture(name)
                    workspace = await client.workspace_create(f["files"])
                    cfg = config(name).model_copy(update={"model": model})
                    entry["agent_config"] = cfg.model_dump(mode="json")
                    agent = await client.create_agent(cfg)
                    # Worker starts only after durable admission, avoiding a first-send race.
                    run = await client.submit(
                        agent.id,
                        f["prompt"],
                        workspace=workspace,
                        task=f["task"],
                        idempotency_key="light-" + cell,
                    )
                    entry["run_id"] = run.id
                    guard.admit(ledger, cell, run.id)
                    save(output, report)
                    worker = await process(
                        "-m",
                        "scripts.acceptance_worker" if live else "scripts.lightweight_stub_worker",
                        environment=worker_env,
                    )
                    result = await client.wait(run.id, timeout=240, stop_at_approval=False)
                    await collect(
                        client,
                        run.id,
                        entry,
                        DIRECTORY / ("live-downloads" if live else "preflight-downloads"),
                    )
                    entry["oracle_errors"] = oracle(entry)
                    entry["status"] = "passed" if not entry["oracle_errors"] else "failed"
                    entry["reason"] = result.error
                except Exception as exc:
                    entry["error"] = type(exc).__name__ + ": " + str(exc)[:400]
                    if entry.get("run_id") and worker and worker.returncode is None:
                        guard.finish(ledger, cell, "failed")
                        await client.cancel(entry["run_id"])
                        try:
                            await client.wait(entry["run_id"], timeout=60, stop_at_approval=False)
                            await collect(
                                client,
                                entry["run_id"],
                                entry,
                                DIRECTORY / ("live-downloads" if live else "preflight-downloads"),
                            )
                        except Exception as cleanup_error:
                            entry["cleanup_error"] = type(cleanup_error).__name__
                finally:
                    guard.finish(ledger, cell, entry["status"])
                    if worker and worker.returncode is None:
                        worker.terminate()
                        await worker.wait()
                    if live and comparison:
                        wire = Path(worker_env["COMPARISON_WIRE_LOG"])
                        records = (
                            [json.loads(line) for line in wire.read_text().splitlines()]
                            if wire.exists()
                            else []
                        )
                        own = [r for r in records if r["context"]["root_id"] == entry.get("run_id")]
                        if own and own[0].get("status_code") in {400, 401, 403, 404, 422}:
                            unavailable.add(model)
                            entry["model_availability"] = "incompatible"
                        else:
                            entry["model_availability"] = (
                                "accepted" if any(r.get("status_code") == 200 for r in own) else "unverified"
                            )
                    entry["calls_after"] = guard.validate(ledger)
                    save(output, report)
                    print(
                        json.dumps({k: entry[k] for k in ["name", "status", "calls_before", "calls_after"]}),
                        flush=True,
                    )
    finally:
        for p in processes:
            if p.returncode is None:
                p.terminate()
                await p.wait()
        for log in logs:
            log.close()
        # Read accounting before removing only this campaign invocation's schema.
        async with admin.begin() as conn:
            rows = await conn.execute(
                text(f"SELECT id, data FROM \"{schema}\".general_operations WHERE id LIKE '%:model:%'")
            )
            report["reservation_evidence"] = [{"id": r[0], "data": r[1]} for r in rows]
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()
        with sqlite3.connect(ledger) as db:
            report["physical_calls"] = db.execute("SELECT count(*) FROM attempts").fetchone()[0]
        report["isolated_schema_removed"] = True
        trace = Path(worker_env["LIGHT_STUB_LOG"] + ".reservations")
        if not live and trace.exists():
            report["reservation_measurements"] = [json.loads(line) for line in trace.read_text().splitlines()]
        save(output, report)
    if not live and all(s["status"] == "passed" for s in report["scenarios"] if s["name"] != "parallel"):
        save(DIRECTORY / "preflight-gate.json", {**report, "source_evidence": str(output)})
    print(str(output), flush=True)
    return 0 if all(s["status"] == "passed" for s in report["scenarios"]) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    return asyncio.run(execute(args.live))


if __name__ == "__main__":
    raise SystemExit(main())
