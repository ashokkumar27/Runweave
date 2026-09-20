# General autonomous runtime v3 validation

Local rollout passed on 2026-09-16. Full live acceptance remains incomplete; see the approved rollout results below. Earlier sections preserve historical evidence.

## Boundaries

- Current correction launch verified from the first 11 lines of `/tmp/agent-runtime-v3-correction-dev.log`: `gpt-6-astra`, reasoning `medium`.
- No paid provider requests were made during this correction pass. All model execution used existing fake scripts or in-process SDK stub responses.
- Existing ledgers were not modified: historical 16/20, v2 48/50, and v3 15/24. V3 allocations remain simple 1/1, project 4/6, dynamic 5/10, data 1/3, recovery 4/4. Historical failures and the retained data artifact remain intact.
- Existing production data, services on 18000/8000 and service volumes were preserved. Backend testing uses isolated database schemas, task queues, a separate broker on 18091 and its own state volume.

## Implemented paths

The v3 opt-in has owned task/state/criterion/assessment contracts, a model-selected action loop, immutable project bytes and revisions, isolated argv execution, scoped evidence admission, dynamic Temporal child workflows, file-level three-way merge, metadata-driven approval for notes and application records, shared accounting, authenticated inspection/downloads and client/CLI support. Legacy workflow implementations remain registered, and v3 dispatch uses a separate task queue suffix.

Project execution uses the pinned image recorded in `config/general.json`: offline Python 3.13 with pinned pytest dependencies. Containers have no network, host checkout, provider credentials or Docker socket. The trusted broker owns daemon access. The supervisor runs generated processes under another UID, kills remaining generated processes before collection, and rejects unsafe links and file types. This is container isolation with a shared kernel, not VM isolation.

Public uploads use a 6 MiB wire cap, 256 files, 256 KiB per file and 4 MiB per revision. Root project retention is 32 MiB unique bytes and 64 revision records. Global content storage is 256 MiB. Commands reserve 5 MiB of potential project/output storage before launch; this conservative reservation can reject a command near a storage ceiling. Logs and named outputs are content-addressed and downloaded separately from artifact slots.

A command success proves only execution of its exact specification. The runtime syntax check uses isolated interpreter imports and proves syntax only. User checks remain separate required obligations. Editing imported test files invalidates their authority. Generated supporting checks do not become user checks. Command evidence becomes stale after project changes; merged child evidence does not certify the integrated parent head.

## Evidence recorded so far

- Targeted offline regressions: 53 passed before subsequent hardening.
- First full offline suite: 100 passed, 38 skipped (service/provider opt-ins).
- Real PostgreSQL/Temporal/broker vertical tests: direct project execution and two actual dynamic child workflows passed.
- Seven real-service feature/isolation tests passed, covering exact project/log downloads, link rejection, timeout, no credentials/socket/network, and valid edits after nonzero exit.
- Actual broker SIGKILL reconstruction and cancellation/cleanup checks passed after fixes.
- Populated-0003 additive migration and drift test passed with active legacy rows unchanged.
- Stale-check rejection followed by a fresh check and accepted completion passed after fixing early SSE replay termination.
- The fake HTTP campaign passed all four scenarios and worker SIGKILL/CLI controls. Raw concrete responses and downloaded-byte hashes are in `acceptance-general-runtime-v3-fake.json` and `general-downloads/`.

Full final checks, live campaign results and serving status will be recorded below when executed. No universal correctness, exactly-once provider billing, unrestricted connector support or exhaustive instruction-boundary crash coverage is claimed.

## Pre-correction release checks

