# Completion model findings — 2026-09-20

**Live acceptance improved from 1/15 to 11/15. Full completion remains unverified:** Luna direct and all three parallel cells failed final verification. No failure is counted as success merely because output bytes exist. These are two single-run fixture matrices, not a statistical model ranking.

Development execution `/tmp/completion-final-execute.log` confirms **gpt-6-astra, medium**. No agents, model substitution, replanning, deployment, commits, or pushes. Existing dirty work was preserved.

## Baseline and held-code verification

| Cell | Baseline | Calls | Tokens | Verified | Calls | Tokens |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| gpt-5.6-luna/bug | failed | 9 | 8,733 | passed | 7 | 7,695 |
| gpt-5.6-luna/csv | failed | 4 | 4,124 | passed | 6 | 7,251 |
| gpt-5.6-luna/recovery | failed | 8 | 8,271 | passed | 5 | 6,089 |
| gpt-5.6-luna/direct | passed | 3 | 2,113 | failed | 6 | 5,071 |
| gpt-5.6-luna/parallel | failed | 10 | 8,354 | failed | 11 | 10,045 |
| gpt-5.6-terra/bug | failed | 7 | 6,825 | passed | 6 | 6,470 |
| gpt-5.6-terra/csv | failed | 3 | 2,877 | passed | 5 | 6,013 |
| gpt-5.6-terra/recovery | failed | 3 | 2,884 | passed | 5 | 6,115 |
| gpt-5.6-terra/direct | failed | 6 | 4,569 | passed | 4 | 3,516 |
| gpt-5.6-terra/parallel | failed | 12 | 10,114 | failed | 11 | 9,909 |
| gpt-5.6-sol/bug | failed | 8 | 7,086 | passed | 6 | 6,473 |
| gpt-5.6-sol/csv | failed | 8 | 8,827 | passed | 6 | 7,289 |
| gpt-5.6-sol/recovery | failed | 9 | 9,297 | passed | 3 | 3,290 |
| gpt-5.6-sol/direct | failed | 4 | 3,427 | passed | 4 | 3,517 |
| gpt-5.6-sol/parallel | failed | 12 | 9,794 | failed | 11 | 10,328 |

Baseline: **106/216 physical calls**, 90,848 input + 6,447 output = **97,295 reported tokens**. Verification: **96/216 physical calls**, 94,390 input + 4,681 output = **99,071 reported tokens**. Combined: **202/432 calls**, **196,366 reported tokens**; unused allowances were not spent. Every physical attempt has a retained HTTP outcome; all 202 responses were HTTP successes, including responses whose actions were rejected. There were no provider-failure/unknown-outcome attempts in these two phases. HTTP success is not task success. Tokens are provider-reported usage, not a monetary bill.

Both phases admitted exactly one unique root for each of 15 cells and terminally latched every cell. No reset, transfer, terminal resubmission, paid probe, fallback, or third phase. Every final cell ran again; none was skipped. The final source remained byte-identical from passing SDK preflight through all 15 paid verification cells.

## Evidence-driven corrections

- Baseline CSV/recovery/bug responses used IDs such as `bytes0` or `pytest` where `k0` selectors were required. Completion responses also used criterion IDs instead of `c0`. They passed broad structural validation then stopped at compilation. Private context version 3 now constrains check, criterion, and child selectors in the actual SDK output schema. Invalid selections enter existing safe structural-feedback repair before effects. Older persisted context versions retain their prior schema/instructions.
- The SDK described the action as “The final response which ends this conversation.” Baseline decisions repeatedly claimed that workspace/check tools were unavailable. The new private `next_action` description accurately describes executable actions and subsequent observations. Compact guidance distinguishes command execution, persistence, authoritative checks, and completion. The pinned SDK sends `parallel_tool_calls:false` for the single-action output contract; this does not serialize Temporal child workflows. Multiple outputs remain rejected before effects. Reasoning/output caps were not changed.
- Luna recovery repeatedly ran the corrected command with `commit:false`, leaving no workspace output. Commands now report `workspace_effect` with `commit_requested`, `persisted`, and exact `changed_paths`. Guidance explains discarded edits. No code automatically changes the model's commit choice. Captured-response regression proves an uncommitted output stays absent until an explicit `commit:true` repair.
- New contexts expose each check's status from authoritative current receipts. They deduplicate repeated latest-result payloads while retaining successful repairs, failure history, user instructions, task constraints, expected bytes, and immutable bindings. String types already implied by enum/const are removed from transmitted schemas; runtime validation and bounds remain intact.
- A first unpaid final preflight exposed excessive instruction overhead: 787 extra instruction bytes per call caused parallel capacity failure. Shortened guidance and redundant-schema removal restored all 15 exact SDK/backend preflight cells under the original limits. The failed preflight is retained. No limit, reservation conversion, default, proof requirement, or acceptance check was relaxed.

