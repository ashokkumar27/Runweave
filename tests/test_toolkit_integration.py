import asyncio
import json

import httpx
import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from temporalio.client import Client as TemporalClient
from temporalio.worker import Worker

from agent_runtime.activities import ACTIVITIES
from agent_runtime.api import create_app
from agent_runtime.client import Client
from agent_runtime.dispatch import Dispatcher
from agent_runtime.schemas import AgentConfig
from agent_runtime.tool_contracts import SubagentSpec
from agent_runtime.toolkit_runtime import toolkit_child, toolkit_state, toolkit_step, toolkit_tool
from agent_runtime.toolkit_workflow import ToolkitWorkflow
from agent_runtime.workflow import RunWorkflow

pytestmark = pytest.mark.integration


def config(**kw):
    return AgentConfig(name="integration", provider="fake", model="deterministic", max_tokens=512, **kw)


def task(tool, **arguments):
    return "toolkit:" + json.dumps([{"tool": tool, "arguments": arguments}])


async def test_parallel_children_public_api_and_shared_budget(pg_store):
    temporal = await TemporalClient.connect("localhost:7233", plugins=[PydanticAIPlugin()])
    queue = pg_store.test_schema
    async with Worker(
        temporal,
        task_queue=queue,
        workflows=[RunWorkflow, ToolkitWorkflow],
        activities=ACTIVITIES + [toolkit_child, toolkit_state, toolkit_step, toolkit_tool],
    ):
        dispatcher = asyncio.create_task(Dispatcher(pg_store, temporal, queue).run())
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_app(pg_store, "test")),
                base_url="http://test",
                headers={"Authorization": "Bearer test"},
            ) as http:
                async with Client(http_client=http) as client:
                    a = await client.upload(b"Policy: 30 days\n", filename="a.txt")
                    b = await client.upload(b"Policy: 60 days\n", filename="b.txt")
                    spec = await client.create_agent(config(tools=["document_read"]))
                    parent = await client.create_agent(
                        config(
                            tools=["delegate"],
                            subagents=[
                                SubagentSpec(name="a", agent_id=spec.id, description="a"),
                                SubagentSpec(name="b", agent_id=spec.id, description="b"),
                            ],
                        )
                    )
                    prompt = "toolkit:" + json.dumps(
                        [
                            {
                                "tool": "delegate",
                                "arguments": {
                                    "specialist": name,
                                    "instruction": task("document_read", artifact_id=ref.id),
                                    "artifact_ids": [ref.id],
                                },
                            }
                            for name, ref in [("a", a), ("b", b)]
                        ]
                    )
                    root = await client.submit(parent.id, prompt, artifact_ids=[a.id, b.id])
                    result = await client.wait(root.id, timeout=40)
                    assert result.status == "completed", result.error
                    children = await client.children(root.id)
                    assert len(children) == 2 and all(c.status == "completed" for c in children)
                    assert all(c.session_id is None and c.task_result.evidence for c in children)
                    budget = await client.budget(root.id)
                    assert budget["requests"] == 6 and budget["tool_calls"] == 4
                    events = [e async for e in client.watch(root.id)]
                    assert sum(e.type == "child.completed" for e in events) == 2
                    assert len({e.id for e in events}) == len(events)
                    for child in children:
                        desc = await temporal.get_workflow_handle("run:" + child.id).describe()
                        assert desc.parent_id == "run:" + root.id
        finally:
            dispatcher.cancel()
            await asyncio.gather(dispatcher, return_exceptions=True)


async def test_root_budget_contention_and_uncertain_reservations(pg_store):
    from agent_runtime.schemas import RunCreate

    agent = await pg_store.agent(config(max_requests=2, max_total_tokens=10000))
    run = await pg_store.submit(RunCreate(agent_id=agent.id, input="budget"), "budget")
    results = await asyncio.gather(
        *(pg_store.reserve_usage(run.id, "requests", 1000) for _ in range(8)), return_exceptions=True
    )
    assert sum(r is None for r in results) == 2
    budget = await pg_store.budget(run.id)
    assert budget["requests"] == 2 and budget["reserved_tokens"] == 2000
    await pg_store.reconcile_usage(run.id, 1000, 100)
    assert (await pg_store.budget(run.id))["reserved_tokens"] == 1000