- `uv run pytest -q`: **101 passed, 45 skipped** (service/provider opt-ins), 16.29 seconds.
- `uv run pytest -q --integration`: **144 passed, 2 paid-provider skips**, 241.89 seconds. Real PostgreSQL, Temporal, Docker broker and isolated project containers were used.
- `uv run ruff check .` and `uv run ruff format --check .`: passed (91 Python files).
- `git diff --check`: passed. OpenAPI export: 30 paths, all local references resolved.
- Integration includes two actual child histories, sparse grants, a surfaced same-file merge conflict and explicit parent resolution, fresh parent verification, real broker SIGKILL/reconstruction, cancellation during execution and populated legacy migration/drift checks.
- The acceptance harness's file-loop variable was corrected before live launch so specialist-specific assertions execute; fake acceptance was rerun after this fix.

## Bounded corrections — development validation, 2026-09-15

The private SDK adapter now validates semantic action types and compiles them into the existing owned action contracts. A persisted version-1 binding contains the captured state/goal/head, file hashes, criterion identities/provenance, eligible receipts, child selectors and parent grants before provider I/O. The serialized model context is also persisted and reused. Successfully persisted decisions replay without another request. Explicit/scripted actions keep their existing contracts; the old private adapter remains for unpatched v3 coordination.

Private assignment accepts role, objective, acceptance statements, capabilities and input/output paths. The server derives criterion IDs, base revision, reads including writable outputs, and effective local limits. Derivation respects parent grants, delegation policy, shared remaining resources, outstanding active-child allocations and reporting/integration reserves. Existing assignment gates remain authoritative. Effective allocations appear in child context and inspection.

Semantic completion persists a verification phase with exact registered check specifications and target head. Existing isolated action/command activities execute the outstanding caller/runtime checks under existing budgets. The phase advances state bindings only through its own verified operation/checkpoint identities; a changed head or unrelated state transition invalidates it. Failed checks, stale evidence, altered imported tests, child cleanup and unresolved operations retain their completion gates. Explicit verification remains supported. Temporal patch `v3-semantic-completion-v1` separates new coordination from retained v3 histories; v1/v2 registrations remain intact.

Public operation inspection now has owned typed responses for pending, complete and failed operations, bounded structural diagnostics, and measured schema/context sizes. Unknown provider field names are suppressed in structural diagnostics. No raw provider response text or credentials are logged.

### Evidence from this correction pass

- Full offline suite: **115 passed, 56 skipped**, 20.29 seconds (`/tmp/v3-correction-offline-final.log`).
- Final full service suite: **169 passed, 2 paid-provider skips**, 385.72 seconds (`/tmp/v3-correction-service-final.log`). No development checks remain failing.
- Targeted private SDK/stub and real-service checks after reservation hardening: **20 passed, 3 fault tests deselected**, 30.18 seconds. The separate fault run passed **3 tests**, 125.27 seconds.
- Fault checks used only the owned broker on 18091 and a credential-free test worker: real broker SIGKILL/reconstruction, worker SIGKILL/restart during an automatic check, cancellation, cleanup, stable command accounting and one accepted receipt per completed check.
- Coverage includes workspace-free completion/reuse; ordinary read versus exact source evidence; selector/authority rejection; context-capture/provider-failure retry; stale completion invalidation; derived grants and shared reserves; real child creation/new output/join/merge/fresh parent verification; unchanged failing caller checks; imported-test tampering; final-report reserve success and incomplete budget stop; pending/failed HTTP inspection; representative pre-correction v3 replay and corrected workflow replay.
- The first full service run found a transient parent/child token-reservation race (**168 passed, 1 failed, 2 skipped**). The adapter now waits at most 20 seconds per activity attempt for existing reservations to settle, without charging an attempt while waiting or raising limits. A forced-overlap child regression passed with exactly six model calls. The failed run remains in `/tmp/v3-correction-service.log`.
- Refreshed fake HTTP acceptance passed all five scenarios (simple, project revision, dynamic specialists, data, controls), including worker restart and CLI inspection. It appended to `docs/acceptance-general-runtime-v3-fake.json`; prior failed evidence was preserved and paid attempts remained zero.
- The measured direct-action schema was **1,327 bytes** and total request context **2,712 bytes** (`/tmp/v3-correction-targeted.xml`). Schemas include only available intents. Limits remain 16,000 bytes for projected JSON context and 24,576 bytes for the full message/schema envelope, with existing conservative token reservations. These measurements describe the direct fixture, not a maximum-size guarantee.
- OpenAPI exports **30 paths**, with all local references resolved. Lint, formatting and whitespace checks passed.
- Fake retained-artifact import passed with zero paid attempts, using temporary evidence `/tmp/v3-correction-import-check/evidence.json`. It imported the original artifact into new run `597d416d-0b59-4d44-9f43-e0f96a3d880c`; it did not resume the original run. Original bytes: **9**, `total\n14\n`; SHA-256 `a130b8f3b878a25a2b239b566490326512dd69d258c21bbf8e36bb7cf5411f16`.

