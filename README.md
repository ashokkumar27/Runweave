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

Approval decisions are immutable and replayable; `false` denies the tool. Approval waiting pauses the active execution budget. The separate total approval allowance is shared across all approval rounds. `temperature:100` exercises the real read-only MCP conversion service. The fake model supports these scripted demonstration tasks; it is not a general language model.

## Providers and bounds

`MODEL_REGISTRY_FILE` selects an operator JSON registry (default `config/models.json`). API and worker validate it at startup. The supplied aliases are `fake/deterministic`, `openai/gpt-4.1-mini` (Responses), and `anthropic/claude-haiku-4-5`. Add models under any provider alias by adding entries; no code changes are needed. Public `provider` and `model` remain aliases. Private `upstream_model` accepts namespaced names.

For an OpenAI-compatible Chat Completions backend, an entry looks like:

```json
{"provider":"local","model":"small","adapter":"openai_chat","upstream_model":"org/model-v1","endpoint":"http://backend:8080/v1","auth":"none","credential_env":null,"tool_calling":true,"max_output_tokens":2048,"total_tokens_limit":16000}
```

Every entry requires an explicit endpoint/authentication mode and capability/token limits; fake entries use a null endpoint. `auth: "env"` requires `credential_env` naming the worker environment variable, never a credential value. Responses and Anthropic require this mode. Chat Completions also permits `auth: "none"`: it sends no authorization header and does not inherit the OpenAI credential. Endpoints cannot contain userinfo, query parameters or fragments. Mount the same operator registry into API and worker and set `MODEL_REGISTRY_FILE` to its container path, or edit `config/models.json` and rebuild. Restart processes after configuration changes.

Agent creation/update and new-run submission reject unknown aliases, missing tool-calling support, and output limits exceeding the registration with 422. The typed-answer flow uses tool calling; no adapter silently switches output modes or models. Missing required worker credentials fail with sanitized `provider_not_configured`. Live provider capability verification remains pending.

Each submitted run pins a content-derived registration identity, retained with its private configuration in PostgreSQL. Alias edits/removals affect only new submissions. Workers resolve queued/resumed runs from the retained registration, including after restart; do not delete referenced registrations or repoint their credential variable to a different backend. Secrets are never persisted in registrations. Back up registration rows with runs; connection configuration is absent from public contracts, events and operational traces.

`timeout_seconds` is a cumulative 5–600 second **active execution budget**, including storage/model/tool execution and retries across every resume. Only the durable approval wait pauses it. `APPROVAL_WAIT_SECONDS` is the operator's finite **total approval allowance** per run (default 86400; range 1–604800), snapshotted at submission and consumed across all approval rounds. Active exhaustion produces `run_timeout`; approval exhaustion produces `approval_timeout`. Expiry wins if an approval signal and deadline share the same Temporal timestamp. The Temporal execution timeout is the sum of both snapshotted budgets plus 180 seconds of bounded startup/finalization headroom; delayed or unexpectedly closed workflows are reconciled to application state.

Drain existing runs before migration `0002`; it refuses an upgrade with active legacy runs. Drain/version workflows before deploying this timer change or any incompatible workflow change. A restart of an unchanged workflow version replays both cumulative budgets without replenishing them.

Agent configuration also bounds request/tool counts and response tokens. There are at most two Temporal attempts per model/tool activity, zero provider SDK retries and one validation retry. The registration sets the cumulative token usage limit (16000 for supplied entries). Failed-attempt provider usage is not included in that total: these are execution bounds, not an exact billing cap. Session history is capped at 250 KB; oversized history fails explicitly. Global active-run admission defaults to 20.

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
# Future live acceptance only, after authentication is resolved and calls are authorized:
uv run python -m scripts.live_smoke --provider openai --load-local-env
uv run python -m scripts.live_smoke --provider anthropic --load-local-env
# Alternative: credentials already in the environment:
uv run pytest -q --live tests/test_live.py
```

Executed on 2026-09-13: lockfile sync, lint/format, migrations and schema drift check, Docker builds, full Compose startup on port 18000, HTTP smoke, and real PostgreSQL/Temporal/MCP tests. Default suite: **24 passed, 14 skipped** (12 service tests + 2 provider tests). With `--integration`: **36 passed, 2 skipped** (provider tests). Four arithmetic evaluation cases pass with typed tool calls and structured results; these measure deterministic plumbing, not live model quality.

Recovery coverage includes SIGKILL/restart after three hours of approval waiting, immutable model selection across registry edits, replaying recovered Temporal history, cumulative active/approval/request budgets across resumes, retried resume activity timeout classification, lost workflow-start acknowledgement, dispatch outage and closed-workflow reconciliation, failure after a tool effect commits, concurrent duplicate submissions, session admission, terminal-state races, cancellation/approval races, approval denial/timeout and request-budget exhaustion. Test schemas are isolated and removed afterward. The hours-long tests use an isolated Temporal time-skipping server with real PostgreSQL; its hard-restart worker disables sticky caching to force replay because that server cannot recover stale sticky routing after a clock jump. The real Temporal hard-restart variant retains normal production caching. Registry tests use mocked HTTP transport, including explicit and absent authentication.

OpenAI smoke was attempted twice with SDK retries disabled; the diagnostic attempt returned **HTTP 401**. No live success is claimed. Anthropic was not called because no credential was supplied. The single authorized read-only `/v1/models` authentication diagnostic also returned **401**, with allowlisted type `invalid_request_error` and an unclassified code. No further provider calls were made and the credential was not modified. Live validation remains blocked. Resolve authentication before rerunning OpenAI; supply a second-provider credential before validating Anthropic. CI is checked in; hosted CI execution and external OTLP collector delivery were not run here.

Implementation decisions and milestone acceptance status are in [PLAN.md](PLAN.md). Current references: [PydanticAI Temporal capability](https://pydantic.dev/docs/ai/capabilities/durable_execution/temporal/), [MCP client](https://pydantic.dev/docs/ai/mcp/client/), [Temporal Python messages](https://docs.temporal.io/develop/python/workflows/message-passing), [OpenAI tools](https://developers.openai.com/api/docs/guides/tools).