async def test_child_approval_denial_and_restart(pg_store):
    temporal = await TemporalClient.connect("localhost:7233", plugins=[PydanticAIPlugin()])
    queue = pg_store.test_schema
    activities = ACTIVITIES + [toolkit_child, toolkit_state, toolkit_step, toolkit_tool]
    dispatcher = asyncio.create_task(Dispatcher(pg_store, temporal, queue).run())
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(pg_store, "test")),
            base_url="http://test",
            headers={"Authorization": "Bearer test"},
        ) as http:
            async with Client(http_client=http) as client:
                spec = await client.create_agent(config(tools=["record_note"]))
                with pytest.raises(Exception):
                    await client.create_agent(
                        config(
                            tools=["delegate"],
                            subagents=[SubagentSpec(name="note", agent_id=spec.id, description="note")],
                        )
                    )
                parent = await client.create_agent(
                    config(
                        tools=["delegate"],
                        delegation_mode="sequential",
                        subagents=[SubagentSpec(name="note", agent_id=spec.id, description="note")],
                    )
                )
                prompt = task(
                    "delegate",
                    specialist="note",
                    instruction=task("record_note", text="synthetic denied"),
                    artifact_ids=[],
                )
                async with Worker(
                    temporal,
                    task_queue=queue,
                    workflows=[RunWorkflow, ToolkitWorkflow],
                    activities=activities,
                ):
                    root = await client.submit(parent.id, prompt)
                    pending = await client.wait(root.id, timeout=30)
                    assert pending.status == "awaiting_approval"
                    children = await client.children(root.id)
                    assert pending.approvals[0].origin_run_id == children[0].id
                await client.decide(root.id, pending.approvals[0].id, False)
                async with Worker(
                    temporal,
                    task_queue=queue,
                    workflows=[RunWorkflow, ToolkitWorkflow],
                    activities=activities,
                ):
                    result = await client.wait(root.id, timeout=30, stop_at_approval=False)
                    assert result.status == "completed", result.error
                    assert await client.effects(root.id) == []
                    assert (await pg_store.toolkit(root.id))["denied"] is True
    finally:
        dispatcher.cancel()
        await asyncio.gather(dispatcher, return_exceptions=True)


async def test_sandbox_exact_bytes_and_boundaries_public_api(pg_store, monkeypatch):
    monkeypatch.setenv("SANDBOX_BROKER_URL", "http://localhost:18091")
    monkeypatch.setenv("SANDBOX_BROKER_KEY", "v3-isolated-test-only")
    temporal = await TemporalClient.connect("localhost:7233", plugins=[PydanticAIPlugin()])
    queue = pg_store.test_schema
    async with Worker(
        temporal,
        task_queue=queue,
        workflows=[RunWorkflow, ToolkitWorkflow],
        activities=ACTIVITIES + [toolkit_child, toolkit_state, toolkit_step, toolkit_tool],
    ):
        dispatcher = asyncio.create_task(Dispatcher(pg_store, temporal, queue).run())
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_app(pg_store, "test")),
                base_url="http://test",
                headers={"Authorization": "Bearer test"},
            ) as http:
                async with Client(http_client=http) as client:
                    data = await client.upload(
                        b"invoice_id,amount\na,10.00\na,10.00\nb,-2.00\n",
                        media_type="text/csv",
                        filename="invoices.csv",
                    )
                    agent = await client.create_agent(config(tools=["csv_analyze", "python_analyze"]))
                    root = await client.submit(
                        agent.id, task("csv_analyze", artifact_id=data.id), artifact_ids=[data.id]
                    )
                    result = await client.wait(root.id, timeout=40)
                    assert result.status == "completed" and len(result.artifacts) == 1
                    assert (
                        await client.download(
                            result.artifacts[0]["id"]
                            if isinstance(result.artifacts[0], dict)
                            else result.artifacts[0].id
                        )
                        == b"invoice_id,amount\na,10.00\nb,-2.00\n"
                    )
                    code = """import os,socket,json,pathlib
assert os.getuid()==65534
assert not any('KEY' in k for k in os.environ)
assert not pathlib.Path('/var/run/docker.sock').exists()
assert not pathlib.Path('/home/ubuntu/agent_runtime').exists()
try: open('/input/data','w'); raise AssertionError('writable input')
except PermissionError: pass
try: os.kill(1,9); raise AssertionError('supervisor kill permitted')
except PermissionError: pass
s=socket.socket();s.settimeout(.2)
try: s.connect(('1.1.1.1',443));raise AssertionError('network available')
except OSError: pass
open('/output/result','w').write('isolated')
"""
                    root = await client.submit(
                        agent.id,
                        task("python_analyze", artifact_id=data.id, code=code),
                        artifact_ids=[data.id],
                    )
                    result = await client.wait(root.id, timeout=40)
                    assert result.status == "completed" and len(result.artifacts) == 1, result.output
                    assert (
                        await client.download(
                            result.artifacts[0]["id"]
                            if isinstance(result.artifacts[0], dict)
                            else result.artifacts[0].id
                        )
                        == b"isolated"
                    )
        finally:
            dispatcher.cancel()
            await asyncio.gather(dispatcher, return_exceptions=True)


