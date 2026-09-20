"""Durable v3 broker protocol, separate from retained v1 job state."""

import hashlib
import json
import sqlite3
import subprocess
import threading
import time

LOCK = threading.Lock()
DB = "/state/projects-v3.sqlite"


def docker(*args, timeout=10, **kwargs):
    return subprocess.run(["docker", *args], capture_output=True, timeout=timeout, **kwargs)


def initialize():
    with LOCK, sqlite3.connect(DB) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,digest TEXT NOT NULL,result TEXT,ack INTEGER NOT NULL DEFAULT 0)"
        )
        for (identity,) in db.execute("SELECT id FROM attempts WHERE result IS NULL"):
            docker("rm", "-f", "agents-project-v3-" + identity)
            inspect = docker("inspect", "agents-project-v3-" + identity)
            if inspect.returncode != 0:
                db.execute(
                    "UPDATE attempts SET result=? WHERE id=?", ('{"error":"sandbox_interrupted"}', identity)
                )


def request(identity, payload):
    fingerprint = hashlib.sha256(payload).hexdigest()
    data = json.loads(payload)
    with LOCK, sqlite3.connect(DB) as db:
        old = db.execute("SELECT digest,result,ack FROM attempts WHERE id=?", (identity,)).fetchone()
        if old:
            if old[0] != fingerprint:
                return {"error": "sandbox_operation_conflict"}
            return json.loads(old[1]) if old[1] else {"error": "sandbox_pending"}
        if not time.time() < data.get("deadline", 0) <= time.time() + 120:
            return {"error": "sandbox_expired"}
        count = db.execute("SELECT count(*) FROM attempts WHERE ack=0").fetchone()[0]
        if count >= 32:
            return {"error": "sandbox_retention_limit"}
        db.execute("INSERT INTO attempts(id,digest) VALUES (?,?)", (identity, fingerprint))
        db.commit()
    name = "agents-project-v3-" + identity
    result = {"error": "sandbox_unavailable"}
    try:
        with open("/opt/general.json") as config:
            allowed_image = json.load(config)["image_digest"]
        image = data.get("image_digest")
        if image != allowed_image:
            raise ValueError
        run = docker(
            "run",
            "--name",
            name,
            "--label",
            "agents.sandbox=general-v3",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "SETUID",
            "--cap-add",
            "SETGID",
            "--cap-add",
            "CHOWN",
            "--cap-add",
            "KILL",
            "--cap-add",
            "DAC_OVERRIDE",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "64",
            "--memory",
            "256m",
            "--memory-swap",
            "256m",
            "--cpus",
            "1",
            "--ulimit",
            "cpu=30:30",
            "--ulimit",
            "fsize=262144:262144",
            "--ulimit",
            "nofile=128:128",
            "--tmpfs",
            "/work:rw,noexec,nosuid,nodev,size=16m,mode=0755",
            "-i",
            image,
            input=payload,
            timeout=65,
        )
        if run.returncode == 0 and len(run.stdout) <= 8388608:
            result = json.loads(run.stdout)
            result["image_digest"] = image
    except subprocess.TimeoutExpired:
        result = {"error": "sandbox_timeout"}
    except Exception:
        pass
    finally:
        docker("rm", "-f", name)
        if docker("inspect", name).returncode == 0:
            result = {"error": "sandbox_pending"}
    with LOCK, sqlite3.connect(DB) as db:
        if result.get("error") != "sandbox_pending":
            db.execute(
                "UPDATE attempts SET result=? WHERE id=? AND result IS NULL", (json.dumps(result), identity)
            )
    return result


def acknowledge(identity):
    with LOCK, sqlite3.connect(DB) as db:
        db.execute(
            "UPDATE attempts SET ack=1,result=? WHERE id=? AND result IS NOT NULL",
            ('{"acknowledged":true}', identity),
        )
    return {"acknowledged": True}


def cancel(identity):
    name = "agents-project-v3-" + identity
    docker("rm", "-f", name)
    if docker("inspect", name).returncode == 0:
        return {"error": "sandbox_pending"}
    with LOCK, sqlite3.connect(DB) as db:
        db.execute(
            "INSERT OR IGNORE INTO attempts(id,digest,result) VALUES (?,?,?)",
            (identity, "cancelled", '{"error":"sandbox_cancelled"}'),
        )
        db.execute(
            "UPDATE attempts SET result=? WHERE id=? AND result IS NULL",
            ('{"error":"sandbox_cancelled"}', identity),
        )
    return {"cancelled": True}
