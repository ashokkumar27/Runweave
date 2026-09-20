import base64
import json

import httpx
import pytest

from agent_runtime.api import create_app
from agent_runtime.client import Client
from agent_runtime.general_contracts import GeneralPolicy
from agent_runtime.general_runtime import general_action, general_step
from agent_runtime.project_store import path, three_way
from agent_runtime.schemas import AgentConfig
from agent_runtime.store import Problem


@pytest.mark.parametrize(
    "name", ["../a", "/a", "a//b", "a/./b", "a\\b", ".git/x", "a/../b", "x\x00", "e\u0301"]
)
def test_paths_reject(name):
    with pytest.raises(Problem):
        path(name)


def test_three_way_conflicts():
    assert three_way({"a": b"1"}, {"a": b"2"}, {"a": b"3"}, [""])[1] == ["a"]
    assert three_way({}, {"a": b"1"}, {"a": b"2"}, [""])[1] == ["a"]
    assert three_way({"a": b"1"}, {}, {"a": b"2"}, [""])[1] == ["a"]
    assert three_way({"a": b"1"}, {"a": b"1", "b": b"2"}, {"a": b"3"}, [""])[0] == {"a": b"3", "b": b"2"}


@pytest.mark.asyncio
async def test_general_http_direct_and_legacy_retry(store):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(store, "test")),
        base_url="http://test",
        headers={"Authorization": "Bearer test"},
    ) as http:
        client = Client(http_client=http)
        config = AgentConfig(
            name="direct", provider="fake", model="deterministic", tools=[], general=GeneralPolicy()
        )
        agent = await client.create_agent(config)
        run = await client.submit(agent.id, "Explain a binary tree", idempotency_key="direct")
        decision = await general_step(run.id)
        result = await general_action({"run_id": run.id, **decision})
        assert result["accepted"]
        got = await client.get(run.id)
        assert got.status == "completed" and got.execution_version == 3
        assert (await client.budget(run.id))["requests"] == 1
        assert (await client.task(run.id))["goal"]["criteria"][0]["origin"] == "model"
        assert len((await client.checkpoints(run.id))["items"]) == 1
        assert await client.children(run.id) == []
        await client.update_agent(agent.id, config.model_copy(update={"general": None}))
        retry = await client.submit(agent.id, "Explain a binary tree", idempotency_key="direct")
        assert retry.status == "completed" and retry.execution_version == 3
        legacy = await client.submit(agent.id, "add 1 2", idempotency_key="legacy")
        await client.update_agent(agent.id, config)
        assert (await client.submit(agent.id, "add 1 2", idempotency_key="legacy")).id == legacy.id


@pytest.mark.asyncio
async def test_workspace_http_revision_and_rejected_proof(store):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(store, "test")),
        base_url="http://test",
        headers={"Authorization": "Bearer test"},
    ) as http:
        client = Client(http_client=http)
        workspace = await client.workspace_create({"main.py": b"x = 1\n"}, idempotency_key="upload")
        assert workspace == await client.workspace_create({"main.py": b"x = 1\n"}, idempotency_key="upload")
        assert (
            await client.workspace_read(workspace["workspace_id"], workspace["revision_id"], "main.py")
            == b"x = 1\n"
        )
        assert (
            await client.workspace_download(workspace["workspace_id"], workspace["revision_id"])
        ).startswith(b"PK")
        config = AgentConfig(
            name="edit",
            provider="fake",
            model="deterministic",
            general=GeneralPolicy(),
            tools=["workspace_write", "workspace_read", "workspace_verify"],
        )
        agent = await client.create_agent(config)
        from agent_runtime.project_store import digest

        script = [
            {
                "action": {
                    "kind": "invoke",
                    "capability": "workspace_write",
                    "arguments": {
                        "expected_revision": "$HEAD",
                        "writes": [
                            {
                                "path": "main.py",
                                "expected_sha256": digest(b"x = 1\n"),
                                "content_base64": base64.b64encode(b"x = 2\n").decode(),
                            }
                        ],
                    },
                }
            }
        ]
        run = await client.submit(agent.id, "general:" + json.dumps(script), workspace=workspace)
        result = await general_action({"run_id": run.id, **await general_step(run.id)})
        assert result["changed"], result
        modified = await client.get(run.id)
        assert modified.workspace["revision_id"] != workspace["revision_id"]
        assert (
            await client.workspace_read(workspace["workspace_id"], workspace["revision_id"], "main.py")
            == b"x = 1\n"
        )
        rejection = await general_action({"run_id": run.id, **await general_step(run.id)})
        assert not rejection["accepted"]
        assert "evidence_required:runtime.integrated" in rejection["remaining_gaps"]


@pytest.mark.asyncio
async def test_forged_evidence_and_check_authority(store):
    from agent_runtime.general_contracts import TaskGoal
    from agent_runtime.schemas import RunCreate

    agent = await store.agent(
        AgentConfig(name="proof", provider="fake", model="deterministic", tools=[], general=GeneralPolicy())
    )
    task = TaskGoal(
        outcome="Prove a file",
        criteria=[
            {"id": "proof", "statement": "Verify file", "evidence_policy": "check", "origin": "runtime"}
        ],
    )
    run = await store.submit(RunCreate(agent_id=agent.id, input="proof", task=task), "proof")
    state = await store.general(run.id)
    assert state["goal"]["criteria"][0]["origin"] == "user"
    decision = {
        "action": {
            "kind": "complete",
            "answer": "fabricated",
            "assessment": {
                "proposal_id": "fake",
                "state_version": 1,
                "goal_version": 1,
                "criteria": [
                    {
                        "criterion_id": "proof",
                        "disposition": "satisfied",
                        "evidence_ids": ["invented"],
                        "assessment": "trust me",
                    }
                ],
            },
        }
    }
    result = await store.general_operation(run.id, 0, decision)
    assert not result["accepted"] and "invalid_evidence:proof" in result["remaining_gaps"]
    assert (await store.get(run.id)).status != "completed"
    with pytest.raises(Problem):
        await store.finish(run.id, "completed", output={"answer": "bypass"})


