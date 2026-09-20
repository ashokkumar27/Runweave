"""Real SDK/semantic adapter and reservation path; in-memory Responses transport only."""

import asyncio
import json
import os
from pathlib import Path

import httpx
from pydantic_ai.messages import ModelMessagesTypeAdapter

from agent_runtime import general_runtime, model_adapter
from agent_runtime.worker import main
from scripts.lightweight_budget import Transport
from scripts.lightweight_fixtures import actions

comparison = os.environ.get("ACCEPTANCE_CAMPAIGN") == "lightweight-model-comparison-v1"
if comparison:
    from scripts.model_comparison_budget import Transport

if os.environ.get("ACCEPTANCE_CAMPAIGN", "").startswith("completion-models-"):
    from scripts.completion_loop_fixtures import actions
    from scripts.completion_models_budget import profile

    comparison = True
    Transport = profile(os.environ["ACCEPTANCE_CAMPAIGN"]).Transport

if os.environ.get("ACCEPTANCE_CAMPAIGN") == "completion-loop-v1":
    from scripts.completion_loop_budget import Transport
    from scripts.completion_loop_fixtures import actions

assert os.environ["DATABASE_SCHEMA"].startswith("light_")
assert os.environ["OPENAI_API_KEY"] == "offline-sdk-stub"
counts = {}


async def respond(request):
    context = model_adapter.request_context.get()
    body = json.loads(await request.aread())
    rid = context["run_id"]
    ordinal = counts.get(rid, 0)
    counts[rid] = ordinal + 1
    child = None
    if rid != context["root_id"]:
        raw = json.dumps(body["input"])
        child = "left.txt" if "left.txt" in raw else "right.txt"
    action = actions(context["scenario"], child)[ordinal]
    arguments = json.dumps({"action": action})
    # Approximate nonzero SDK usage, never fabricate a zero-token preflight.
    usage = {
        "input_tokens": (len(json.dumps(body).encode()) + 3) // 4,
        "output_tokens": (len(arguments.encode()) + 3) // 4,
    }
    usage["total_tokens"] = sum(usage.values())
    with Path(os.environ["LIGHT_STUB_LOG"]).open("a") as f:
        f.write(
            json.dumps(
                {
                    **context,
                    "ordinal": ordinal,
                    "body_bytes": len(json.dumps(body).encode()),
                    "action": action,
                    "usage": usage,
                }
            )
            + "\n"
        )
    await asyncio.sleep(0.15)  # Permit simultaneous child reservation attempts.
    return httpx.Response(
        200,
        json={
            "id": "resp_offline",
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "model": body["model"],
            "output": [
                {
                    "type": "function_call",
                    "id": "fc_offline",
                    "call_id": "call_offline",
                    "name": body["tools"][0]["name"],
                    "arguments": arguments,
                    "status": "completed",
                }
            ],
            "usage": usage,
        },
    )


def factory(registration):
    return httpx.AsyncClient(
        transport=(
            Transport(os.environ["ACCEPTANCE_BUDGET_FILE"], registration.model, httpx.MockTransport(respond))
            if comparison
            else Transport(os.environ["ACCEPTANCE_BUDGET_FILE"], httpx.MockTransport(respond))
        ),
        trust_env=False,
    )


original_request = general_runtime.GeneralModel.request


async def measured_request(self, messages, model_settings, parameters):
    from agent_runtime.general_semantic import compact_schema

    definitions = [
        compact_schema(t.parameters_json_schema, minimal=getattr(self, "semantic_version", 0) >= 3)
        if self.reject_multiple
        else t.parameters_json_schema
        for t in parameters.output_tools
    ]
    context_bytes = len(ModelMessagesTypeAdapter.dump_json(messages)) + len(
        json.dumps(definitions, separators=(",", ":")).encode()
    )
    record = {
        "run_id": self.run_id,
        "operation_id": self.op_id,
        "context_bytes": context_bytes,
        "required_reservation": context_bytes + self.output + 512,
    }
    try:
        result = await original_request(self, messages, model_settings, parameters)
        record["outcome"] = "settled"
        return result
    except Exception as exc:
        record["outcome"] = getattr(exc, "detail", type(exc).__name__)
        raise
    finally:
        with Path(os.environ["LIGHT_STUB_LOG"] + ".reservations").open("a") as f:
            f.write(json.dumps(record) + "\n")


general_runtime.GeneralModel.request = measured_request
model_adapter.http_client_factory = factory
asyncio.run(main())
