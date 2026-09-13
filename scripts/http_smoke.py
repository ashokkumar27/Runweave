"""Exercise a running API with fake models only; API_KEY must be in the environment."""

import argparse
import asyncio
import os
from uuid import uuid4

import httpx


async def main(base_url):
    async with httpx.AsyncClient(
        base_url=base_url, headers={"Authorization": f"Bearer {os.environ['API_KEY']}"}
    ) as client:
        async with asyncio.timeout(30):
            while True:
                try:
                    response = await client.get("/openapi.json")
                    response.raise_for_status()
                    break
                except httpx.HTTPError:
                    await asyncio.sleep(0.1)

        async def post(path, data=None, **kwargs):
            response = await client.post(path, json=data, **kwargs)
            response.raise_for_status()
            return response.json()

        async def wait(run_id, desired):
            async with asyncio.timeout(30):
                while True:
                    result = (await client.get(f"/v1/runs/{run_id}")).json()
                    if result["status"] in desired:
                        return result
                    assert result["status"] not in {"failed", "cancelled"}, result["error"]
                    await asyncio.sleep(0.05)

        agent = await post(
            "/v1/agents",
            {
                "name": "HTTP smoke",
                "provider": "fake",
                "model": "deterministic",
                "tools": ["add", "record_note", "convert_temperature"],
            },
        )
        body = {"agent_id": agent["id"], "input": "add 2 3"}
        headers = {"Idempotency-Key": uuid4().hex}
        run = await post("/v1/runs", body, headers=headers)
        assert (await post("/v1/runs", body, headers=headers))["id"] == run["id"]
        assert (await wait(run["id"], {"completed"}))["output"]["value"] == 5
        events = await client.get(f"/v1/runs/{run['id']}/events")
        assert "run.completed" in events.text
        replay = await client.get(f"/v1/runs/{run['id']}/events", headers={"Last-Event-ID": "1"})
        assert "id: 1\n" not in replay.text and "run.completed" in replay.text
        continued = await post(
            "/v1/runs",
            {**body, "session_id": run["session_id"], "input": "previous"},
            headers={"Idempotency-Key": uuid4().hex},
        )
        assert (await wait(continued["id"], {"completed"}))["output"]["value"] == 5
        note = await post(
            "/v1/runs", {**body, "input": "note:HTTP approval"}, headers={"Idempotency-Key": uuid4().hex}
        )
        pending = await wait(note["id"], {"awaiting_approval"})
        await post(f"/v1/runs/{note['id']}/approvals/{pending['approvals'][0]['id']}", {"approved": True})
        await wait(note["id"], {"completed"})
        mcp = await post(
            "/v1/runs", {**body, "input": "temperature:100"}, headers={"Idempotency-Key": uuid4().hex}
        )
        assert (await wait(mcp["id"], {"completed"}))["output"]["value"] == 212
        assert (
            await client.get("/v1/runs/missing", headers={"Authorization": "Bearer wrong"})
        ).status_code == 401
        print(
            "HTTP smoke PASS: auth, duplicate submission, durable result, SSE replay, continuation, approval, MCP"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    asyncio.run(main(args.base_url))
