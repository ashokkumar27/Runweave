"""Trusted in-container supervisor. Never executes generated code as its own UID."""

import base64
import json
import os
import pathlib
import selectors
import signal
import stat
import subprocess
import sys
import time


def main():
    payload = json.loads(sys.stdin.buffer.read(400000))
    source = payload["code"]
    if len(source.encode()) > 8000:
        raise ValueError
    data = base64.b64decode(payload["input"], validate=True)
    if len(data) > 262144:
        raise ValueError
    pathlib.Path("/work/input").mkdir(mode=0o755)
    pathlib.Path("/work/input/data").write_bytes(data)
    os.chmod("/work/input/data", 0o444)
    os.chmod("/work/input", 0o555)
    pathlib.Path("/work/output").mkdir(mode=0o777)
    os.chmod("/work/output", 0o777)
    pathlib.Path("/work/program.py").write_text(source)
    os.chmod("/work/program.py", 0o444)
    process = subprocess.Popen(
        ["/usr/local/bin/python", "-I", "-B", "/work/program.py"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
        cwd="/work/output",
        user=65534,
        group=65534,
        extra_groups=[],
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + 12
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise TimeoutError
            for key, _ in selector.select(0.1):
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    outputs[key.data].extend(chunk)
                    if sum(map(len, outputs.values())) > 16384:
                        raise ValueError
        if process.wait(timeout=1) != 0:
            return {"error": "sandbox_execution_failed"}
        path = pathlib.Path("/work/output/result")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 262144:
                raise ValueError
            result = os.read(fd, 262145)
            result.decode("utf-8")
        finally:
            os.close(fd)
        return {"content": base64.b64encode(result).decode(), "stdout": outputs["stdout"].decode("utf-8")}
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


try:
    result = main()
except TimeoutError:
    result = {"error": "sandbox_timeout"}
except Exception:
    result = {"error": "sandbox_output_limit"}
print(json.dumps(result), flush=True)
