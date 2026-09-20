"""Fake-only deployed v3 and legacy compatibility check through authenticated HTTP."""

import asyncio
import base64
import hashlib
import json
from pathlib import Path

from dotenv import dotenv_values

from agent_runtime.client import Client
from agent_runtime.general_contracts import GeneralPolicy
from agent_runtime.schemas import AgentConfig
from scripts.general_acceptance import invoke, script


async def main():
    key = dotenv_values(".env.api.local", interpolate=False)["API_KEY"]
    report = {"live_calls": 0, "runs": []}
    async with Client(api_key=key) as client:
        for version in (1, 2, 3):
            cfg = AgentConfig(
                name=f"v3 rollout compatibility v{version}",
                provider="fake",
                model="deterministic",
                tools=["add"] if version == 2 else [],
                max_total_tokens=4000 if version == 2 else None,
                general=GeneralPolicy() if version == 3 else None,
            )
            agent = await client.create_agent(cfg)
            run = await client.submit(agent.id, "What is 7 + 5?")
            result = await client.wait(run.id, timeout=60)
            assert result.status == "completed"
            assert (await client.budget(run.id))["execution_version"] == version
            report["runs"].append(result.model_dump(mode="json"))
        workspace = await client.workspace_create({"input.txt": b"retained input\n"})
        agent = await client.create_agent(
            AgentConfig(
                name="v3 rollout isolated project",
                provider="fake",
                model="deterministic",
                tools=["workspace_command", "workspace_verify"],
                general=GeneralPolicy(),
            )
        )
        run = await client.submit(
            agent.id,
            script(
                invoke(
                    "workspace_command",
                    expected_revision="$HEAD",
                    argv=[
                        "python",
                        "-c",
                        "from pathlib import Path; Path('result.txt').write_text('isolated result\\n')",
                    ],
                    commit=True,
                ),
                invoke("workspace_verify", expected_revision="$HEAD", check_id="runtime.syntax"),
            ),
            workspace=workspace,
        )
        result = await client.wait(run.id, timeout=90)
        assert result.status == "completed"
        content = await client.workspace_read(
            result.workspace["workspace_id"], result.workspace["revision_id"], "result.txt"
        )
        assert content == b"isolated result\n"
        report.update(
            project=result.model_dump(mode="json"),
            task=await client.task(run.id),
            operations=await client.operations(run.id),
            verifications=await client.verifications(run.id),
            budget=await client.budget(run.id),
            readiness=await client.readiness(),
            download={
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes_base64": base64.b64encode(content).decode(),
            },
        )
    path = Path("docs/acceptance-general-runtime-v3-production.json")
    reports = json.loads(path.read_text()) if path.exists() else {"executions": []}
    reports["executions"].append(report)
    path.write_text(json.dumps(reports, indent=2) + "\n")
    print(json.dumps({"legacy_versions": [1, 2], "v3": "completed", "project": "completed", "live_calls": 0}))


if __name__ == "__main__":
    asyncio.run(main())
