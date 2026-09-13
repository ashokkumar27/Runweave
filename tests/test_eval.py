import json
from pathlib import Path

import pytest
from pydantic_ai import DeferredToolRequests

from agent_runtime.runtime import Deps, agent
from agent_runtime.schemas import AgentConfig, RunCreate

CASES = json.loads((Path(__file__).parent / "eval_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
async def test_fake_evaluation(store, case):
    saved = await store.agent(AgentConfig(name="eval", provider="fake", model="deterministic"))
    run = await store.submit(RunCreate(agent_id=saved.id, input=case["prompt"]), case["name"])
    result = await agent.run(case["prompt"], deps=Deps(run.id, ["add"]))
    assert not isinstance(result.output, DeferredToolRequests)
    assert result.output.value == case["value"]
    assert result.usage.tool_calls == 1
