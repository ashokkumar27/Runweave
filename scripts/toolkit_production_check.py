"""Fake-only public HTTP verification of the deployed images. Never calls a live provider."""

import asyncio
import hashlib
import json
from pathlib import Path

from dotenv import dotenv_values

from agent_runtime.client import Client
from agent_runtime.schemas import AgentConfig
from agent_runtime.tool_contracts import SubagentSpec
from scripts.toolkit_acceptance import scripted


async def main():
    key = dotenv_values(".env.api.local", interpolate=False)["API_KEY"]
    async with Client(api_key=key) as client:
        data = await client.upload(
            Path("docs/fixtures/toolkits/invoices.csv").read_bytes(), "text/csv", "invoices.csv"
        )
        specialist = await client.create_agent(
            AgentConfig(
                name="production fake CSV check",
                provider="fake",
                model="deterministic",
                tools=["csv_analyze"],
                max_tokens=512,
            )
        )
        parent = await client.create_agent(
            AgentConfig(
                name="production fake delegation check",
                provider="fake",
                model="deterministic",
                tools=["delegate"],
                max_tokens=512,
                subagents=[
                    SubagentSpec(
                        name="analyst", agent_id=specialist.id, description="Analyze synthetic invoices"
                    )
                ],
            )
        )
        instruction = scripted([("csv_analyze", {"artifact_id": data.id})])
        root = await client.submit(
            parent.id,
            scripted(
                [
                    (
                        "delegate",
                        {"specialist": "analyst", "instruction": instruction, "artifact_ids": [data.id]},
                    )
                ]
            ),
            artifact_ids=[data.id],
        )
        result = await client.wait(root.id, timeout=60, stop_at_approval=False)
        assert result.status == "completed" and len(result.artifacts) == 1
        output = await client.download(result.artifacts[0].id)
        assert output == Path("docs/fixtures/toolkits/cleaned.csv").read_bytes()
        children = await client.children(root.id)
        assert len(children) == 1 and children[0].status == "completed"
        report = {
            "run": result.model_dump(mode="json"),
            "children": [c.model_dump(mode="json") for c in children],
            "budget": await client.budget(root.id),
            "effects": await client.effects(root.id),
            "download_sha256": hashlib.sha256(output).hexdigest(),
            "download_bytes": len(output),
            "readiness": await client.readiness(),
            "live_calls": 0,
        }
        Path("docs/acceptance-toolkits-production.json").write_text(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": result.status,
                    "root_run_id": root.id,
                    "children": len(children),
                    "download_bytes": len(output),
                    "live_calls": 0,
                }
            )
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print("Production verification failed (" + type(exc).__name__ + "; details suppressed)")
        raise SystemExit(1) from None