### Remaining live and rollout gaps

Corrected Luna execution, successful live specialist integration, fresh live data generation, and live retained-artifact verification remain unproven. The exhausted recovery allocation is unchanged. Five remaining specialist attempts are below the optimistic six-request assign/write/complete/join/merge/complete path, so the remaining ledger cannot establish full specialist acceptance. No universal model-quality, exhaustive crash-window, or exactly-once provider-billing claim is made. A crash before decision persistence can require another provider attempt against the same captured context.

Production rollout and additional paid calls were **not performed** because they are outside this approved development launch; automatic approval review rejected the broader launch containing those actions. The full milestone's live acceptance remains incomplete.

### Concrete proposal for parent review (not executed)

After reviewing the completed development gates, the existing local rollout entrypoints are:

```bash
uv run python -m scripts.start_local
uv run python -m scripts.general_production_check
```

The first command rebuilds/restarts the app profile and invokes its migration service using the existing local configuration; the second writes fake-only smoke runs to the deployed application's data. Both require the parent's separate rollout approval. Neither was run in this correction pass. Existing images, volumes, configurations, ports and histories must be retained. The deployed check exercises explicit fake actions; it is not Luna evidence.

A separately approved bounded live proposal is one project attempt using at most the remaining **2 project calls**, and one fresh-data attempt using at most the remaining **2 data calls**. Maximum proposed additional calls: **4**, permanently raising v3 usage from 15 to at most 19. Keep existing fixed ledger/path, scenario ceilings, endpoint, model, reasoning and output caps. Do not spend specialist or recovery allocations. Stop on failure or scenario exhaustion; no reallocation or reset.

```bash
uv run python -m scripts.live_acceptance --live --campaign general-runtime-v3 --scenario project-revise --evidence docs/acceptance-general-runtime-v3-live.json
uv run python -m scripts.live_acceptance --live --campaign general-runtime-v3 --scenario data-task --evidence docs/acceptance-general-runtime-v3-live.json
```

These commands append evidence through the existing guarded campaign and start isolated validation services; they are proposals only. Retained-artifact verification would compete for the same remaining data allocation and must not be mislabeled as fresh generation.

## Approved rollout and bounded live rerun — 2026-09-16

The user explicitly approved “Please update and run it all again” for the concrete local rollout and at most four additional Luna calls (two project, two fresh-data). This authorization superseded the earlier rollout restriction for these actions only. The first 11 lines of this session's `/tmp/v3-approved-rollout.log` confirm **gpt-6-astra**, reasoning **medium**, session `01a0a955-cf1a-72d1-a6be-4805b2eae9dc`. Existing key reuse was authorized. No provisioning, model substitution, specialist/recovery calls, extra scenario invocation, cap changes, resets, commits or pushes occurred. No implementation changes were needed.

### New fake and service evidence

