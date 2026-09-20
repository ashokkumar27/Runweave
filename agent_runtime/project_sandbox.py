"""Authenticated worker-to-broker transport; never executes project code locally."""

import os

import httpx

from .project_store import digest, fail


async def project_request(identity, payload=None, *, acknowledge=False, cancel=False):
    endpoint = os.environ.get("SANDBOX_BROKER_URL")
    key = os.environ.get("SANDBOX_BROKER_KEY")
    if not endpoint or not key:
        fail("sandbox_unavailable", 503)
    try:
        async with httpx.AsyncClient(timeout=70, trust_env=False, follow_redirects=False) as client:
            response = await client.post(
                endpoint + "/projects/" + digest(identity.encode()),
                headers={"Authorization": "Bearer " + key},
                content=b'{"cancel":true}' if cancel else b'{"ack":true}' if acknowledge else None,
                json=None if acknowledge or cancel else payload,
            )
            if response.status_code != 200 or len(response.content) > 8388608:
                raise ValueError
            return response.json()
    except Exception:
        fail("sandbox_unavailable", 503)
