# Independent Agents API

A local MVP with FastAPI, PostgreSQL application state, Temporal workflows and PydanticAI activities. Public contracts live in `agent_runtime/schemas.py`; execution-framework messages remain private. No shell execution, sandbox, external deployment or automatic model routing.

## Run locally

Requires Python 3.12–3.13, uv 0.11.12 and Docker Compose. Tested with Python 3.13.3 and Docker 28.2.2. On this environment Docker requires `sudo -n docker`; use ordinary `docker` where your account has daemon access.

```bash
uv sync --frozen
test -e .env.local || cp .env.example .env.local
```

Set `API_KEY` in `.env.local` to your own long random API authentication key. Preserve any existing provider credential. Fake agents need no provider key. Compose loads the file; the Python application itself does not automatically read dotenv files.

```bash
docker compose --profile app up -d --build
```

API: `http://localhost:8000`, OpenAPI: `/docs`. If that port is occupied, use `API_PORT=18000 docker compose --profile app up -d --build`. `AGENTS_ENV_FILE` selects another env file. PostgreSQL, Temporal and MCP ports bind only to loopback. The Compose database password is for local development only. `docker compose --profile app stop` retains database volumes.

For host development, run the services, migrate, then run the API and worker in separate terminals:

```bash
docker compose up -d --build postgres temporal mcp
uv run python -m scripts.wait_services
uv run alembic upgrade head
uv run --env-file .env.local uvicorn agent_runtime.api:app --port 8000
uv run --env-file .env.local python -m agent_runtime.worker
```

The worker also dispatches committed outbox records. While it is stopped, accepted runs and approval/cancellation commands remain in PostgreSQL for later delivery. Keep PostgreSQL and Temporal data together when backing up or restoring. Drain/version workflows before incompatible changes to workflow code or activity names.

## API examples

Set `$API_KEY` to your local API authentication key and `$BASE` to `http://localhost:8000` (or your chosen port). Provider keys belong only in worker configuration, never in API requests.

```bash
curl -sS "$BASE/v1/agents" -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"name":"demo","provider":"fake","model":"deterministic","tools":["add","record_note","convert_temperature"]}'
```

Use the returned agent ID as `$AGENT_ID`:

```bash
curl -sS "$BASE/v1/runs" -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: example-1' \
  -d "{\"agent_id\":\"$AGENT_ID\",\"input\":\"add 2 and 3\"}"
curl -sS "$BASE/v1/runs/$RUN_ID" -H "Authorization: Bearer $API_KEY"
curl -N "$BASE/v1/runs/$RUN_ID/events" -H "Authorization: Bearer $API_KEY"
curl -N "$BASE/v1/runs/$RUN_ID/events" -H "Authorization: Bearer $API_KEY" -H 'Last-Event-ID: 2'
```

Set `$RUN_ID` from the run response. Events are ordered per run; reconnect with its last event ID or `?cursor=2`. SSE emits persisted lifecycle/tool events, not token deltas. Disconnecting does not cancel execution. Reusing an idempotency key with the same request returns the original run; different input returns 409.

Continue with a new idempotency key and the previous `session_id` in the run body. Only one active run per session is allowed (409 otherwise). Completed messages carry forward; failed/cancelled turns do not. Agent updates via `PUT /v1/agents/{id}` affect future runs only.

Submit `note:remember this` to the fake agent to request approval, then use the returned `approvals[0].id`:

```bash
curl -sS -X POST "$BASE/v1/runs/$RUN_ID/approvals/$APPROVAL_ID" \
  -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' -d '{"approved":true}'
curl -sS -X POST "$BASE/v1/runs/$RUN_ID/cancel" -H "Authorization: Bearer $API_KEY"
```

Approval decisions are immutable and replayable; `false` denies the tool. The approval wait counts against the run timeout. `temperature:100` exercises the real read-only MCP conversion service. The fake model supports these scripted demonstration tasks; it is not a general language model.

## Providers and bounds

Registered combinations: `fake/deterministic`, `openai/gpt-4.1-mini`, `anthropic/claude-haiku-4-5`. The two real provider adapters and opt-in smokes are implemented; successful live capability verification is pending. Missing worker credentials produce `provider_not_configured`. Unsupported model selections return 422.

Agent configuration bounds request/tool counts, per-response tokens and a 5–600 second execution budget. There are at most two Temporal attempts per model/tool activity, zero provider SDK retries, one validation retry, and a 16,000-token usage limit. Failed-attempt provider usage is not included in that total: these are execution bounds, not an exact billing cap. Session history is capped at 250 KB; oversized history fails explicitly. Global active-run admission defaults to 20.

The approved note effect and its event commit atomically under a stable call ID. Read-only MCP calls can safely retry. Other mutating connectors must supply upstream idempotency or a real reconciliation implementation before registration; arbitrary non-idempotent external writes are not exposed. Cancellation immediately closes application state and prevents subsequent note commits; Temporal cancellation is delivered through the outbox.

Telemetry is off by default. `OTEL_EXPORTER_OTLP_ENDPOINT` enables allowlisted run spans only; prompts, model responses, tool arguments, exception bodies and credentials are excluded. Worker diagnostic logging suppresses exception bodies. Application/Temporal history still contains task content and must be treated as private storage.

## Checks and validation

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run python -m scripts.wait_services
uv run alembic check
uv run pytest -q --integration
# Against an already running API, with API_KEY in the environment:
uv run python -m scripts.http_smoke --base-url http://localhost:8000
# Explicit live calls only; loads the authorized file in-process:
uv run python -m scripts.live_smoke --provider openai --load-local-env
uv run python -m scripts.live_smoke --provider anthropic --load-local-env
# Alternative: credentials already in the environment:
uv run pytest -q --live tests/test_live.py
```

Executed on 2026-09-13: lockfile sync, lint/format, migrations and schema drift check, Docker builds, full Compose startup on port 18000, HTTP smoke, and real PostgreSQL/Temporal/MCP tests. Default suite: **10 passed, 10 skipped** (8 service tests + 2 provider tests). With `--integration`: **18 passed, 2 skipped** (provider tests). Four arithmetic evaluation cases pass with typed tool calls and structured results; these measure deterministic plumbing, not live model quality.

Recovery coverage includes SIGKILL/restart while awaiting approval, replaying the recovered Temporal history, lost workflow-start acknowledgement, dispatch outage and closed-workflow reconciliation, failure after a tool effect commits, concurrent duplicate submissions, session admission, terminal-state races, cancellation/approval races, approval denial/timeout and request-budget exhaustion. Test schemas are isolated and removed afterward.

OpenAI smoke was attempted twice with SDK retries disabled; the diagnostic attempt returned **HTTP 401**. No live success is claimed. Anthropic was not called because no credential was supplied. Fix authentication before rerunning OpenAI; supply a second-provider credential before validating Anthropic. CI is checked in; hosted CI execution and external OTLP collector delivery were not run here.

Implementation decisions and milestone acceptance status are in [PLAN.md](PLAN.md). Current references: [PydanticAI Temporal capability](https://pydantic.dev/docs/ai/capabilities/durable_execution/temporal/), [MCP client](https://pydantic.dev/docs/ai/mcp/client/), [Temporal Python messages](https://docs.temporal.io/develop/python/workflows/message-passing), [OpenAI tools](https://developers.openai.com/api/docs/guides/tools).