- `uv run pytest -q`: **115 passed, 56 skipped**, 19.71 seconds; `/tmp/v3-approved-offline.log`.
- `uv run pytest -q --integration`: **169 passed, 2 paid-provider skips**, 392.77 seconds; `/tmp/v3-approved-service.log`.
- Tests used their unique temporary PostgreSQL schemas and Temporal queues. V3 fault injection targeted the existing `agent-runtime-v3-test-broker` on **18091**, with separate `agent-runtime-v3-test-state` storage and credential-free test workers. No production fault injection was performed. Existing toolkit checks used their authenticated broker on 18090.
- `uv run python -m scripts.live_acceptance --campaign general-runtime-v3 --evidence docs/acceptance-general-runtime-v3-fake.json`: **all five scenarios passed**, including controls/worker restart/CLI inspection, **zero paid calls**; `/tmp/v3-approved-fake-http.log`. Evidence appended without removing prior failures.
- `uv run python -m scripts.start_local`: **passed**, existing app rebuilt/restarted and migration entrypoint completed; readiness at **http://localhost:18000**; `/tmp/v3-approved-start-local.log`. Existing data/volumes retained; unrelated port 8000 was not targeted.
- `uv run python -m scripts.general_production_check`: **passed**, deployed fake v1/v2 compatibility, v3 completion and isolated project/download check, **zero live calls**; `/tmp/v3-approved-production-check.log` and appended `acceptance-general-runtime-v3-production.json`.
- `uv run ruff check .`, `uv run ruff format --check .` (102 Python files after new download evidence), and `git diff --check`: passed, including after documentation updates.

### New live evidence — one invocation per approved scenario

Both exact proposed commands above were executed once using the existing guarded harness and appended `acceptance-general-runtime-v3-live.json`. All four newly counted outbound requests returned HTTP success; neither scenario passed task acceptance. Runtime remained official Responses **gpt-5.6-luna**, reasoning **none**, with existing 2,048-token scenario output caps. No retry invocation followed either failure.

| Scenario | Run | Outcome | Calls |
| --- | --- | --- | --- |
| project-revise | `345176aa-9789-4f31-bdbd-56716cac2bfe` | Failed `task_blocked`; first decision read `main.py`, second attempted an edit in the protected final-report slot and was blocked. File remained `return x + 2`; no commands or verification receipts. | 2; campaign 15 → 17 |
| data-task | `0881068f-86ea-4f43-b1a3-bf733dfe9b98` | Failed `task_blocked`; first decision successfully generated fresh `result.csv` in an isolated command. Second decision requested another command in the protected final-report slot and was blocked. No verification receipts or accepted completion. | 2; campaign 17 → 19 |

Logs: `/tmp/v3-approved-live-project.log` and `/tmp/v3-approved-live-data.log`, both exit 1. The exact blocker was `Final reporting reserve reached; work remains incomplete.` The protected reserve was not weakened to make these scenarios pass.

Fresh data bytes were authenticated/downloaded and matched **`total\n14\n`**, length **9**, SHA-256 **`a130b8f3b878a25a2b239b566490326512dd69d258c21bbf8e36bb7cf5411f16`**. Retained file: `general-downloads/0881068f-86ea-4f43-b1a3-bf733dfe9b98-result.csv`. This proves fresh generation and exact downloaded bytes, not completed live verification or resumed-artifact acceptance.

### Ledger and readiness after this pass

Exact v3 delta: **15 → 19 of 24 (+4)** at the unchanged `var/acceptance/general-runtime-v3.sqlite`. Allocations: simple **1/1**, project **6/6** (+2), dynamic specialists **5/10** (unchanged), data **3/3** (+2), recovery **4/4** (unchanged). Attempt IDs **16–19** are the only new attempts. Both campaign started markers are unchanged. SHA-256 baselines in `/tmp/v3-approved-ledger-before.json` confirm the historical **16/20** and toolkit **48/50** ledger files remained byte-for-byte unchanged.

The updated local app is ready and its deployed fake checks passed. Full live milestone acceptance is **not ready**: corrected live project completion and fresh-data verified completion failed within their exhausted allocations. Live specialist integration and live retained-artifact verification remain unproven. The five remaining campaign slots belong exclusively to specialists and were not authorized or used in this pass; no reallocation is permitted. Existing historical failures, original artifact, dirty implementation work, ignored credentials and persistent service volumes were preserved.
