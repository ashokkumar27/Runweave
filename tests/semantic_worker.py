"""Owned integration worker: fake registration and in-process SDK response only."""

import asyncio
import os

import pydantic_ai.models
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

import agent_runtime.general_runtime as adapter
from agent_runtime.worker import main

assert os.environ["DATABASE_SCHEMA"].startswith("test_")
assert os.environ["TASK_QUEUE"].startswith("test_")
pydantic_ai.models.ALLOW_MODEL_REQUESTS = False


async def response(messages, info):
    return ModelResponse(
        parts=[
            ToolCallPart(
                info.output_tools[0].name,
                {
                    "action": {
                        "kind": "complete",
                        "answer": "Checked",
                        "assessments": [
                            {
                                "criterion": "c0",
                                "disposition": "satisfied",
                                "assessment": "Registered verification.",
                            }
                        ],
                    }
                },
            )
        ]
    )


def build(registration):
    assert registration.adapter == "fake"
    return FunctionModel(response)


adapter.build_model = build
asyncio.run(main())