Coordination is unchanged. Model/tool/storage work remains activity-side; existing cancellation fences, authoritative receipt resolution, retry-context reuse, and parent/policy capability intersections remain in force. No case-specific runtime branches or forced completion were added.

## Exact outputs and authoritative acceptance

Every passing bug cell downloaded `main.py` containing `def double(x):\n    return x * 2\n`, preserved `test_main.py`, passed fresh supplied pytest and runtime syntax checks, and passed the independent AST behavior oracle for 4, -3, and 0.

All passing CSV cells downloaded exactly:

```text
cleaned.csv = "name,amount\nAlice,7\nBob,-2\nEve,9\n"
summary.csv = "valid_rows,rejected_rows,total\n3,2,14\n"
```

They preserved `input.csv` byte-for-byte and passed fresh `bytes0`, `bytes1`, and `runtime.syntax` receipts. All three final recovery cells first ran the required failing filename, then ran the corrected `python report.py inputs.csv` exactly once with explicit persistence. They downloaded `result.csv = "total\n14\n"`, preserved `report.py` and `inputs.csv`, and passed fresh `bytes0` and `runtime.syntax`. Terra/Sol direct downloaded `sum.txt = "12\n"` and passed both fresh checks. Luna direct produced those bytes but never obtained accepted completion or fresh receipts.

Full exact answers, downloaded-file paths/SHA-256 values, authoritative receipt IDs/specification hashes/revision/dependency bindings, events, operation arguments/results, logs, and child records are retained in:

- [Baseline audit](../var/acceptance/completion-models-baseline-v1/audit.json) and [full baseline evidence](../var/acceptance/completion-models-baseline-v1/live.json).
- [Verified audit](../var/acceptance/completion-models-verified-v1/audit.json) and [full verified evidence](../var/acceptance/completion-models-verified-v1/live.json).
- Both directories contain `live.wire.jsonl`, `live-source.json`, `models.json`, immutable source/fixture hashes, and `live-downloads/`. Raw wire captures and full evidence use private filesystem permissions and contain fixed fixture data, never request headers or credentials. Provider raw error bodies are excluded. Tool outputs remain untrusted.

The audits pair every raw model response with the persisted compiled decision. **Zero forced reporting blocks were found in either phase**, and no accepted result came from forced completion. Rejected/malformed actions and missing wire outcomes are distinguished from compiled actions. Final live responses did not need selector or multiple-output rejection; fake replays establish that invalid responses still repair safely.

## Remaining failures and exact capacity evidence

- **Luna direct:** one correct write followed by five identical writes, all with available check selectors/status and reuse/completion guidance. It stopped `no_progress` after 6 calls / 5,071 tokens. This regressed from the passing baseline cell. Correct bytes alone do not meet acceptance.
- **Luna parallel:** left child repeatedly rewrote its file; right child explicitly assessed a pending syntax check as inconclusive. Both then failed capacity admission. Parent authored substitute files and repeated joins instead of successful integration. No child completed.
- **Terra parallel:** both children repeated unchanged writes three times; parent wrote substitutes before/after joining. Neither child reached checks/completion before capacity refusal.
- **Sol parallel:** the right child completed in two calls with automatic checks. The left child wrote and explicitly verified, then could not reserve its next request. Parent merged the successful child, wrote a substitute, and performed further joins/merges, but never passed the integrated checks and acceptance. One completed child is insufficient.

| Final parallel cell | Final root reported tokens | Next root reservation | Sum vs 16,000 |
| --- | ---: | ---: | ---: |
| Luna | 10,045 | 6,471 | 16,516 |
| Terra | 9,909 | 6,332 | 16,241 |
| Sol | 10,328 | 6,440 | 16,768 |

These refusals occur **before provider send**. Local child ceilings stayed at 4 attempts and 8,000 tokens. Retained local usage + next reservation was: Luna left 2,409 + 5,723 = 8,132; Luna right 1,633 + 6,478 = 8,111; Terra children 2,403 + 5,705 = 8,108 and 2,403 + 5,713 = 8,116; Sol left 1,633 + 6,411 = 8,044. Shared concurrent reservations and parent headroom are additional constraints. These are conservative request reservations, not provider-reported consumption or evidence that all physical-call allowances were used.

This does **not** establish that parallel completion is fundamentally impossible: the final exact SDK/backend preflight passed all three parallel fixtures, and Sol's right child completed live. It establishes narrow operational headroom for these actual live assignments and actions, with repeated work and pending-check uncertainty consuming that headroom. Further improvement should target redundant actions, the distinction between pending checks and genuine uncertainty, and compact child context. The 44-token local deficit in Sol is explicitly a capacity sensitivity, not proof of an intrinsic model inability. Those improvements need another separately authorized live evaluation; this task authorizes no third paid phase. The final code was left at the version actually live-tested.

### Final child identities

