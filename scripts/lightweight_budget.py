"""One immutable confidence campaign, with root admission and terminal latches."""

import json
import os
import sqlite3
import sys

import httpx

from scripts import general_budget as legacy

MANIFEST = {
    "campaign": "lightweight-confidence-v1",
    "version": 1,
    "limit": 32,
    "endpoint": "https://api.openai.com/v1/responses",
    "model": "gpt-5.6-luna",
    "reasoning": "none",
    "scenario_limits": {"bug": 5, "csv": 6, "recovery": 6, "direct": 3, "parallel": 12},
    "scenario_caps": {"bug": 1024, "csv": 1024, "recovery": 1024, "direct": 768, "parallel": 768},
}
SCHEMA = legacy.SCHEMA + [
    "CREATE TABLE admissions(scenario TEXT PRIMARY KEY,root_id TEXT NOT NULL UNIQUE)",
    "CREATE TABLE terminals(scenario TEXT PRIMARY KEY,outcome TEXT NOT NULL)",
]
TRIGGERS = {
    **legacy.TRIGGERS,
    "hard_limit": legacy.TRIGGERS["hard_limit"].replace(">=24", ">=32"),
    **{
        f"immutable_{t}_{a}": f"CREATE TRIGGER immutable_{t}_{a} BEFORE {a} ON {t} BEGIN SELECT RAISE(ABORT,'immutable campaign'); END"
        for t in ["admissions", "terminals"]
        for a in ["UPDATE", "DELETE"]
    },
}


def manifest(path, *, policy=None):
    policy = policy or sys.modules[__name__]
    return json.dumps({**policy.MANIFEST, "path": str(path)}, sort_keys=True)


def initialize(value, *, policy=None):
    policy = policy or sys.modules[__name__]
    path = legacy.checked(value)
    marker = legacy.checked(path.with_suffix(".started"))
    if path.exists():
        return policy.validate(path)
    if marker.exists():
        raise RuntimeError("Started campaign ledger missing")
    path.parent.mkdir(parents=True, exist_ok=True)
    for target, data in [(marker, policy.manifest(path)), (path, "")]:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    with sqlite3.connect(path) as db:
        for sql in policy.SCHEMA:
            db.execute(sql)
        db.execute("INSERT INTO manifest VALUES (?)", (policy.manifest(path),))
        for sql in policy.TRIGGERS.values():
            db.execute(sql)
    return policy.validate(path)


def validate(value, *, policy=None):
    policy = policy or sys.modules[__name__]
    path = legacy.checked(value)
    marker = legacy.checked(path.with_suffix(".started"))
    if not path.exists() or not marker.exists() or marker.read_text() != policy.manifest(path):
        raise RuntimeError("Campaign identity missing or changed")
    with sqlite3.connect(f"file:{path}?mode=rw", uri=True) as db:
        if db.execute("SELECT value FROM manifest").fetchall() != [(policy.manifest(path),)]:
            raise RuntimeError("Campaign manifest mismatch")
        if dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'")) != policy.TRIGGERS:
            raise RuntimeError("Campaign enforcement mismatch")
        if sorted(r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE type='table'")) != sorted(
            policy.SCHEMA
        ):
            raise RuntimeError("Campaign schema mismatch")
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise RuntimeError("Campaign corrupt")
        return db.execute("SELECT count(*) FROM attempts").fetchone()[0]


def admit(value, scenario, root_id, *, policy=None):
    policy = policy or sys.modules[__name__]
    policy.validate(value)
    if scenario not in policy.MANIFEST["scenario_limits"]:
        raise RuntimeError("Unknown scenario")
    with sqlite3.connect(value) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM terminals WHERE scenario=?", (scenario,)).fetchone():
            raise RuntimeError("Scenario terminal")
        db.execute("INSERT INTO admissions VALUES (?,?)", (scenario, root_id))


def finish(value, scenario, outcome, *, policy=None):
    policy = policy or sys.modules[__name__]
    policy.validate(value)
    with sqlite3.connect(value) as db:
        db.execute("INSERT OR IGNORE INTO terminals VALUES (?,?)", (scenario, outcome))


def reserve(value, context, cap, *, policy=None):
    policy = policy or sys.modules[__name__]
    policy.validate(value)
    scenario = context["scenario"]
    if (
        scenario not in policy.MANIFEST["scenario_limits"]
        or cap != policy.MANIFEST["scenario_caps"][scenario]
    ):
        raise RuntimeError("Scenario outside campaign bounds")
    with sqlite3.connect(value, timeout=30) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT root_id FROM admissions WHERE scenario=?", (scenario,)).fetchone() != (
            context["root_id"],
        ):
            raise RuntimeError("Unadmitted root")
        if db.execute("SELECT 1 FROM terminals WHERE scenario=?", (scenario,)).fetchone():
            raise RuntimeError("Scenario terminal")
        if db.execute(
            "SELECT 1 FROM outcomes JOIN attempts ON attempts.id=outcomes.attempt_id WHERE scenario=? AND classification!='http_success'",
            (scenario,),
        ).fetchone():
            raise RuntimeError("Prior failed or ambiguous transport: scenario stopped")
        count = db.execute("SELECT count(*) FROM attempts WHERE scenario=?", (scenario,)).fetchone()[0]
        if count >= policy.MANIFEST["scenario_limits"][scenario]:
            raise RuntimeError("Scenario exhausted")
        if scenario.rsplit("/", 1)[-1] == "parallel":
            local_limit = (
                policy.MANIFEST.get("parallel_root_limit", 6)
                if context["run_id"] == context["root_id"]
                else policy.MANIFEST.get("parallel_child_limit", 3)
            )
            local_count = db.execute(
                "SELECT count(*) FROM attempts WHERE run_id=?", (context["run_id"],)
            ).fetchone()[0]
            if local_count >= local_limit:
                raise RuntimeError("Parallel local allocation exhausted")
        cursor = db.execute(
            "INSERT INTO attempts(scenario,run_id,root_id,operation_id,physical_attempt_id,output_cap) VALUES (?,?,?,?,?,?)",
            (
                scenario,
                context["run_id"],
                context["root_id"],
                context["operation_id"],
                context["attempt_id"],
                cap,
            ),
        )
        return cursor.lastrowid


class BufferedResponse(httpx.AsyncBaseTransport):
    """Count body-read failures as unknown outcomes, not successful HTTP headers."""

    def __init__(self, inner):
        self.inner = inner

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        try:
            await response.aread()
        except BaseException:
            await response.aclose()
            raise
        return response

    async def aclose(self):
        await self.inner.aclose()


class Transport(legacy.Transport):
    def __init__(self, path, inner=None):
        super().__init__(
            path,
            BufferedResponse(
                inner or httpx.AsyncHTTPTransport(local_address="0.0.0.0", trust_env=False, retries=0)
            ),
            guard=sys.modules[__name__],
        )


def reconcile_unknown(value, *, policy=None):
    """A new worker cannot know whether a previous process completed an unrecorded send."""
    policy = policy or sys.modules[__name__]
    policy.validate(value)
    with sqlite3.connect(value) as db:
        db.execute("BEGIN IMMEDIATE")
        pending = db.execute(
            "SELECT id FROM attempts WHERE id NOT IN (SELECT attempt_id FROM outcomes)"
        ).fetchall()
        for (identity,) in pending:
            db.execute("INSERT INTO outcomes VALUES (?, 'transport_failed_or_ambiguous')", (identity,))
    return len(pending)
