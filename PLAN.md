# Independent Agents API — current plan

## Objective

Build a self-hosted API that turns a user request, configuration and context into authorized tool use, optional delegation, verification and a result.

## Current scope

- One authenticated workspace with explicit provider/model selection, owned public contracts, and Python client/CLI access.
- Durable run submission, session continuation, ordered replayable SSE, approvals, cancellation and bounded execution.
- Tool discovery, artifacts, isolated project workspaces, iterative task state and evidence-based completion.
- Optional scoped specialists with separate context and branches: depth one, at most two lifetime children, shared root limits and integrated verification.
- Generated code runs in an isolated offline sandbox. External mutations require idempotency or reconciliation; repository results are downloadable, not external repository writes.
- Automatic model routing, multi-tenancy, dashboards, recursive delegation and arbitrary network/package access from generated code remain outside this scope.

## Architecture

FastAPI exposes framework-independent Agent, Session, Run and Event contracts. PostgreSQL stores application state, immutable configuration snapshots, projects and ordered events; a transactional outbox bridges durable submission and workflow dispatch.

Temporal coordinates deterministic workflows and recovery. PydanticAI sits behind private adapters; model and tool I/O executes through activities. Root-owned budgets and policy apply across retries, approvals and children. Completion checks server-stored evidence against the current project revision.

The sandbox broker executes bounded commands in disposable containers reconstructed from committed revisions. Credentials stay out of public events, traces and generated-code environments.

## Latest state — 2026-09-20

**Development build; not production-ready.** The lifecycle, toolkit and general-runtime flows above are implemented, but full live acceptance remains incomplete.

Latest held-code live acceptance improved from **1/15 to 11/15**. **Luna direct and all three parallel cases remain incomplete.** Repeated actions, pending-check uncertainty and local/shared reservation limits remain documented failure causes. Narrow fixture results do not establish general reliability.

Final SDK/backend preflight passed 15/15 fake cells. A broad unpaid service run passed 220 tests with two paid skips before final payload compaction; later affected/replay checks passed. These are recorded results, not checks rerun for this documentation update. No production rollout was performed for the latest work.

See [completion model findings](docs/completion-models-findings.md) for exact matrices and limitations, and the [validation index](docs/validation-index.md) for checks, evidence and terminal campaign restrictions.

## Next priorities

- Reduce redundant actions and distinguish pending verification from genuine uncertainty.
- Compact child context and investigate reservation headroom while preserving shared limits, authorization and completion evidence requirements.
- Validate corrections with fake models and focused recovery/replay checks; any new paid evaluation requires separate authorization. Existing terminal campaigns and unused allowances authorize no new calls.
- Establish the remaining live acceptance and deployment-readiness evidence before claiming reliability or production readiness.

## Documentation

- [AGENTS.md](AGENTS.md): concise development, model and security rules.
- [README.md](README.md): setup and entry points to usage and operations.
- [Historical plan through 2026-09-20](docs/history/plan-through-2026-09-20.md): complete prior scope, decisions and outcomes; historical approvals are not current authorization.