async def test_cancel_during_child_sandbox_fences_artifacts(pg_store, monkeypatch):
    monkeypatch.setenv("SANDBOX_BROKER_URL", "http://localhost:18091")
    monkeypatch.setenv("SANDBOX_BROKER_KEY", "v3-isolated-test-only")
    temporal = await TemporalClient.connect("localhost:7233", plugins=[PydanticAIPlugin()])
    queue = pg_store.test_schema
    async with Worker(
        temporal,
        task_queue=queue,
        workflows=[RunWorkflow, ToolkitWorkflow],
        activities=ACTIVITIES + [toolkit_child, toolkit_state, toolkit_step, toolkit_tool],
    ):
        dispatcher = asyncio.create_task(Dispatcher(pg_store, temporal, queue).run())
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_app(pg_store, "test")),
                base_url="http://test",
                headers={"Authorization": "Bearer test"},
            ) as http:
                async with Client(http_client=http) as client:
                    data = await client.upload(b"input")
                    spec = await client.create_agent(config(tools=["python_analyze"]))
                    parent = await client.create_agent(
                        config(
                            tools=["delegate"],
                            subagents=[SubagentSpec(name="slow", agent_id=spec.id, description="slow")],
                        )
                    )
                    instruction = task(
                        "python_analyze",
                        artifact_id=data.id,
                        code="import time\ntime.sleep(5)\nopen('/output/result','w').write('late')",
                    )
                    root = await client.submit(
                        parent.id,
                        task("delegate", specialist="slow", instruction=instruction, artifact_ids=[data.id]),
                        artifact_ids=[data.id],
                    )
                    async with asyncio.timeout(20):
                        while (await client.budget(root.id))["tool_calls"] < 2:
                            await asyncio.sleep(0.1)
                    await client.cancel(root.id)
                    await asyncio.sleep(6)
                    assert (await client.get(root.id)).status == "cancelled"
                    assert all(c.status == "cancelled" for c in await client.children(root.id))
                    assert await client.effects(root.id) == []
                    assert (await client.budget(root.id))["requests"] == 2
        finally:
            dispatcher.cancel()
            await asyncio.gather(dispatcher, return_exceptions=True)


@pytest.mark.parametrize(
    "code",
    [
        "import os\nos.symlink('/input/data','/output/result')",
        "print('x'*20000)\nopen('/output/result','w').write('bad')",
        "x=bytearray(300*1024*1024)\nopen('/output/result','w').write('bad')",
        "while True: pass",
        "import os\nwhile True: os.fork()",
    ],
)
async def test_sandbox_resource_and_link_rejection(pg_store, monkeypatch, code):
    monkeypatch.setenv("SANDBOX_BROKER_URL", "http://localhost:18091")
    monkeypatch.setenv("SANDBOX_BROKER_KEY", "v3-isolated-test-only")
    temporal = await TemporalClient.connect("localhost:7233", plugins=[PydanticAIPlugin()])
    queue = pg_store.test_schema
    async with Worker(
        temporal,
        task_queue=queue,
        workflows=[RunWorkflow, ToolkitWorkflow],
        activities=ACTIVITIES + [toolkit_child, toolkit_state, toolkit_step, toolkit_tool],
    ):
        dispatcher = asyncio.create_task(Dispatcher(pg_store, temporal, queue).run())
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_app(pg_store, "test")),
                base_url="http://test",
                headers={"Authorization": "Bearer test"},
            ) as http:
                async with Client(http_client=http) as client:
                    data = await client.upload(b"input")
                    agent = await client.create_agent(config(tools=["python_analyze"]))
                    root = await client.submit(
                        agent.id,
                        task("python_analyze", artifact_id=data.id, code=code),
                        artifact_ids=[data.id],
                    )
                    result = await client.wait(root.id, timeout=40)
                    assert result.status == "completed"
                    assert result.artifacts == []
                    assert "sandbox_" in result.output.answer
                    assert await client.effects(root.id) == []
        finally:
            dispatcher.cancel()
            await asyncio.gather(dispatcher, return_exceptions=True)


async def test_completed_sandbox_retry_survives_admission_expiry(monkeypatch):
    import time
    from uuid import uuid4

    from agent_runtime.sandbox import run_python

    monkeypatch.setenv("SANDBOX_BROKER_URL", "http://localhost:18091")
    monkeypatch.setenv("SANDBOX_BROKER_KEY", "v3-isolated-test-only")
    operation = str(uuid4())
    deadline = time.time() + 2
    code = "import time\ntime.sleep(3)\nopen('/output/result','w').write('cached')"
    first = await run_python(operation, code, b"", deadline=deadline)
    assert time.time() > deadline
    second = await run_python(operation, code, b"", deadline=deadline)
    assert first == second and first[0] == b"cached"
