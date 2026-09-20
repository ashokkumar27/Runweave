# Toolkit milestone validation — 2026-09-15

The implemented flows use public HTTP contracts and the ordinary worker, PostgreSQL storage, real Temporal child workflows, and isolated job containers. Application submissions, approvals, cancellation, observations and artifact downloads in the acceptance harness use `Client`; only infrastructure setup, process fault injection and isolated-schema cleanup use infrastructure interfaces.

## Checks

- Offline suite: **77 passed** (opt-in service/provider tests skipped).
- Final full service suite: **105 passed, 2 paid-provider tests skipped** (`uv run pytest -q --integration`, 163.96 seconds).
- Additional completed-job recovery test: **1 passed** against the real backend; an identical retry retrieves cached bytes even after its new-job admission deadline has expired. The broker image was rebuilt after this fix.
- Additional sandbox resource suite: **5 passed**, covering symlink output, stdout flood, memory exhaustion, CPU exhaustion, and PID/fork exhaustion through API-configured fake runs against the actual backend.
- Toolkit PostgreSQL/Temporal suite: **9 passed** before adding the PID case, including actual parallel children, root reservation contention, child approval recovery, exact CSV bytes, isolation boundaries, and parent cancellation during child Python execution.
- Fake HTTP fixture campaign: all six single/delegated document, CSV and repository flows passed. A separate **SIGKILL worker restart** case passed: child approval persisted, root denial was submitted while the worker was down, replay resumed, a second child inherited denial, and public effect receipts remained empty.
- Offline contracts cover upload retry/conflict, authentication, grant isolation, path rejection, exact output hash, immutable specialist snapshots, duplicate/conflicting child intent, depth/lifetime limits, exact approved note arguments, namespaced child approval IDs, and retained charges after failed model requests.
- The new SQLite transport guard passed 60 concurrent reservation attempts: exactly 50 succeeded; the next request never reached transport. Manifest/counter mutation and symlink/reset attempts were rejected. Historical fixed-20 tests still pass.
- Lint, format, additive migration `0003`, and Alembic drift checks passed. `AGENTS.md` remains unchanged. Existing PostgreSQL/Temporal volumes were retained.

## Bounded API consistency follow-up

- `uv run pytest -q tests/test_toolkits.py tests/test_client.py`: **27 passed**. Six new HTTP cases cover queued/running/completed legacy usage, v2 shared root/child accounting including retained reservations, and external availability with absent/configured endpoints.
- Three targeted fake-model service tests passed: parallel children/public shared budgets, PostgreSQL reservation contention/reconciliation, and legacy durable session/MCP execution. The contention fixture now explicitly opts into v2, matching the ledger semantics it tests.
- V1 budgets return `execution_version=1`, `accounting_mode="recorded_successful_usage"`, and `successful_usage` equal to persisted `Run.usage`. Physical counters, reservations, reported-token ledger and shared total-token limit are `null`; an empty usage object means unrecorded, including while active. V2 retains its authoritative root ledger with `execution_version=2` and `accounting_mode="shared_ledger"`. Workflow/replay semantics are unchanged.
- Existing descriptor logic already marked remote MCP and sandbox handlers `unverified`; no duplicate handler change was needed. Availability now has an explicit public enum and conservative default. Configuration does not establish health; discovery performs no network probes.
- Ruff lint/format and diff checks passed. OpenAPI was refreshed and matched the deployed API. Local images were rebuilt through `scripts.start_local`; the existing fake-only production check passed again. [API consistency evidence](acceptance-toolkit-api-consistency.json) records a completed deployed v1 fake run with nonzero successful usage, unknown physical accounting, tool availability and readiness. [Deployment metadata](toolkit-deployment.json) was refreshed with current image IDs and safe security fields.
- No paid calls or campaign reservations; both ledgers were read-only verified unchanged at **48/50** and **16/20**. Existing work and `AGENTS.md` were preserved; no commits or external deployment.

## Actual Luna campaign

Ledger: `var/acceptance/toolkits-subagents-v1.sqlite`, immutable maximum **50**, actual attempts **48**. Every attempt was reserved immediately before transport I/O, including retries/errors. Model: `gpt-5.6-luna`; Responses endpoint only; reasoning `none`; output caps 512 or 1024; SDK/HTTP retries zero. Root/scenario attribution is persisted. Reported usage across all campaign runs is **45,829 tokens**. This is reported usage, not a monetary bill or a promise to account exactly for unknown provider charges.

The historic `/tmp/agent-runtime-acceptance-budget.sqlite` still contains **16 attempts** and was not reset or reused. No further live call was made for production readiness.

Raw evidence: [acceptance-toolkits-subagents-live.json](acceptance-toolkits-subagents-live.json). Each execution appends to prior evidence. Initial failures remain recorded. Inputs: [fixtures/toolkits](fixtures/toolkits/). Downloaded artifacts: [toolkit-downloads](toolkit-downloads/).

