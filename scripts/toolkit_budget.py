"""Immutable 50-attempt campaign guard. No credentials or request bodies are persisted."""

import json
import os
import sqlite3
import stat
from pathlib import Path

import httpx

MANIFEST = {
    "campaign": "toolkits-subagents-v1",
    "limit": 50,
    "endpoint": "https://api.openai.com/v1/responses",
    "model": "gpt-5.6-luna",
    "output_caps": [512, 1024],
    "reasoning": "none",
    "version": 1,
    "scenario_limits": {
        "single-documents": 8,
        "delegated-documents": 16,
        "csv": 12,
        "repository": 8,
        "headroom": 6,
    },
}


def checked(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise RuntimeError("Campaign symlink refused")
    if path.exists() and not stat.S_ISREG(path.stat().st_mode):
        raise RuntimeError("Campaign file must be regular")
    return path


def initialize(path):
    path = checked(path)
    marker = path.with_suffix(".started")
    checked(marker)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        validate(path)
        if not marker.is_file():
            raise RuntimeError("Campaign marker missing")
        return
    if marker.exists():
        raise RuntimeError("Started campaign ledger missing; refused reset")
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(json.dumps(MANIFEST, sort_keys=True))
        file.flush()
        os.fsync(file.fileno())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE manifest (value TEXT NOT NULL)")
        db.execute("INSERT INTO manifest VALUES (?)", (json.dumps(MANIFEST, sort_keys=True),))
        db.execute(
            "CREATE TABLE attempts (id INTEGER PRIMARY KEY, scenario TEXT NOT NULL, run_id TEXT NOT NULL, root_id TEXT NOT NULL, output_cap INTEGER NOT NULL, reserved_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        for table in ["manifest", "attempts"]:
            for action in ["UPDATE", "DELETE"]:
                db.execute(
                    f"CREATE TRIGGER immutable_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable campaign'); END"
                )
        db.execute(
            "CREATE TRIGGER hard_limit BEFORE INSERT ON attempts WHEN (SELECT count(*) FROM attempts)>=50 BEGIN SELECT RAISE(ABORT,'campaign exhausted'); END"
        )
        db.execute(
            "CREATE TRIGGER immutable_manifest_insert BEFORE INSERT ON manifest BEGIN SELECT RAISE(ABORT,'immutable manifest'); END"
        )
    validate(path)


def validate(path):
    path = checked(path)
    if not path.exists():
        raise RuntimeError("Campaign ledger missing")
    with sqlite3.connect(f"file:{path}?mode=rw", uri=True) as db:
        values = db.execute("SELECT value FROM manifest").fetchall()
        if values != [(json.dumps(MANIFEST, sort_keys=True),)]:
            raise RuntimeError("Campaign manifest mismatch")
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError("Campaign ledger corrupt")
        return db.execute("SELECT count(*) FROM attempts").fetchone()[0]


def reserve(path, scenario, run_id, cap, root_id=None):
    validate(path)
    with sqlite3.connect(f"file:{checked(path)}?mode=rw", uri=True, timeout=30) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT count(*) FROM attempts").fetchone()[0] >= 50:
            raise RuntimeError("Campaign exhausted")
        db.execute(
            "INSERT INTO attempts(scenario,run_id,root_id,output_cap) VALUES (?,?,?,?)",
            (scenario, run_id, root_id or run_id, cap),
        )
        db.commit()


class Transport(httpx.AsyncBaseTransport):
    def __init__(self, path, inner=None):
        self.path = checked(path)
        validate(self.path)
        self.inner = inner or httpx.AsyncHTTPTransport(local_address="0.0.0.0", trust_env=False, retries=0)

    async def handle_async_request(self, request):
        from agent_runtime.model_adapter import request_context

        body = json.loads(await request.aread())
        if (
            str(request.url) != MANIFEST["endpoint"]
            or body.get("model") != MANIFEST["model"]
            or body.get("max_output_tokens") not in MANIFEST["output_caps"]
            or body.get("reasoning", {}).get("effort") != "none"
        ):
            raise RuntimeError("Request outside campaign bounds")
        context = request_context.get()
        if not context:
            raise RuntimeError("Missing accounted API run context")
        reserve(
            self.path,
            context.get("scenario", "test"),
            context["run_id"],
            body["max_output_tokens"],
            context.get("root_id"),
        )
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        await self.inner.aclose()
