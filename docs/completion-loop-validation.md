# Completion-loop validation

Development execution headers `/tmp/completion-context-execute.log` and `/tmp/completion-finish.log` confirm `gpt-6-astra`, reasoning `medium`. Implementation follows `/tmp/completion-context-plan.md`; no additional agents, production rollout, commits or pushes.

## Changes

- Versioned semantic context exposes declared expected bytes/hashes, command specifications, criterion/check relationships, assumptions, constraints, task plan, remaining capacity, scoped action history and failed/passing/stale verification observations. Session history carries user/assistant roles and explicit truncation. Configured instructions remain in SDK instructions and propagate to children; task constraints and assumptions now propagate too.
- Commands retain argv, cwd, exit code and bounded stdout/stderr observations. Full logs remain available through authenticated operation downloads and the existing authorized `workspace_outputs` capability. History retains successful repairs and failed actions; scoped operation/child selectors remove repeated opaque identities. Tool output is untrusted data, never completion authority.
- Completion resolves check receipts from authoritative database records, matching criterion, check specification, provenance, goal, branch, revision and dependency hash. Missing checks run through existing durable actions. Failed checks reject completion and feed repair; unchanged failures are not automatically rerun. Fresh passes support acceptance; explicit uncertainty stays explicit. Source receipts also come from records, not the context projection.
- Multiple semantic output calls are rejected before any action effects, with actionable persisted feedback. The physical provider call is counted normally. No call is silently selected while others are dropped.
- New coordination uses `v3-completion-loop-v2`; the earlier semantic marker and legacy activity payloads remain supported. Stale completion phases checkpoint feedback and return to observation. Model retries reuse the persisted context. All model/tool/storage I/O remains activity-side; existing fences, operation identities, approvals and sandbox isolation remain in force.
- Compact context/schema metadata and shared-ledger token reservations allow useful child and parent work within the unchanged 16,000-token root ceiling. Child token ceilings are local maxima, not prepaid equal partitions; root reservations still enforce capacity and protect parent headroom. Capacity rejection remains visible, including measured message/schema bytes and required reservation. No token conversion ratio or security boundary was relaxed.

## Validation and evidence

Focused fake tests cover declared requirements, role history, config/constraint inheritance, scoped child context, immutable retry context, multioutput rejection, failed checks followed by repair, multiple checks, fabricated projected receipts, explicit uncertainty and visible capacity failure. Focused PG/Temporal/broker checks cover real failing commands, repair, accepted completion, fresh parent checks, cancellation, worker/broker restart and replay.

Verified focused commands and the final broad/live results are listed in README.md. The final infrastructure gate uses isolated schemas/queues and broker 18091, sequentially. The initial full run (196 passed, 2 skipped) inadvertently used broker 18090 for legacy toolkit sandbox checks because those tests hard-coded it. No deployment/restart/migration occurred. A subsequent rerun was interrupted with SIGINT before its toolkit section; those test URLs/keys were corrected to the isolated 18091 broker. No suite was SIGSTOPed. Paid-provider pytest cases are excluded.

The new `completion-loop-v1` fixtures explicitly require evaluated arithmetic `12\n` and exact CSV headers/order/LF endings. The existing harness and immutable guard are reused. Before paid execution, every exact fixture must pass through the real SDK with a fake transport and real HTTP/PG/Temporal/sandbox execution. Initial unpaid preflights exposed context/child-allocation failures; their evidence is retained. Stub usage is synthetic, so it does not establish live provider token usage or model quality.

Campaign evidence is under `var/acceptance/completion-loop-v1/`: each preflight, SDK trace, downloaded bytes, authoritative operation/verification snapshots, source/fixture hashes and historical-file preservation hashes. Live success requires accepted completed status, independent downloaded-byte/behavior checks, preserved inputs, fresh meaningful checks, and actual completed children plus parent integration for parallel work. The live transport guard permits at most 72 physical calls: 12 each for bug/CSV/recovery/direct and 24 shared for parallel; unused allowances cannot transfer. One root per case; terminal failures cannot be resubmitted. Luna uses reasoning `none` and output caps 768/1024, with the existing key confined to the worker.

## Limitations

