# Focused development checks

Start with saved results, then inspect the smallest trace that answers the current question.
The helper uses only Python's standard library and never invokes a model, test runner,
service or ledger writer. It excludes raw prompts, responses, command output and free-form
exception messages. It reports the first **recorded** failure, which may have been recovered
and is not necessarily the cause of a failed task. Missing and paginated evidence is flagged.

```bash
python3 developer_tools/report.py var/acceptance/completion-loop-v1/live.json
python3 developer_tools/report.py var/acceptance/completion-loop-v1/live.json --cell recovery
python3 developer_tools/report.py path/to/report.json --json --test-log path/to/pytest.log
```

Use the exact cell identifier in the summary. Three-model reports use identifiers such as
`gpt-5.6-luna/recovery`. Cell details include at most five recent operation summaries by
default (`--recent 0..10`); the evidence pointer identifies the relevant saved JSON object.
Exit status 0 means the report was read, not that its tasks passed. A reading/selection error
returns 2. Test-log summaries read only the last 64 KiB. Evidence reads are capped at 64 MiB.

## Validation sequence

1. State one unresolved failure and the evidence needed to explain it.
2. Read the summary; open only that case's relevant operation, context or diagnostic.
3. Replay the observed failure without paid calls, then implement the smallest general fix.
4. Run the affected tests during edits. Run required integration/regression checks once the
   change stabilizes; repeat only for relevant new changes or unresolved failures.
5. Validate with a small authorized live checkpoint, then the agreed comparison on fixed
   code and matching inputs. Preserve failures, limits and historical evidence.
6. Keep the working handoff short: objective, confirmed cause, changed files, test result,
   next action and evidence paths. Link older detail instead of copying it into every session.

Use Astra High for design and Astra Medium for implementation/tests as required by the
project. Keep roadmap/progress in PLAN.md and setup commands in README.md when integrating
this helper into the main workflow; no extra AGENTS.md rules are needed.

This standalone directory avoids the acceptance harness's source fingerprints for
`scripts/`, `agent_runtime/` and `config/`. Existing source files and instructions are not
modified. Run the helper's focused tests explicitly:

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider developer_tools/test_report.py
```
