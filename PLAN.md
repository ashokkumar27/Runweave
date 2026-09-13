# Independent Agents API

Build a self-hosted API that runs tool-using agents across supported model providers. Start with one developer and one workspace; validate provider capabilities rather than promising every model supports every feature.

## Stack and boundaries

Python, FastAPI, PydanticAI, PostgreSQL, and Temporal. One repository, with API and worker processes. Use Docker Compose for local services and OpenTelemetry for run traces. Pin dependency versions after a compatibility spike.

Own the public Agent, Session, Run, and Event schemas. Keep PydanticAI behind a small runtime adapter. PostgreSQL stores application records and replayable events; Temporal owns workflow execution history. Add Harness capabilities individually when needed.

## Milestones

1. **Validate the foundation.** Run the same typed tool and structured-output task against two providers. Exercise PydanticAI's Temporal integration with a worker restart. Record supported versions and limitations. Done when both provider paths and recovery work in a small integration demo.
2. **Ship one complete API flow.** Implement create/get run, session continuation, and SSE events. Snapshot agent configuration per run. Persist ordered event IDs and support reconnect from the last received ID. Use explicit provider/model selection. Done when a client submits a task, sees tool progress, reconnects, and retrieves its result.
3. **Make execution reliable.** Add idempotent submission, bounded retries/timeouts, cancellation, approval and resume. Use stable workflow IDs plus recoverable dispatch to bridge database writes and Temporal starts. Deduplicate event writes and tool operations; external side effects require idempotency support or reconciliation. Done when fault tests cover worker crashes, duplicate requests, interrupted tool calls, and approval across restarts.
4. **Make it usable daily.** Add API-key authentication, usage limits, redacted traces, one MCP integration, and a small repeatable task evaluation set. Add a single isolated sandbox backend only when shell/file execution is needed. Done when the deployment guide reproduces a working installation and the evaluation set passes agreed thresholds.

Defer automatic model routing, subagents, persistent memory, a dashboard, multiple sandbox providers, and multi-tenancy until real usage establishes the need.

## Development workflow

Implement one milestone as small end-to-end changes. Each change states observable acceptance criteria, updates relevant tests, and leaves a runnable demo. Use fake models in default tests and opt-in provider integration tests. Keep setup and verified commands in README.md; record architectural decisions here until separate decision records are useful.

## Implementation status — 2026-09-13

| Milestone | Implemented and verified | Remaining acceptance work |
| --- | --- | --- |
| 1 | Pinned Python stack and lockfile; typed tool + structured fake output; current TemporalDurability integration; hard worker kill/restart and history replay against local Temporal/PostgreSQL | Both live provider demonstrations: OpenAI attempted, HTTP 401; Anthropic credential absent. No live success claimed. |
| 2 | Authenticated create/get run, agent create/get/update, session creation/continuation, immutable run config snapshots, ordered persisted SSE with cursor replay; full Compose HTTP smoke | None for the implemented lifecycle/tool-event flow; token streaming is not included. |
| 3 | Transactional outbox; stable workflow IDs; delivery/reconciliation; idempotent submission/events/note effects; approvals/resume/cancel; bounded retries/timeouts; concurrency and fault tests | General external mutation reconciliation is connector-specific; unsafe external mutations are refused. |
| 4 | API-key auth; admission/request/tool/token budgets; safe operational spans/logging; real read-only HTTP MCP integration; four repeatable fake evaluation cases; Compose/README/CI | Live model quality evaluation and external OTLP collector delivery unverified; hosted CI not executed. |

Executed checks: default 24 passed / 14 explicitly skipped; service-enabled 36 passed / 2 live-provider tests skipped. This includes mocked Chat Completions/configuration contracts, retained registrations, hours-long approval waits with hard restart/replay, cumulative approval/active/request budgets and retry-timeout classification. Local PostgreSQL 17.6, Temporal server 1.28.1, Python 3.13.3, PydanticAI 2.43.0, Temporal SDK 1.32.0, FastAPI 0.141.1 and SQLAlchemy 2.0.52. Dependency versions are exact in pyproject.toml and/or uv.lock. Migration upgrade and drift check, image builds and full Compose HTTP flow passed. Port 8000 was occupied; Compose API port is configurable and was verified on 18000.

## Implementation decisions

- A single workspace admission row serializes the short submission transaction. A session accepts one active run; concurrent continuation receives 409. Only completed turns advance private session history, capped at 250 KB. This avoids ambiguous history forks without adding queues per session.
- The worker process also polls the transactional outbox and reconciles unexpectedly closed workflows. PostgreSQL stays authoritative for public status. Cancellation wins when it acquires the run lock first; a completed run cannot later become cancelled. Outbox commands remain recoverable while the worker is down.
- The current supported PydanticAI `TemporalDurability` capability runs the agent loop inside the deterministic workflow and registers model/tool I/O activities. Connection-free model metadata is used in workflows; provider clients are constructed and closed outside workflows through the private registration resolver. Credentials never travel in workflow dependencies or public events. Public schemas contain no PydanticAI/Temporal types.
- The MVP streams durable lifecycle/tool events, not model tokens. Approval uses PydanticAI deferred calls with persisted immutable decisions and outbox signals. Active time is cumulative across execution, retries and all resumes, and pauses only during durable approval waits. A finite operator approval allowance is snapshotted per run and shared across rounds (default 24 hours). Approval expiry is `approval_timeout`; active expiry remains `run_timeout`; expiry wins equal-timestamp approval races. Temporal execution timeout combines both budgets plus 180 seconds of headroom. Migration 0002 refuses active legacy runs; drain/version existing workflows before changing timer behavior.
- The only mutating tool is a PostgreSQL note, with effect and event committed in one transaction under a stable operation ID. The HTTP MCP integration is read-only. Arbitrary external writes are not exposed; future connectors must provide idempotency or actual reconciliation rather than relying on retries alone.
- Model/tool activities allow two attempts, provider SDK retries are disabled, and validation allows one retry. Request/tool/token limits are enforced across approval resumes. Failed provider attempts can incur usage not reflected in successful-response accounting; no exact monetary cap is promised.
- Operational telemetry contains only allowlisted run metadata and excludes content/exception bodies. Private PostgreSQL session data and Temporal history contain task content. No external trace export is enabled by default.
- One validated operator registry maps public provider/model aliases to private adapters, namespaced upstream models, explicit endpoints/authentication modes, and tool-calling/token capabilities. Responses, Chat Completions and Anthropic adapters use zero SDK retries. Unsupported selections/capabilities are rejected at agent create/update and new-run submission; no fallback occurs. Each run pins a content-derived immutable registration retained in PostgreSQL across config edits and restarts. Endpoints/credential references remain outside public contracts, events and traces. Local unauthenticated Chat Completions sends no authorization header or inherited OpenAI credential.
- Live OpenAI and Anthropic acceptance remains unverified. Two earlier paid OpenAI attempts returned 401. The one authorized read-only models diagnostic also returned 401 (allowlisted type `invalid_request_error`, unclassified code). No additional paid requests, key changes or credential-file modifications occurred.

All originally deferred features remain deferred. No sandbox backend was added because there is no shell/file execution tool.

## Verified references

- [PydanticAI model providers](https://pydantic.dev/docs/ai/models/overview/)
- [PydanticAI Temporal integration](https://pydantic.dev/docs/ai/capabilities/durable_execution/temporal/)
- [Codex project instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