| Model | Child ID | Status |
| --- | --- | --- |
| gpt-5.6-luna | `4bba75df-1802-5051-98db-eaeb961b507f` | failed (budget_exhausted) |
| gpt-5.6-luna | `879ddb14-623a-5974-b8bd-0aca7931d99c` | failed (budget_exhausted) |
| gpt-5.6-terra | `015fea5b-9c87-567c-812d-6c73581ef863` | failed (budget_exhausted) |
| gpt-5.6-terra | `58568f59-104d-5e29-b185-753fb942adc0` | failed (budget_exhausted) |
| gpt-5.6-sol | `a4573493-1ff2-55fb-946e-ec7c5ffe0544` | completed (accepted) |
| gpt-5.6-sol | `f200a345-b966-5879-990f-e3ae68d5b129` | failed (budget_exhausted) |

## Validation and reproducibility

The first setup-only replay attempt was blocked by pytest's SDK-request guard and is not claimed as before-fix proof. After using an exclusively in-memory HTTP transport, the four captured regressions failed on the original selector/persistence paths, then passed after corrections. The before/after logs are retained alongside final evidence. Real backend regressions verify exact outputs, preserved inputs, authoritative checks, and Temporal replay. Fake usage is synthetic and is not mixed into the live totals above.

- New immutable phase/child guard tests: **5 passed**; existing focused guard/semantic tests plus these guards: **47 passed**.
- One broad unpaid service run: **220 passed, 2 paid tests skipped**, 426.30 seconds. This was before final payload compaction and is not described as a broad result on final source.
- After compaction: **40 affected tests passed**, including real backend/replay coverage; after the final wording trim, the **4 captured SDK/backend regressions passed** again.
- Final exact SDK/backend gate: **15/15 passed**, 63 fake physical requests; initial payloads match across all models after excluding only model identity and elapsed-clock fields. Final repository lint/format/whitespace checks passed.
- Final live gate: **11/15 accepted**, with independent output/receipt/child oracles; **96 physical requests**.

Verified commands and non-rerunnable paid campaign instructions are recorded in README.md. Final source/fixture/config hashes are in `completion-models-verified-v1/live-source.json`; baseline equivalents are preserved separately. Model registrations are isolated files derived from the same Luna registration, changing only model/upstream identity to the exact Luna/Terra/Sol aliases. Both phases use reasoning `none`, output caps 1,024 for bug/CSV/recovery and 768 for direct/parallel, per-cell call limits 12/12/12/12/24, parent parallel limit 24 shared with children, child local limit 4, root token limit 16,000, child local token limit 8,000. Fixtures, inputs, oracles, and configured budgets are unchanged between models/phases; private contract fixes are the intervention.

### Source and evidence hashes

| File | SHA-256 |
| --- | --- |
| `var/acceptance/completion-models-baseline-v1/live-source.json` | `48a562c4dbac3337b0e9b19bcd8ec95c829d2f1e23679758b906ce0e889acdb6` |
| `var/acceptance/completion-models-verified-v1/live-source.json` | `968247d7e97818e36752e24433485be2c6513973a3811e2db632eb94c772ff22` |
| `var/acceptance/completion-models-baseline-v1/live.wire.jsonl` | `7e2f7e202bac313277ad43a19098338983d934e74066c6b1f5942ac023744433` |
| `var/acceptance/completion-models-verified-v1/live.wire.jsonl` | `6a1019730eecc6fc1ab4657c6d5bc9b6539bbd04cc3f393f0f98182e9242de0a` |
| `agent_runtime/general_semantic.py` | `ac657ce22ca997a239237d9c7526d27df4795036c8a0c3cc20973948d36ce444` |
| `agent_runtime/general_runtime.py` | `c079054b6c806a172ba2ce8001d4ef3e5186672a517c970e7dd8d370cf52bf74` |
| `agent_runtime/general_actions.py` | `39fc277b8f104f04cf897d54ebe6d888500822dd1308179a6a042bd17b462cc2` |
| `scripts/completion_loop_fixtures.py` | `db9ea188cd93ae027fd178f9fa28c8e149e8f228bf9bee67495bb0040109b1f0` |
| `tests/fixtures/completion-models-responses.json` | `6f4865c7e8ccac9fca792265a60136d7280eba05bf1c648af685c4f6984196f5` |

## Preservation and isolation

All **677 historical files** in the preservation snapshot remained byte-identical. Historical ledgers/markers remain completion **28/72**, comparison **58/60**, lightweight **19/32**, v3 **19/24**, v2 **48/50**, and historical **16/20**. AGENTS.md is unchanged. Only temporary API ports, isolated PostgreSQL schemas/Temporal queues, and broker **18091** were used. Each harness invocation removed its own schema and stopped its own processes; broker volumes remain. Production **18000**, its broker **18090**, and unrelated **8000** received no deployment, restart, or migration. No secrets were printed, no keys created, and no commits/pushes performed.
