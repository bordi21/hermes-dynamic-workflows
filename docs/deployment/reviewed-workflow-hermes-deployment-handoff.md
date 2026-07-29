# Reviewed Workflow Hermes Deployment Handoff

Use this only after the repository execution report supplies the exact approved Step 8 branch-head SHA. Replace `APPROVED_COMMIT_SHA` below with that full SHA before execution. Do not deploy a branch name or an unverified moving ref.

## Ready-to-run Hermes prompt

```text
Deploy and live-verify the reviewed-workflow repair from `bordi21/hermes-dynamic-workflows` at exact commit `APPROVED_COMMIT_SHA`.

Before changing the installation, report the currently installed plugin path and SHA. Fetch the repository and verify that `APPROVED_COMMIT_SHA` exists and is the commit being installed; stop if the SHA differs or cannot be verified. Install or update only this plugin at that exact commit. Preserve the existing Hermes configuration, profiles, memory, tools, integrations, approvals, command guards, telemetry, persistence, accounting, resume cache, and worktree behavior. Restart the gateway only when the installation mechanism requires it, and report whether a restart occurred.

Run exactly three live canaries through the installed canonical `reviewed-workflow`:
1. a read-only request against one named file;
2. a small precise modification with a focused check and reviewer PASS before integration;
3. a reviewer FAIL followed by a fresh repair, a second review, and final validation.

For every canary, report the run ID, child session IDs, phase transitions, scoped packet boundaries, prompts and tool activity, non-progress interventions if any, worker result, reviewer verdict, repair lineage, integration status, final-validation verdict, deterministic terminal report, and the exact installed plugin SHA. Confirm that child conversations remained isolated and that information crossed roles only through structured packets and bounded runtime metadata.

Do not merge branches, alter unrelated plugins or profiles, weaken approvals or command guards, or claim live success from repository tests. If any canary is BLOCKED or fails, stop and report the exact evidence without forcing PASS.
```
