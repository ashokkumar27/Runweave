"""Versioned public contracts. No execution-framework types belong here."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentConfig(Contract):
    name: str = Field(min_length=1, max_length=100)
    provider: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")
    model: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")
    instructions: str = Field(default="Use tools when appropriate. Return a concise answer.", max_length=8000)
    tools: list[Literal["add", "record_note", "convert_temperature"]] = Field(
        default_factory=lambda: ["add"], max_length=3
    )
    max_requests: int = Field(default=6, ge=1, le=12)
    max_tool_calls: int = Field(default=6, ge=1, le=12)
    max_tokens: int = Field(default=1024, ge=128, le=4096)
    timeout_seconds: int = Field(default=120, ge=5, le=600)


class Agent(Contract):
    id: str
    config: AgentConfig


class Session(Contract):
    id: str
    created_at: datetime


class RunCreate(Contract):
    agent_id: str
    session_id: str | None = None
    input: str = Field(min_length=1, max_length=16000)


class Answer(Contract):
    answer: str = Field(max_length=16000)
    value: float | None = None


Status = Literal["queued", "running", "awaiting_approval", "completed", "failed", "cancelled"]


class Approval(Contract):
    id: str
    tool: str
    arguments: dict[str, Any]


class Run(Contract):
    id: str
    session_id: str
    agent_id: str
    config: AgentConfig
    status: Status
    output: Answer | None = None
    error: str | None = None
    approvals: list[Approval] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
    created_at: datetime


class Decision(Contract):
    approved: bool


class Event(Contract):
    id: int
    run_id: str
    type: str
    data: dict[str, Any]
    created_at: datetime