@pytest.mark.asyncio
async def test_metadata_effect_denial_and_cas(store):
    from agent_runtime.schemas import RunCreate

    agent = await store.agent(
        AgentConfig(
            name="effects",
            provider="fake",
            model="deterministic",
            tools=["record_note", "record_set"],
            general=GeneralPolicy(),
        )
    )
    run = await store.submit(RunCreate(agent_id=agent.id, input="effects"), "effects")

    def call(tool, **args):
        return {"action": {"kind": "invoke", "capability": tool, "arguments": args}}

    first = call("record_set", key="sample", value="one", expected_version=0)
    approval = await store.general_operation(run.id, 0, first)
    await store.decide(run.id, approval["approval"], False)
    assert (await store.general_operation(run.id, 0, first))["error"] == "effect_denied"
    assert (
        await store.general_operation(
            run.id, 1, call("record_set", key="sample", value="reworded", expected_version=0)
        )
    )["error"] == "effect_denied"
    note = call("record_note", text="separate effect domain")
    approval = await store.general_operation(run.id, 2, note)
    await store.decide(run.id, approval["approval"], True)
    committed = await store.general_operation(run.id, 2, note)
    assert committed["effect"] == "committed"
    assert await store.general_operation(run.id, 2, note) == committed
    with pytest.raises(Problem):
        await store.decide(run.id, approval["approval"], False)


@pytest.mark.asyncio
async def test_small_nonproject_budget_and_large_bounded_reads(store):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(store, "test")),
        base_url="http://test",
        headers={"Authorization": "Bearer test"},
    ) as http:
        client = Client(http_client=http)
        agent = await client.create_agent(
            AgentConfig(
                name="small",
                provider="fake",
                model="deterministic",
                tools=["add"],
                general=GeneralPolicy(limits={"model_attempts": 2, "tool_attempts": 2}),
            )
        )
        run = await client.submit(
            agent.id, 'general:[{"action":{"kind":"invoke","capability":"add","arguments":{"a":2,"b":3}}}]'
        )
        assert (await general_action({"run_id": run.id, **await general_step(run.id)}))["value"] == 5
        assert (await general_action({"run_id": run.id, **await general_step(run.id)}))["accepted"]
        workspace = await client.workspace_create(
            {"binary.dat": b"\xff" * 16384, "policy.txt": b"match\n" * 100}
        )
        agent = await client.create_agent(
            AgentConfig(
                name="read",
                provider="fake",
                model="deterministic",
                tools=["workspace_read", "workspace_search"],
                general=GeneralPolicy(),
            )
        )
        script = [
            {
                "action": {
                    "kind": "invoke",
                    "capability": "workspace_search",
                    "arguments": {"query": "match", "cursor": 40},
                }
            },
            {
                "action": {
                    "kind": "invoke",
                    "capability": "workspace_read",
                    "arguments": {"path": "binary.dat", "length": 16384},
                }
            },
            {
                "action": {
                    "kind": "invoke",
                    "capability": "workspace_read",
                    "arguments": {"path": "policy.txt", "criterion_id": "source", "quote": "match"},
                }
            },
        ]
        run = await client.submit(
            agent.id,
            "general:" + json.dumps(script),
            workspace=workspace,
            task={
                "outcome": "Read the source",
                "criteria": [{"id": "source", "statement": "Source says match", "evidence_policy": "source"}],
            },
        )
        search = await general_action({"run_id": run.id, **await general_step(run.id)})
        assert len(search["hits"]) == 40 and search["hits"][0]["line"] == 41 and search["next_cursor"] == 80
        read = await general_action({"run_id": run.id, **await general_step(run.id)})
        assert base64.b64decode(read["content_base64"]) == b"\xff" * 16384
        await general_action({"run_id": run.id, **await general_step(run.id)})
        assert (await general_action({"run_id": run.id, **await general_step(run.id)}))["accepted"]
        assert (await client.verifications(run.id))["items"][0]["method"] == "source"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        {
            "kind": "invoke",
            "capability": "workspace_command",
            "arguments": {"expected_revision": "r", "argv": ["python", "-c", "print(1)"], "commit": False},
        },
        {
            "kind": "assign",
            "assignments": [
                {
                    "role": "writer",
                    "objective": "Create part",
                    "criteria": [{"id": "part", "statement": "Create file"}],
                    "tools": ["workspace_write"],
                    "base_revision": "r",
                    "read_prefixes": ["part.txt"],
                    "write_prefixes": ["part.txt"],
                }
            ],
        },
    ],
)
async def test_private_model_envelope_decodes_general_actions(action):
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    from agent_runtime.general_contracts import StepDecision
    from agent_runtime.general_runtime import DecisionEnvelope

    agent = Agent(TestModel(custom_output_args={"action": action}), output_type=DecisionEnvelope, retries=0)
    result = await agent.run("Select the general action")
    decision = StepDecision.model_validate(result.output.model_dump())
    assert decision.action.kind == action["kind"]
