# Independent Agents API

Turn a user request, configuration, and context into a plan, authorized tool use, optional delegation, verification, and a result.

A self-hosted development tool for iterative task execution through an owned API. Supply instructions, tool permissions and context; the general runtime can plan, act, inspect results and revise its approach. Optional scoped subagents share bounded resources. Completion requires applicable verification evidence, not just a model's claim of success.

**Development build—not production-ready.** Latest live acceptance: **11/15**; Luna direct and all three parallel cases failed. These narrow fixtures do not establish general reliability. No production rollout was performed for the latest work. See [latest findings](docs/completion-models-findings.md) and the [validation index](docs/validation-index.md).

## Start locally

Requires Python **3.12–3.13**, **uv 0.11.12**, and Docker Compose with daemon access (or non-interactive `sudo -n docker`).

```bash
uv sync --frozen
test -e .env.local || cp .env.example .env.local
uv run python -m scripts.start_local
```

The wrapper preserves existing credentials and volumes, creates only a missing app `API_KEY`, and waits for local services. Startup makes no paid model call. Keep `.env.local` private.

API: **http://localhost:18000** · Interactive API docs: **http://localhost:18000/docs**.

## Try a scripted fake task

```bash
uv run --env-file .env.local python -m agent_runtime.cli readiness
uv run --env-file .env.local python -m agent_runtime.cli agent --tools add
# Replace AGENT_ID with the returned ID:
uv run --env-file .env.local python -m agent_runtime.cli submit AGENT_ID 'add 2 3' --key demo-1 --wait
```

The default `fake/deterministic` provider demonstrates scripted tasks; this example does **not** demonstrate general language autonomy. Reuse the key only when retrying the same submission; use a new key for a new task. Readiness observes local dependencies, not provider verification.

## Use and operate

- [Usage](docs/usage.md): Python/API examples, [general runtime configuration](docs/usage.md#general-runtime-configuration), workspaces, tools and delegation.
- [Operations](docs/operations.md): local development, provider setup, execution limits, recovery and sandbox security.
- [Validation index](docs/validation-index.md): current limitations, historical evidence and terminal campaign restrictions.
- [Current project plan](PLAN.md): objective, scope, latest state and next priorities.

FastAPI exposes the public contracts; PostgreSQL retains application state and events, Temporal coordinates workflows, and PydanticAI handles model activities. Public API schemas remain independent of execution frameworks. One authenticated workspace is supported; provider selection is explicit.
