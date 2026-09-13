"""Private PydanticAI adapter; framework messages never enter the public API."""

import re
from dataclasses import dataclass
from datetime import timedelta

from fastmcp import Client
from pydantic_ai import Agent, DeferredToolRequests, RunContext
from pydantic_ai.capabilities import ResolveModelId
from pydantic_ai.durable_exec.temporal import TemporalDurability
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.toolsets import FunctionToolset
from temporalio import workflow
from temporalio.common import RetryPolicy

from .config import settings
from .db import Database
from .model_adapter import SelectionModel, build_model
from .schemas import Answer
from .store import Store


@dataclass
class Deps:
    run_id: str
    tools: list[str]


_store: Store | None = None


def configure_store(store: Store):
    global _store
    _store = store


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store(Database(settings().database_url, settings().database_schema))
    return _store


async def fake_response(messages, info):
    """A scripted test model, not an imitation of a live provider result."""
    parts = [part for message in messages for part in message.parts]
    latest = 0
    prompt = ""
    for index, part in enumerate(parts):
        if isinstance(part, UserPromptPart):
            latest, prompt = index, str(part.content)
    returns = [p for p in parts[latest + 1 :] if isinstance(p, ToolReturnPart)]
    if returns:
        value = returns[-1].content
        result = {"answer": str(value), "value": value if isinstance(value, (int, float)) else None}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, result)])
    available = {t.name for t in info.function_tools}
    if prompt.startswith("note:") and "record_note" in available:
        call = ToolCallPart("record_note", {"text": prompt[5:].strip()})
    elif prompt.startswith("temperature:") and "convert_temperature" in available:
        call = ToolCallPart("convert_temperature", {"celsius": float(prompt.split(":")[1])})
    elif prompt == "previous":
        previous = [
            p.content for p in parts[:latest] if isinstance(p, ToolReturnPart) and p.tool_name == "add"
        ]
        value = previous[-1] if previous else None
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"answer": str(value), "value": value})]
        )
    elif "add" in available and len(numbers := re.findall(r"-?\d+(?:\.\d+)?", prompt)) >= 2:
        call = ToolCallPart("add", {"a": float(numbers[0]), "b": float(numbers[1])})
    else:
        return ModelResponse(
            parts=[
                ToolCallPart(info.output_tools[0].name, {"answer": "No matching test task", "value": None})
            ]
        )
    return ModelResponse(parts=[call])


async def prepare(ctx: RunContext[Deps], definition):
    return definition if definition.name in ctx.deps.tools else None


toolset = FunctionToolset(id="builtin-v1")


@toolset.tool(prepare=prepare)
async def add(ctx: RunContext[Deps], a: float, b: float) -> float:
    """Add two numbers."""
    await get_store().tool_event(ctx.deps.run_id, ctx.tool_call_id, "add", "started")
    value = a + b
    await get_store().tool_event(ctx.deps.run_id, ctx.tool_call_id, "add", "completed")
    return value


@toolset.tool(prepare=prepare, requires_approval=True)
async def record_note(ctx: RunContext[Deps], text: str) -> str:
    """Persist a note after the user approves this exact call."""
    if len(text) > 8000:
        raise ValueError("Note too large")
    await get_store().tool_event(ctx.deps.run_id, ctx.tool_call_id, "record_note", "started")
    result = await get_store().record_note(ctx.deps.run_id, ctx.tool_call_id, text)
    await get_store().tool_event(ctx.deps.run_id, ctx.tool_call_id, "record_note", "completed")
    return result


@toolset.tool(prepare=prepare)
async def convert_temperature(ctx: RunContext[Deps], celsius: float) -> float:
    """Convert Celsius to Fahrenheit using the configured read-only MCP service."""
    await get_store().tool_event(ctx.deps.run_id, ctx.tool_call_id, "convert_temperature", "started")
    # Endpoint is operator configuration, never model/user supplied (no arbitrary URL access).
    async with Client(settings().mcp_url, timeout=10) as client:
        result = await client.call_tool("convert_temperature", {"celsius": celsius}, timeout=10)
        value = float(result.data)
    await get_store().tool_event(ctx.deps.run_id, ctx.tool_call_id, "convert_temperature", "completed")
    return value


fake_model = FunctionModel(fake_response)


async def resolve_registration(ctx, model_id):
    if not model_id.startswith("registry:") or len(model_id) != 73:
        raise ValueError("Unknown registration selection")
    identity = model_id.split(":", 1)[1]
    if workflow.in_workflow():
        return SelectionModel(identity)
    registration = await get_store().registration(identity)
    return build_model(registration)


agent = Agent(
    fake_model,
    name="runtime-v1",
    deps_type=Deps,
    output_type=Answer | DeferredToolRequests,
    toolsets=[toolset],
    retries=1,
    capabilities=[
        ResolveModelId(resolve_registration),
        TemporalDurability(
            activity_config={
                "start_to_close_timeout": timedelta(seconds=45),
                "schedule_to_close_timeout": timedelta(seconds=100),
                "heartbeat_timeout": timedelta(seconds=10),
                "retry_policy": RetryPolicy(maximum_attempts=2),
            },
        ),
    ],
)
