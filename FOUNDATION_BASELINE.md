# Foundation Baseline — T00 to T02

- Base commit: `c67d873941cf4d309eda2b2bf6ac9f534f378f0c`
- Branch: `refactor/t00-t02-foundation`
- Python: `3.11`
- Test command: `python -m unittest discover -s tests -v`
- Initial baseline: `FAIL` — 243 tests, one pre-existing failure
- Stabilized baseline: `PASS` — 243 tests
- Post-change suite: `PASS` — 247 tests
- Verification workflow run: `30391596987`

## T00 — Executable baseline

The original suite ran before T01/T02 changes and exposed one pre-existing Linux-only defect. Bundled agent-type files use lowercase filenames and frontmatter names, while the public resolver and existing tests also use names such as `Plan` and `Explore`. The fallback comparison was case-sensitive, so `resolve_agent_type("Plan")` returned `None`.

T00 changed only the fallback name comparison to use `casefold()`. The complete pre-existing suite then passed 243/243 before T01/T02 were applied.

## T01 — Hermes profile inheritance

Workflow children now instantiate fresh `AIAgent` sessions with profile context files and memory enabled. Role-specific `agentType` instructions remain additive through the ephemeral system prompt, while task-specific run context remains isolated in the child's scoped first user message. The default blocked-toolset list no longer blocks `memory`.

Repository tests inspect the actual constructor arguments supplied to `AIAgent`. This is code-level proof; a live installed-Hermes SOUL/memory canary remains a separate runtime verification step.

## T02 — Structured package schemas

Nine canonical Draft 2020-12 schemas define `PlanPackage`, `TaskPackage`, `WorkerResultPackage`, `ReviewRequestPackage`, `ReviewVerdictPackage`, `RepairPackage`, `IntegrationResultPackage`, `FinalValidationPackage`, and `FinalReportPackage`.

The schemas use the plugin's existing structured-output validation path. Tests require planner-authored reviewer guidelines, strict `PASS`/`FAIL`/`BLOCKED` verdicts, and repair lineage containing the original task, previous result, and reviewer feedback.

## Verification boundary

GitHub Actions proves the repository suite is green after these changes. It does not prove that this branch is installed on the VPS or that the live Hermes profile has passed context and memory canaries.
