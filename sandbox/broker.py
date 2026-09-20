"""Privileged operator broker; fixed job policy, bounded protocol, persistent reconciliation."""

import hashlib
import hmac
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import project_broker

DB = "/state/jobs.sqlite"
LOCK = threading.Lock()


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], capture_output=True, timeout=kwargs.pop("timeout", 10), **kwargs)


def execute(identity, payload):
    try:
        deadline = json.loads(payload)["deadline"]
        if not isinstance(deadline, (int, float)):
            return {"error": "sandbox_invalid_request"}
    except Exception:
        return {"error": "sandbox_invalid_request"}
    fingerprint = hashlib.sha256(payload).hexdigest()
    name = "agents-sandbox-" + identity
    with LOCK, sqlite3.connect(DB) as db:
        old = db.execute("SELECT digest,result FROM jobs WHERE id=?", (identity,)).fetchone()
        if old:
            if old[0] != fingerprint:
                return {"error": "sandbox_operation_conflict"}
            return json.loads(old[1]) if old[1] else {"error": "sandbox_pending"}
        # The deadline gates new jobs, never retrieval of an already committed result.
        if not time.time() < deadline <= time.time() + 31:
            return {"error": "sandbox_expired"}
        db.execute("INSERT INTO jobs VALUES (?,?,NULL)", (identity, fingerprint))
        db.commit()
    result = {"error": "sandbox_unavailable"}
    try:
        job = docker(
            "run",
            "--name",
            name,
            "--label",
            "agents.sandbox=toolkits-v1",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "SETUID",
            "--cap-add",
            "SETGID",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "32",
            "--memory",
            "128m",
            "--memory-swap",
            "128m",
            "--cpus",
            "1",
            "--ulimit",
            "cpu=10:10",
            "--ulimit",
            "fsize=262144:262144",
            "--ulimit",
            "nofile=64:64",
            "--tmpfs",
            "/work:rw,noexec,nosuid,nodev,size=2m,mode=0755",
            "-i",
            "agent-runtime-sandbox:v1",
            input=payload,
            timeout=20,
        )
        if job.returncode == 0 and len(job.stdout) < 400000:
            result = json.loads(job.stdout)
    except subprocess.TimeoutExpired:
        result = {"error": "sandbox_timeout"}
    except Exception:
        pass
    finally:
        docker("rm", "-f", name)
    with LOCK, sqlite3.connect(DB) as db:
        db.execute("UPDATE jobs SET result=? WHERE id=?", (json.dumps(result), identity))
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
        expected = os.environ.get("SANDBOX_BROKER_KEY", "")
        if not expected or not hmac.compare_digest(supplied, expected):
            self.send_error(401)
            return
        identity = self.path.removeprefix("/jobs/")
        if not re.fullmatch("[a-f0-9]{64}", identity):
            self.send_error(422)
            return
        with LOCK, sqlite3.connect(DB) as db:
            row = db.execute("SELECT result FROM jobs WHERE id=?", (identity,)).fetchone()
        data = json.dumps(
            {"state": "complete" if row and row[0] else "pending" if row else "unknown"}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
        expected = os.environ.get("SANDBOX_BROKER_KEY", "")
        if not expected or not hmac.compare_digest(supplied, expected):
            self.send_error(401)
            return
        project = self.path.startswith("/projects/")
        identity = self.path.removeprefix("/projects/" if project else "/jobs/")
        size = int(self.headers.get("Content-Length", "0"))
        if (
            not (self.path.startswith("/jobs/") or project)
            or not re.fullmatch("[a-f0-9]{64}", identity)
            or not 1 <= size <= (6291456 if project else 400000)
        ):
            self.send_error(422)
            return
        raw = self.rfile.read(size)
        if project:
            import project_broker

            if raw == b'{"cancel":true}':
                result = project_broker.cancel(identity)
            elif raw == b'{"ack":true}':
                result = project_broker.acknowledge(identity)
            else:
                result = project_broker.request(identity, raw)
        else:
            result = execute(identity, raw)
        encoded = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


os.makedirs("/state", exist_ok=True)
with sqlite3.connect(DB) as db:
    db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,digest TEXT NOT NULL,result TEXT)")
    for (identity,) in db.execute("SELECT id FROM jobs WHERE result IS NULL"):
        docker("rm", "-f", "agents-sandbox-" + identity)
        db.execute("UPDATE jobs SET result=? WHERE id=?", ('{"error":"sandbox_interrupted"}', identity))
project_broker.initialize()
ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