This is scoped task verification, not a universal correctness proof. Imported user checks and exact-byte assertions establish their declared properties; the built-in integration check establishes Python syntax only. Context/history and log excerpts are bounded and explicitly marked; oversized requests still fail visibly. No production deployment, restart or migration was performed on 18000 or unrelated 8000. Historical campaign fixtures/evidence/ledgers and AGENTS.md remain unchanged.

## Final bounded correction pass — 2026-09-16

The single live campaign completed **before** the two post-live fixes below. Exact final preflight `var/acceptance/completion-loop-v1/preflight-0db5c29b0d434418bf5851d076691ee2.json` passed all five SDK/backend scenarios. That preflight and the 198 passed / 2 skipped broad service result are **pre-final** results, not validation of the post-live source. The earlier 196 passed / 2 skipped run used 18090 for legacy toolkit sandbox jobs as noted above. Final focused service tests use only 18091.

| Live scenario | Physical requests | Outcome |
| --- | ---: | --- |
| Bug | 9 | Failed; corrected `double` to multiplication, preserved tests and obtained passing pytest/syntax receipts, then repeated commands/inspection without accepted completion; stopped `budget_exhausted`. |
| CSV | 6 | Failed; exact cleaned/summary CSV bytes and input preservation passed, but malformed semantic responses stopped execution before all fresh checks and accepted completion. |
| Recovery | 5 | Failed `no_progress`; required corrected command/output and fresh checks were absent. |
| Direct | 2 | Passed accepted completion, exact `12\n` output and fresh checks. |
| Parallel | 6 | Failed `execution_stopped`; malformed responses and a write-only child lacking required verification contributed; neither child completed, and required merges/output checks were absent. |

Total: **28/72 physical requests; 1/5 accepted scenarios**. Full operations, events, downloads and original source hashes remain in `var/acceptance/completion-loop-v1/live.json` and its adjacent evidence. Terminal cases were not resubmitted. These results do not establish reliable live completion, even where intermediate artifacts were correct.

Post-live corrections:

- Validate returned semantic output against the actual private SDK output type before SDK selection. Invalid JSON/schema, text-only, unknown and multiple tool calls produce bounded structural feedback in persisted operations/checkpoints and the next observation. No invalid action executes. Field locations are restricted to schema-known names; raw values, provider text and exception messages are excluded. Provider attempt/usage accounting remains normal. Repeated invalid outputs stop through existing progress/attempt limits. Provider/network/arbitrary exceptions do not enter semantic repair; no new provider transport retry mechanism was added.
- For completion-loop v2 assignments, derive `workspace_verify` for write/command or declared-check work only from the intersection of parent tools and delegation policy. Reject a missing authorized dependency with actionable feedback before any children are created, including a multi-child assignment. Persist requested assignment and effective capabilities separately; public effective grants show the actual tools. Legacy assignment behavior remains unchanged.

Final verification: **153 passed / 60 skipped** in the final offline suite (30.32 seconds); **32 passed** in focused SDK/context tests (13.48 seconds); **4 passed** in focused service tests; repository lint, format and whitespace checks passed. The four focused PG/Temporal/broker tests passed in 27.43 seconds: actual minimal-capability child completion/merge, failed-check repair with one and four commands, and malformed SDK response → corrective write → fresh byte/syntax checks → accepted completion. All four replay their Temporal histories. No six-minute fault-suite rerun was needed for these activity-side changes; its earlier results remain pre-final. Offline SDK regressions additionally cover repeated malformed responses, zero effects for invalid/multiple calls, safe diagnostics, unchanged provider-error classification, denied policy with zero children, immutable contexts and authoritative completion receipts.

Historical preservation was checked read-only: all 28 files in `preserved-before.json` remain byte-identical, including ledger/marker states v3 19/24, lightweight 19/32, comparison 58/60, v2 48/50 and historical 16/20. AGENTS.md is unchanged. No additional paid calls, ledger changes, production deployment, production restart, migration, commits or pushes occurred in this correction pass.

The post-live fixes have **offline and isolated real-backend evidence only**, with no new live evaluation. Repeated unnecessary actions, failure to choose completion after valid evidence, and failed recovery behavior remain live limitations. Completion still requires all configured criteria and fresh authoritative evidence; no acceptance requirement was weakened.
