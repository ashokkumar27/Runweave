"""Trusted PID-1 project supervisor. Program output is never trusted control data."""

import base64
import hashlib
import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import time
import unicodedata


def valid_path(p):
    parts = p.split("/")
    if not p or len(p.encode()) > 200 or len(parts) > 16 or unicodedata.normalize("NFC", p) != p or "\\" in p:
        raise ValueError
    if any(
        x in {"", ".", ".."}
        or x.casefold() in {".git", ".runtime", "__runtime__"}
        or len(x.encode()) > 100
        or any(ord(c) < 32 or ord(c) == 127 for c in x)
        for x in parts
    ):
        raise ValueError


def terminate():
    # Kill every generated process, including setsid/fork escapees. No untrusted
    # process may remain alive while the supervisor walks writable directories.
    for _ in range(100):
        alive = False
        for name in os.listdir("/proc"):
            if not name.isdigit() or int(name) == os.getpid():
                continue
            try:
                with open("/proc/" + name + "/status") as f:
                    status = f.read()
                uid = next(x for x in status.splitlines() if x.startswith("Uid:")).split()[1]
                if uid == "65534":
                    os.kill(int(name), signal.SIGKILL)
                    alive = True
            except (FileNotFoundError, ProcessLookupError):
                pass
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
            except ChildProcessError:
                break
        if not alive:
            return
        time.sleep(0.01)
    raise RuntimeError


def collect(root, max_files, max_bytes):
    files = {}
    total = 0

    def walk(fd, prefix=""):
        nonlocal total
        for name in sorted(os.listdir(fd)):
            p = prefix + name
            valid_path(p)
            st = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(st.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    walk(child, p + "/")
                finally:
                    os.close(child)
            elif stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_size <= 262144:
                child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                try:
                    actual = os.fstat(child)
                    if actual.st_ino != st.st_ino or actual.st_nlink != 1 or not stat.S_ISREG(actual.st_mode):
                        raise ValueError
                    data = os.read(child, 262145)
                finally:
                    os.close(child)
                if len(data) != st.st_size:
                    raise ValueError
                total += len(data)
                files[p] = {
                    "content_base64": base64.b64encode(data).decode(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                }
                if total > max_bytes or len(files) > max_files:
                    raise ValueError
            else:
                raise ValueError

    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk(fd)
    finally:
        os.close(fd)
    return files


def main():
    raw = sys.stdin.buffer.read(6291457)
    if len(raw) > 6291456:
        raise ValueError
    payload = json.loads(raw)
    for directory in ("project", "outputs", "scratch"):
        os.mkdir("/work/" + directory, 0o700)
        os.chown("/work/" + directory, 65534, 65534)
    for name, encoded in payload["files"].items():
        valid_path(name)
        target = "/work/project/" + name
        os.makedirs(os.path.dirname(target), exist_ok=True)
        data = base64.b64decode(encoded, validate=True)
        if len(data) > 262144:
            raise ValueError
        with open(target, "xb") as f:
            f.write(data)
        os.chmod(target, 0o600)
        os.chown(target, 65534, 65534)
    for directory, _, _ in os.walk("/work/project"):
        # Ownership grants the generated UID access; inherited safe directory modes suffice.
        os.chown(directory, 65534, 65534)
    argv = payload["argv"]
    if (
        not isinstance(argv, list)
        or not 1 <= len(argv) <= 32
        or sum(len(a.encode()) for a in argv) > 4096
        or argv[0] not in {"python", "python3", "pytest"}
    ):
        raise ValueError
    executable = ["/usr/local/bin/python", "-B"]
    if argv[0] == "pytest":
        executable += ["-I", "-m", "pytest", "-p", "no:cacheprovider"]
    cwd = payload.get("cwd", "")
    if cwd:
        valid_path(cwd)
    process = subprocess.Popen(
        executable + argv[1:],
        cwd="/work/project" + ("/" + cwd if cwd else ""),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        user=65534,
        group=65534,
        extra_groups=[],
        start_new_session=True,
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "HOME": "/work/scratch",
            "TMPDIR": "/work/scratch",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + min(60, payload.get("wall_seconds", 60))
    truncated = False
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise TimeoutError
            for key, _ in selector.select(0.05):
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    left = 65536 - sum(map(len, outputs.values()))
                    outputs[key.data].extend(chunk[:left])
                    truncated |= len(chunk) > left
        code = process.wait(timeout=1)
    finally:
        terminate()
    files = collect("/work/project", 256, 4194304)
    named = collect("/work/outputs", 16, 1048576)
    logs = {
        n: {
            "content_base64": base64.b64encode(bytes(b)).decode(),
            "sha256": hashlib.sha256(b).hexdigest(),
            "size_bytes": len(b),
        }
        for n, b in outputs.items()
    }
    return {"exit_code": code, "files": files, "outputs": named, "logs": logs, "truncated": truncated}


try:
    result = main()
except TimeoutError:
    result = {"error": "sandbox_timeout"}
except Exception:
    result = {"error": "sandbox_unsafe_result"}
print(json.dumps(result), flush=True)
