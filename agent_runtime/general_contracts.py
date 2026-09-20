"""Owned v3 contracts. Evidence authority is assigned by the server, never the model."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GeneralLimits(Contract):
    model_attempts: int = Field(default=12, ge=1, le=24)
    tool_attempts: int = Field(default=48, ge=2, le=96)
    total_tokens: int = Field(default=16000, ge=1024, le=16000)
    active_seconds: int = Field(default=600, ge=10, le=1800)
    command_attempts: int = Field(default=16, ge=2, le=16)
    files: int = Field(default=256, ge=1, le=256)
    file_bytes: int = Field(default=262144, ge=1, le=262144)
    revision_bytes: int = Field(default=4194304, ge=1, le=4194304)
    storage_bytes: int = Field(default=33554432, ge=1, le=33554432)
    revisions: int = Field(default=64, ge=1, le=64)


class ChildLimits(Contract):
    model_attempts: int = Field(default=4, ge=1, le=4)
    tool_attempts: int = Field(default=16, ge=1, le=16)
    command_attempts: int = Field(default=4, ge=1, le=4)
    active_seconds: int = Field(default=240, ge=10, le=240)
    total_tokens: int = Field(default=8000, ge=1024, le=16000)


class DelegationPolicy(Contract):
    tools: list[str] = Field(default_factory=list, max_length=16)
    max_children: int = Field(default=2, ge=1, le=2)
    max_simultaneous: int = Field(default=2, ge=1, le=2)
    depth: Literal[1] = 1
    limits: ChildLimits = Field(default_factory=ChildLimits)


class GeneralPolicy(Contract):
    schema_version: Literal[3] = 3
    limits: GeneralLimits = Field(default_factory=GeneralLimits)
    workspace_policy: Literal["python-project-v3"] = "python-project-v3"
    delegation: DelegationPolicy | None = None
    context_policy: Literal["bounded-v3"] = "bounded-v3"
    evidence_policy: Literal["scoped-v3"] = "scoped-v3"
    effect_policy: Literal["declared-v3"] = "declared-v3"


class CheckSpec(Contract):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    kind: Literal["command", "sha256", "bytes"]
    argv: list[str] = Field(default_factory=list, max_length=32)
    cwd: str = Field(default="", max_length=200)
    expected_exit: int = Field(default=0, ge=0, le=255)
    path: str | None = Field(default=None, max_length=200)
    expected: str | None = Field(default=None, max_length=350000)

    @model_validator(mode="after")
    def valid(self):
        if self.kind == "command" and (not self.argv or sum(len(x.encode()) for x in self.argv) > 4096):
            raise ValueError("Invalid command specification")
        if self.kind != "command" and (self.path is None or self.expected is None):
            raise ValueError("File assertion requires path and expected value")
        return self


class Criterion(Contract):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    statement: str = Field(min_length=1, max_length=512)
    required: bool = True
    evidence_policy: Literal["assessment", "source", "check"] = "assessment"
    checks: list[CheckSpec] = Field(default_factory=list, max_length=4)
    origin: Literal["user", "model", "runtime"] = "user"


class TaskGoal(Contract):
    outcome: str = Field(min_length=1, max_length=4000)
    constraints: list[Annotated[str, Field(max_length=512)]] = Field(default_factory=list, max_length=16)
    criteria: list[Criterion] = Field(min_length=1, max_length=12)
    assumptions: list[Annotated[str, Field(max_length=512)]] = Field(default_factory=list, max_length=8)
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError("Duplicate criterion IDs")
        ids = [s.id for c in self.criteria for s in c.checks]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate check IDs")
        return self


class WorkspaceAttachment(Contract):
    workspace_id: str
    revision_id: str


class PlanStep(Contract):
    description: str = Field(max_length=300)
    status: Literal["pending", "active", "done", "blocked"] = "pending"


class TaskState(Contract):
    version: int = 1
    goal_version: int = 1
    plan: list[PlanStep] = Field(default_factory=list, max_length=12)
    branch_id: str | None = None
    head: str | None = None
    unresolved: list[str] = Field(default_factory=list, max_length=13)
    blockers: list[Annotated[str, Field(max_length=300)]] = Field(default_factory=list, max_length=16)
    progress: dict[str, int] = Field(default_factory=dict)
    checkpoint_id: str | None = None


class VerificationResult(Contract):
    id: str
    criterion_id: str
    check_id: str | None = None
    outcome: Literal["pass", "fail", "inconclusive"]
    method: Literal["source", "command", "sha256", "bytes"]
    provenance: Literal["user", "runtime", "supporting"]
    operation_id: str
    goal_version: int
    branch_id: str
    revision_id: str
    spec_hash: str
    dependency_hash: str
    fresh: bool = True
    details: dict = Field(default_factory=dict)


class CriterionDisposition(Contract):
    criterion_id: str
    disposition: Literal["satisfied", "unsatisfied", "inconclusive"]
    assessment: str = Field(default="", max_length=512)
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)


class CompletionAssessment(Contract):
    proposal_id: str = Field(max_length=100)
    state_version: int
    goal_version: int
    revision_id: str | None = None
    criteria: list[CriterionDisposition] = Field(default_factory=list, max_length=13)
    remaining_gaps: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[Annotated[str, Field(max_length=512)]] = Field(default_factory=list, max_length=8)
    stop_reason: str | None = None
    accepted: bool = False


class FileInput(Contract):
    path: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(max_length=349528)


class WorkspaceCreate(Contract):
    files: list[FileInput] = Field(default_factory=list, max_length=256)


class EffectPolicy(Contract):
    kind: Literal["read", "local-write", "isolated-command", "external-write", "delegation"]
    domain: str
    approval: Literal["none", "required"] = "none"
    retry_safety: Literal["read", "transactional", "reconcile"] = "transactional"


class CapabilityDescriptor(Contract):
    alias: str
    registration_id: str
    description: str
    effect: EffectPolicy
    availability: Literal["available", "unverified"]
    arguments_schema: dict | None = None


class InvokeAction(Contract):
    kind: Literal["invoke"]
    capability: str
    arguments: dict = Field(default_factory=dict)


class DiscoverAction(Contract):
    kind: Literal["discover"]
    query: str = Field(default="", max_length=200)


class Assignment(Contract):
    role: str = Field(min_length=1, max_length=80)
    objective: str = Field(min_length=1, max_length=2000)
    criteria: list[Criterion] = Field(min_length=1, max_length=6)
    tools: list[str] = Field(max_length=16)
    artifact_ids: list[str] = Field(default_factory=list, max_length=8)
    read_prefixes: list[str] = Field(default_factory=lambda: [""], max_length=16)
    write_prefixes: list[str] = Field(default_factory=list, max_length=16)
    base_revision: str
    limits: ChildLimits = Field(default_factory=ChildLimits)


class AssignAction(Contract):
    kind: Literal["assign"]
    assignments: list[Assignment] = Field(min_length=1, max_length=2)


class JoinAction(Contract):
    kind: Literal["join"]
    child_ids: list[str] = Field(min_length=1, max_length=2)


class MergeAction(Contract):
    kind: Literal["merge"]
    child_id: str
    base_revision: str
    source_revision: str
    expected_revision: str


class CompleteAction(Contract):
    kind: Literal["complete"]
    answer: str = Field(max_length=16000)
    value: float | None = Field(default=None, allow_inf_nan=False)
    assessment: CompletionAssessment


class BlockedAction(Contract):
    kind: Literal["blocked"]
    reason: str = Field(max_length=300)


class StepDecision(Contract):
    goal_additions: list[Criterion] = Field(default_factory=list, max_length=6)
    plan: list[PlanStep] | None = Field(default=None, max_length=12)
    action: Annotated[
        InvokeAction
        | DiscoverAction
        | AssignAction
        | JoinAction
        | MergeAction
        | CompleteAction
        | BlockedAction,
        Field(discriminator="kind"),
    ]


class GoalSnapshot(TaskGoal):
    # The server may append one mandatory integration criterion to 12 caller criteria.
    criteria: list[Criterion] = Field(min_length=1, max_length=13)


class TaskSnapshot(Contract):
    goal: GoalSnapshot
    state: TaskState
    assessment: CompletionAssessment | None = None


class VerificationPage(Contract):
    items: list[VerificationResult] = Field(max_length=16)
    next_cursor: int | None = None


class ProjectFile(Contract):
    path: str
    sha256: str
    size_bytes: int


class ProjectManifest(Contract):
    workspace_id: str
    revision_id: str
    schema_version: Literal[3]
    parents: list[str] = Field(max_length=2)
    files: list[ProjectFile] = Field(max_length=256)


class CapabilityPage(Contract):
    items: list[CapabilityDescriptor] = Field(max_length=16)
    next_cursor: int | None = None
    policy: GeneralPolicy
    operator: dict


class OperationOutput(Contract):
    name: str
    sha256: str
    size_bytes: int


class FieldDiagnostic(Contract):
    type: str = Field(max_length=100)
    loc: list[str | int] = Field(max_length=16)


class OperationDiagnostics(Contract):
    message_bytes: int | None = Field(default=None, ge=0)
    output_reservation: int | None = Field(default=None, ge=0)
    required_reservation: int | None = Field(default=None, ge=0)
    validation_feedback: str | None = Field(default=None, max_length=512)
    output_calls: int | None = Field(default=None, ge=0)
    failure_type: str | None = Field(default=None, max_length=100)
    validation_errors: list[FieldDiagnostic] = Field(default_factory=list, max_length=16)
    response_shape: list = Field(default_factory=list, max_length=2)
    context_bytes: int | None = Field(default=None, ge=0)
    schema_bytes: int | None = Field(default=None, ge=0)


class OperationInspection(Contract):
    id: str
    status: Literal["pending", "complete", "failed", "outcome_unknown"]
    result: dict | None = None
    diagnostics: OperationDiagnostics = Field(default_factory=OperationDiagnostics)
    outputs: list[OperationOutput] = Field(default_factory=list)


class OperationPage(Contract):
    items: list[OperationInspection] = Field(max_length=16)
    next_cursor: int | None = None
