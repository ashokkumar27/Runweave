"""Worker backend: HTTP protocol only, no host execution or daemon access."""

import base64
import hashlib
import os
import time

import httpx


async def run_python(operation_id, code, content, *, deadline=None):
    endpoint = os.environ.get("SANDBOX_BROKER_URL")
    key = os.environ.get("SANDBOX_BROKER_KEY")
    if not endpoint or not key:
        raise ValueError("sandbox_unavailable")
    try:
        async with httpx.AsyncClient(timeout=25, trust_env=False, follow_redirects=False) as client:
            response = await client.post(
                endpoint + "/jobs/" + hashlib.sha256(operation_id.encode()).hexdigest(),
                headers={"Authorization": "Bearer " + key},
                json={
                    "code": code,
                    "input": base64.b64encode(content).decode(),
                    "deadline": deadline or time.time() + 30,
                },
            )
            if response.status_code != 200 or len(response.content) > 400000:
                raise ValueError
            data = response.json()
    except Exception:
        raise ValueError("sandbox_unavailable") from None
    if data.get("error"):
        raise ValueError(
            data["error"]
            if data["error"]
            in {
                "sandbox_timeout",
                "sandbox_execution_failed",
                "sandbox_output_limit",
                "sandbox_interrupted",
                "sandbox_pending",
            }
            else "sandbox_unavailable"
        )
    output = base64.b64decode(data["content"], validate=True)
    if len(output) > 262144 or len(data["stdout"]) > 16384:
        raise ValueError("sandbox_output_limit")
    return output, data["stdout"]


async def job_complete(identity, deadline):
    endpoint = os.environ.get("SANDBOX_BROKER_URL")
    key = os.environ.get("SANDBOX_BROKER_KEY")
    if not endpoint or not key:
        return False
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(
                endpoint + "/jobs/" + identity, headers={"Authorization": "Bearer " + key}
            )
            return response.status_code == 200 and (
                response.json().get("state") == "complete"
                or (response.json().get("state") == "unknown" and time.time() > deadline)
            )
    except Exception:
        return False