| Accepted scenario | Attempts | Reported tokens | Seconds | Verified result |
| --- | ---: | ---: | ---: | --- |
| Document baseline | 2 | 2,349 | 9.555 | Both original/amended diffs and source evidence |
| Parallel document specialists, repeat 1 | 6 | 6,092 | 16.342 | Two real children; parent synthesis; both downloaded diffs |
| Parallel document specialists, repeat 2 | 6 | 5,837 | 14.951 | Same independent tasks, correct source evidence and diffs |
| CSV baseline | 2 | 1,766 | 10.108 | Model-generated Python; exact cleaned CSV bytes; net 200.00 |
| Delegated CSV | 4 | 3,306 | 13.421 | Real child generated Python; identical downloaded CSV |
| Repository baseline | 4 | 3,676 | 12.617 | Both file/line locations; correct downloaded patch |
| Delegated repository | 6 | 5,100 | 16.706 | Real child inspection; source evidence and identical patch |

Baseline/delegated pairs use the same domain tools, input artifacts, output cap and total root allowances. Only delegation and specialist declarations differ. The repository parent was admitted with the remaining campaign request ceiling; this did not bind (6 requests used). The CSV oracle is 5 input rows, 4 retained rows, 1 duplicate, 1 refund, net **200.00**, with original amount formatting and LF newlines. Both live outputs also reported value 200.0. The repository patch changes `config.env:1` from `TIMEOUT_SECONDS=30` to `TIMEOUT_SECONDS=60`, supported by `README.md:2`.

Delegation cost more requests, tokens and elapsed time on these small fixtures. Its observed benefit is independent context and durable specialist execution, not a demonstrated speed/cost improvement. It remains opt-in.

### Initial failures and fixes

The first document batch spent **18 attempts**. Three roots failed conservative token admission before final synthesis; their tools/children had produced artifacts. One initial baseline passed its artifact oracle but incorrectly described an unchanged refund clause as added. That initial prose is not accepted as a correctness success.

The fix made the child handoff explicitly bounded (600-character summary excerpt, four short evidence refs, artifact IDs/hashes and truncation indicators), excluded non-prompt provider bookkeeping from conservative prompt-byte admission, and returned surrounding original lines from document comparison. No root token allowance was increased. The strengthened oracle rejects the erroneous refund claim. A fresh baseline and two fresh delegated runs then passed, using the same ledger. Campaign headroom was explicitly reallocated to corrective verification; there was no reset or top-up.

## Production readiness

Production images were rebuilt and the app was started on **http://localhost:18000**. The deployed fake-only delegated CSV check passed: root `4867012a-f3fe-466b-9c85-0dd0b9ba8b1b`, one child, 76 exact downloaded bytes, zero live calls. The unrelated service on port 8000 was not changed. [toolkit-deployment.json](toolkit-deployment.json) records safe inspected metadata: API/worker are not privileged, have no Docker socket or host-root mounts, drop all capabilities and enable no-new-privileges. The API has no provider credential. The application worker retains the authorized provider credential; the broker has no provider credential and alone owns daemon access.

[acceptance-toolkits-production.json](acceptance-toolkits-production.json) records a fake-only public HTTP submission to the deployed images: a real child workflow executes CSV analysis in the sandbox and the downloaded bytes are checked against the fixture. Its synthetic run remains in application storage for inspection. OpenAPI: [openapi.json](openapi.json).

## Explicit limits and remaining validation scope

- One authenticated workspace; no multi-tenant principals, automatic compaction, recursive agents, arbitrary tool imports, networked Python, repository execution, or external publishing.
- Parallel specialists cannot select approval-requiring tools. Sequential mode handles root-owned child approvals. General overlapping approval clocks are not supported.
- Child limits come from registered agent configurations; there are no additional per-reference override fields. Evidence uses one-based text/file lines (CSV is also an immutable text artifact); there is no speculative general finding/measurement DSL.
- Tool snapshots are retained in run state with installed version-one handler code. Future handler removal requires retaining the old implementation or explicitly failing closed.
- Legacy builtin-only roots retain v1 workflow/history behavior. New toolkit features and explicit total-token limits use v2. Children never append transcripts to the parent session.
- Token reservations are conservative text/schema-byte allowances. Interrupted requests can retain unused reservations. Exactly-once billing is not claimed.
- Sandbox cancellation fences publication immediately; admitted jobs may run until their bounded deadline, with cleanup exposed separately. An unavailable broker leaves cleanup unverified/pending rather than claiming success. Container isolation shares the host kernel. Broker daemon access is a trusted operator risk.
- Worker restart at a persisted child approval and cancellation during child execution were fault-tested. The complete speculative crash matrix in the original plan—every instruction boundary around broker submit/collect, response commit, child-start acknowledgement and parent termination—was not exhaustively injected. Broker startup reconciliation and stable operation IDs are implemented; broader production soak/fault testing remains advisable.
- No claim is made that all model prose is validated. Server-created evidence and downloaded artifacts are the correctness anchors. Initial model/protocol failures are retained in the evidence.
