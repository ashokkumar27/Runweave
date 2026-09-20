"""Operator-selected installed handlers. Metadata is validated and content-addressed."""

import hashlib
import json
from pathlib import Path

from pydantic import Field

from .config import settings
from .tool_contracts import DTO, TaskSpec, ToolDescriptor


class Add(DTO):
    a: float
    b: float


class Note(DTO):
    text: str = Field(max_length=8000)


class Temperature(DTO):
    celsius: float


class Read(DTO):
    artifact_id: str
    start_line: int = Field(default=1, ge=1)
    max_lines: int = Field(default=40, ge=1, le=100)
    path: str | None = Field(default=None, max_length=200)


class Search(DTO):
    artifact_id: str
    query: str = Field(min_length=1, max_length=200)


class Compare(DTO):
    left_id: str
    right_id: str


class Inspect(DTO):
    artifact_id: str


class Patch(DTO):
    artifact_id: str
    path: str = Field(max_length=200)
    old: str = Field(min_length=1, max_length=4000)
    new: str = Field(max_length=4000)


class Python(DTO):
    artifact_id: str
    code: str = Field(min_length=1, max_length=8000)


# Handler versions are retained in code; a registry may select only these deployments.
CATALOG = {
    "add": (Add, "read", "Add two numbers."),
    "record_note": (Note, "approval_write", "Record a note with exact user approval."),
    "convert_temperature": (Temperature, "read", "Convert Celsius through operator MCP."),
    "document_read": (Read, "read", "Read bounded original lines and verified source evidence."),
    "document_search": (Search, "read", "Find literal text in an uploaded document."),
    "document_compare": (
        Compare,
        "artifact_write",
        "Compare two uploaded documents; return line evidence and downloadable unified diff.",
    ),
    "csv_analyze": (
        Inspect,
        "artifact_write",
        "Analyze invoices CSV in isolated Python. Columns: invoice_id,amount. Deduplicate invoice_id, preserve first row; signed amount includes refunds. Return exact decimal net and cleaned CSV.",
    ),
    "python_analyze": (
        Python,
        "artifact_write",
        "Run Python in isolated backend. Input bytes: /input/data. Write UTF-8 result to /output/result (max 256 KiB); print concise JSON measurements. Standard library only, no network. Downloaded output is an artifact.",
    ),
    "repository_inspect": (Inspect, "read", "List bounded text files in uploaded repository ZIP."),
    "repository_read": (Read, "read", "Read repository path lines with verified evidence."),
    "repository_patch": (
        Patch,
        "artifact_write",
        "Generate downloadable unified patch replacing exactly one old string in a repository file. Never applies changes.",
    ),
    "delegate": (
        TaskSpec,
        "delegate",
        "Delegate a bounded independent task to a configured specialist with selected artifact IDs. At most two lifetime children, depth one. Calls may run in parallel per configuration.",
    ),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ToolRegistry:
    def __init__(self, entries=None):
        self.entries = {}
        for entry in (
            entries if entries is not None else json.loads(Path(settings().tool_registry_file).read_text())
        ):
            if set(entry) != {"alias", "handler", "version"} or entry["version"] != 1:
                raise ValueError("Unsupported tool registration")
            alias, handler = entry["alias"], entry["handler"]
            # Initial installed names deliberately fixed: aliases cannot bypass effect domains.
            if alias != handler or handler not in CATALOG or alias in self.entries:
                raise ValueError("Unsupported tool alias")
            schema, effect, description = CATALOG[handler]
            retained = {
                **entry,
                "arguments_schema": schema.model_json_schema(),
                "effect": effect,
                "description": description,
                "result_schema": {"type": "object"}
                if handler not in {"add", "convert_temperature", "record_note"}
                else {"type": "string" if handler == "record_note" else "number"},
            }
            self.entries[alias] = retained

    def select(self, aliases):
        if any(a not in self.entries for a in aliases):
            raise ValueError("Unknown operator tool")
        return {a: self.entries[a] for a in aliases}

    @staticmethod
    def descriptor(entry):
        return ToolDescriptor(
            alias=entry["alias"],
            registration_id=digest(entry),
            description=entry["description"],
            arguments_schema=entry["arguments_schema"],
            result_schema=entry["result_schema"],
            effect=entry["effect"],
            permissions=[entry["handler"]],
            requires_approval=entry["effect"] == "approval_write",
            availability="unverified"
            if entry["handler"] in {"csv_analyze", "python_analyze", "convert_temperature"}
            else "available",
        )

    @staticmethod
    def validate_snapshot(entry):
        installed = ToolRegistry(
            [{"alias": entry["alias"], "handler": entry["handler"], "version": entry["version"]}]
        ).entries[entry["alias"]]
        if installed != entry:
            raise ValueError("tool_registration_unavailable")
        return CATALOG[entry["handler"]][0]
