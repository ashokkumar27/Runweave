# Validation and evidence

**Development build—not production-ready.** Latest held-code live verification on 2026-09-20 accepted **11/15** cases, up from 1/15 baseline. Luna direct and all three parallel cases failed. Output bytes alone are not accepted completion. These single-run fixture matrices do not establish general reliability or a statistical model ranking. No production rollout was performed for this work.

## Evidence index

- [Historical plan through 2026-09-20](history/plan-through-2026-09-20.md): preserved scope, decisions and outcomes; past approvals do not authorize new actions.

- [Completion model findings](completion-models-findings.md): latest matrices, receipts, child outcomes, limitations and raw evidence links. Baseline used 106/216 calls; verification used 96/216.
- [Completion-loop validation](completion-loop-validation.md): earlier correction/replay checks; live campaign stopped at 28/72 calls with only direct passing.
- [Model comparison](model-comparison-findings.md): historical 0/12 acceptance, 58/60 calls.
- [Lightweight confidence](lightweight-confidence-findings.md): earlier bounded campaign, 19/32 calls.
- [General runtime v3](general-runtime-v3-validation.md): fake/service checks, rollout history and live limitations, 19/24 calls.
- [Toolkit validation](toolkit-validation.md): artifact/subagent/recovery evidence, 48/50 calls; [API consistency evidence](acceptance-toolkit-api-consistency.json).
- [Original validation](validation.md): initial lifecycle and denial-policy evidence, 16/20 calls.
- [Historical OpenAPI export](openapi.json): retained evidence; the running app serves its current contract at `/openapi.json`.

The latest broad unpaid service run passed 220 tests with 2 paid skips **before final payload compaction**. Subsequent checks covered 40 affected tests and four captured SDK/backend regressions. Final SDK/backend preflight passed 15/15 fake cells plus five cross-model payload-parity checks. These are historical results, not checks rerun during documentation cleanup.

## Local checks

Common unpaid checks (service tests require configured local dependencies):

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run pytest -q --integration
```

Broker-dependent suites run sequentially with isolated schemas/queues and broker 18091. Exact latest focused checks are retained here because the historical findings refer back to README commands:

```bash
uv run pytest -q tests/test_completion_models.py
uv run pytest -q --integration tests/test_completion_models_replay.py
uv run python -m scripts.completion_models --phase completion-models-baseline-v1
uv run python -m scripts.completion_models --phase completion-models-verified-v1
```

## Campaign restrictions

**Paid campaigns are historical evidence, not startup instructions. No further paid phase is authorized by this cleanup.** Lightweight, model-comparison, completion-loop and both completion-model phases are terminal. Do not rerun/resubmit terminal cells or spend unused allowances. Post-live changes need separately authorized evaluation.

Never reset, relocate, replace or transfer a ledger to extend a cap. Preserve all retained evidence, downloads, wire captures, source hashes and terminal markers. Earlier ledgers remain separate: `/tmp/agent-runtime-acceptance-budget.sqlite` (16/20), `var/acceptance/toolkits-subagents-v1.sqlite` (48/50), and `var/acceptance/general-runtime-v3.sqlite` (19/24). Do not rerun the whole toolkit live suite; only two original slots remain. Unused slots are not new authorization.

The following completion-model commands were executed once after their strict gates. **Both phases are terminal; these commands must not be used to restart them.**

```bash
uv run python -m scripts.completion_models --phase completion-models-baseline-v1 --live
uv run python -m scripts.completion_models --phase completion-models-verified-v1 --live
```

The retained [baseline evidence](../var/acceptance/completion-models-baseline-v1/live.json) and [verified evidence](../var/acceptance/completion-models-verified-v1/live.json) include one immutable root per model-qualified cell. Reinvocation is refused. Preserve phase ledgers and markers; do not authorize a third phase by changing paths or resetting state. Other historical commands and outcomes remain in the evidence documents linked above.
