# Independent Agents API

A self-hosted API for iterative tasks: turn instructions and context into authorized tool use, optional delegation, verification, and a result. Applications can submit work, follow its progress, and continue a session through the API, Python client, or CLI.

**Experimental; not production-ready.** Full live acceptance remains incomplete, and the existing test fixtures do not establish general reliability. See the [latest findings](docs/completion-models-findings.md) for known failures and limitations.

## Capabilities

- Durable run submission and session continuation, with idempotent submission retries.
- Ordered, persisted events that clients can replay over server-sent events (SSE).
- Tool permissions, approval decisions, cancellation, and bounded execution.
- Uploadable artifacts, downloadable results, and isolated project workspaces.
- Scoped delegation with shared resource limits and verification of integrated results.
- Completion checks against stored evidence for the current project revision.

The current scope supports one authenticated workspace with explicit provider selection. Multi-tenancy, automatic model routing, and arbitrary network or package access from generated code are outside that scope.

## Architecture

FastAPI exposes public Agent, Session, Run, and Event contracts. PostgreSQL stores application state and ordered events; a transactional outbox connects persisted submissions to workflow dispatch.

Temporal coordinates deterministic workflows and recovery. Model and tool I/O runs through activities, with PydanticAI behind private adapters. Public API schemas stay independent of both execution frameworks. Generated code executes in isolated containers under bounded permissions and resources.

## Start locally

From the root of a Git checkout, use a POSIX environment with Python **3.12–3.13**, **uv 0.11.12**, and Docker Compose with daemon access (or non-interactive `sudo -n docker`).

```bash
uv sync --frozen
test -e .env.local || cp .env.example .env.local
uv run python -m scripts.start_local
```

The startup wrapper preserves existing credentials and volumes, generates a missing app `API_KEY` and sandbox authentication, and waits for local services. Startup makes no model calls. Keep `.env.local` private; see [operations](docs/operations.md#startup-and-recovery) for credential handling and recovery.

API: **http://localhost:18000** · Interactive API docs: **http://localhost:18000/docs**.

## Try a scripted fake task

With local services running:

```bash
uv run --env-file .env.local python -m agent_runtime.cli readiness
uv run --env-file .env.local python -m agent_runtime.cli agent --tools add
# Replace AGENT_ID with the returned ID:
uv run --env-file .env.local python -m agent_runtime.cli submit AGENT_ID 'add 2 3' --key demo-1 --wait
```

The default `fake/deterministic` provider uses scripted actions to add two numbers without a paid model call. This demonstrates the submission and tool lifecycle, not general language autonomy.

Reuse the idempotency key only when retrying the same submission; use a new key for a new task. Readiness checks local dependencies but does not verify provider or MCP access.

## Documentation

- [Usage](docs/usage.md): Python/API examples, CLI commands, artifacts, and workspaces.
- [General runtime configuration](docs/usage.md#general-runtime-configuration): instructions, authorized tools, delegation, and completion checks.
- [Operations](docs/operations.md): provider setup, execution limits, recovery, and sandbox security.
- [Validation index](docs/validation-index.md): recorded checks, evidence, and limitations.
- [Current project plan](PLAN.md): scope, current state, and next priorities.

## Contributing

Read [AGENTS.md](AGENTS.md) for project conventions and [PLAN.md](PLAN.md) for current scope. Existing unpaid checks are documented under [local checks](docs/validation-index.md#local-checks) and in [CI](.github/workflows/ci.yml); they include linting, formatting, and fake-model tests. Integration checks require local services.

## License

License pending. No license file is included; the owner must choose a license before open-source publication.
