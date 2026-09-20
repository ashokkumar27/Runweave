# Local validation — 2026-09-13

The app is available at **http://localhost:18000**. PostgreSQL volumes were preserved. No commit, push, external deployment, hosted Agents API, sandbox or real messaging action was performed. `.codex` and `AGENTS.md` were unchanged. Existing provider credentials were reused without rotation or disclosure.

## Checks

- Offline tests: **65 passed, 20 opt-in skips** in the final shared workspace.
- Final full service-enabled suite: **83 passed, 2 provider skips**. An earlier rerun overlapped the authorized MCP rebuild and had one connection failure (81 passed); the undisturbed final rerun passed. Counts include the separately added client/startup tests; this denial-policy task did not edit those files.
- Ruff lint, format and `git diff --check` passed.
- Production Docker images built with `uv sync --frozen --no-dev`; `httpx`, API, worker and CLI imports passed inside the API container.
- Migration startup and `alembic check` passed without deleting data or modifying the legacy-run migration guard.
- Running production app HTTP smoke passed authentication, duplicate submission, durable fake result, SSE replay, continuation, approval and real MCP conversion.
- Authenticated readiness reported database ready, Temporal reachable and a workflow poller observed. It intentionally reports provider/MCP access as unverified; separate acceptance provides execution evidence for this configuration at test time.

## Full HTTP acceptance

[Initial live artifact](acceptance-live.json), [historical coached denial artifact](acceptance-denial.json), [current uncoached policy proof](acceptance-denial-policy.json), and [fake artifact](acceptance-fake.json) contain synthetic results and run/event identifiers. The acceptance client creates agents and submits, continues, streams, approves, denies and cancels through HTTP. Assertions additionally read isolated PostgreSQL state and Temporal history.

Each invocation starts a dedicated API and worker, a unique PostgreSQL schema and task queue, and uses the real local PostgreSQL, Temporal and MCP services. APIs receive no provider credential from the harness. Dedicated workers are stopped and isolated schemas removed afterward; Temporal retains cancelled/completed test workflow history under its normal retention policy.

| Scenario | Observed result |
| --- | --- |
| MCP composition | Two `convert_temperature` completions for 20°C and 30°C, then one `add` completion; final value **154**. |
| Session continuation | Follow-up asked for the previous sum without restating it; returned **154**. |
| SSE disconnect/replay | Disconnected after the first event, reconnected using its cursor; IDs **1–9**, ordered, unique, matching persisted events through `run.completed`. |
| Exact note approval | Exact synthetic incident text shown in the pending arguments; zero stored notes before approval. |
| Durable recovery | Observed the durable approval timer, SIGKILLed the dedicated worker, submitted duplicate approvals while down, confirmed zero effects while down, restarted; exactly one stored note and one committed-effect event. |
| Idempotency/conflicts | Duplicate submission returned the original run; changed input with the same key and contradictory approval decisions were rejected. |
| Denial | Targeted rerun reached a terminal denial acknowledgement with zero stored notes and zero committed-effect events. |
| Clause conflict | Referenced Clause A’s 30 days and Clause B’s 60 days as conflicting. Same-session amendment of B to 30 days produced an explicit resolution. |
| Fake cancellation | Cancelled while awaiting approval; terminal `cancelled`, zero notes. No paid model used for this case. |

The original uncoached denial failure and coached passing rerun remain unchanged in their historical artifacts. The server now disables `record_note` for the remainder of a run after its first resolved denial. Subsequent note calls receive `ToolDenied` before approval publication or execution, including fresh call IDs and changed arguments. Read-only tools and structured completion remain available; a new explicit user turn creates a fresh run and can request approval again. Decisions already resolved in the same batch remain immutable.

The current denial-only HTTP regression restored the exact original prompt from retained Temporal history: `Call record_note with text exactly: SYNTHETIC denied incident.` It completed with exactly one approval round, zero notes and zero effect events, using three outbound attempts. No coaching, tool hiding or additional paid scenarios were used.

Deterministic tests cover repeated same/changed note arguments, mixed approved/denied batches, read-only completion, fresh session turns, contradictory/duplicate decisions, request exhaustion without a second approval, and hard worker restart after denial. Cumulative approval fixtures now approve the first round so a legitimate second approval can consume the remaining allowance. The `run-scoped-note-denial-v1` Temporal patch preserves unmarked histories' original decisions. Both retained live denial histories replayed successfully, including the original failed second-approval history; a generated unmarked-history regression also passed.

The first fake harness run exposed two test assumptions: fake history recall supports prior additions, and a decision acknowledgement can precede the workflow leaving `awaiting_approval`. The harness now tests MCP separately in fake mode and waits through that transient state when expecting terminal completion. All four applicable fake scenarios then passed with zero paid attempts.

## Paid bounds and transport

**16 / 20 new outbound attempt reservations used**: 11 in the initial live suite, 2 in the historical coached denial rerun, and 3 in the current uncoached denial-policy regression. Four slots remain. No full paid suite rerun or model fallback occurred. The prior authorized direct Luna smoke had already passed two requests and was not repeated here.

The test-only worker wraps actual HTTP transport. SQLite `BEGIN IMMEDIATE` atomically reserves and commits a slot before each provider send, persisting through SIGKILL/restart. Failures and ambiguous sends consume slots. Concurrent offline tests prove the cap stops at 20. The campaign ledger remains at `/tmp/agent-runtime-acceptance-budget.sqlite`; preserve that file for targeted reruns. Do not reset or switch it to extend this campaign’s budget.

The transport rejects any destination except the official Responses endpoint, any model except `gpt-5.6-luna`, output limits over 512 and reasoning other than `none`. SDK and transport retries are zero; Temporal activities retain their existing two-attempt policy. Each run has a 120-second cumulative active budget, 30-second model request timeout and a separate bounded approval allowance. These test bounds do not implement general billing enforcement.

Luna reasoning defaults are private immutable registration data, resolved from each run’s retained snapshot inside activities. Old registrations without this field keep their original hashes and behavior. The denial-policy workflow change is versioned as described above. The official OpenAI IPv4 fix uses matching `httpx` client/transport types, bypassing the earlier local stream incompatibility; live durable acceptance confirms it works here.

## Remaining scope

This establishes narrow synthetic task and recovery behavior, not broad model quality or legal analysis. Anthropic and other live aliases remain unverified. No browser UI, extra connectors, general external mutation reconciliation, hosted CI run or external telemetry delivery was added. Readiness is an observation, not a promise that a currently observed worker will complete future work.


## Toolkit milestone (2026-09-15)

New toolkit, artifact, sandbox and real child-workflow acceptance is recorded separately in [toolkit-validation.md](toolkit-validation.md). The new campaign used 48/50 attempts; the historical 16/20 evidence above is unchanged.
