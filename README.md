# Hermes Dynamic Workflow

> **One Hermes profile. Many bounded workers. Strong review. One evidence-backed result.**

Hermes Dynamic Workflow is a fork of
[`lingjiuu/hermes-dynamic-workflows`](https://github.com/lingjiuu/hermes-dynamic-workflows)
for building reliable multi-agent execution inside
[Hermes Agent](https://github.com/NousResearch/hermes-agent).

The project keeps Hermes as the runtime and control surface. It does not introduce a
second orchestration engine, a separate agent platform, or a second state store.

## Project mission

The target default flow is:

```text
strong parent
  → bounded task decomposition
  → one cheaper worker per task
  → stronger reviewer
      PASS    → accepted
      FAIL    → fresh repair worker with feedback
      BLOCKED → surfaced honestly
  → integration of accepted results
  → final verification
  → one evidence-backed result
```

The workflow starts from one Hermes profile. Planner, workers, reviewers, repair
workers, and integrator are ephemeral child agents or lightweight `agentType`
presets—not separately managed Hermes profiles.

## Current foundation

The inherited runtime already provides:

- sandboxed async Python workflows;
- `agent()`, `pipeline()`, `parallel()`, nested `workflow()`, phases, and progress logs;
- independent Hermes `AIAgent` children;
- per-agent model, toolset, agent type, schema, and worktree options;
- background execution with run IDs and task IDs;
- structured output validation;
- concurrency, timeout, token-budget, and runaway guards;
- launch and command approvals through Hermes;
- persisted scripts, run snapshots, journals, outputs, and child transcripts;
- `/workflows` status, completion notifications, and the `hermes-workflows` TUI;
- pause, resume, stop, restart, transcript export, and content-addressed result reuse.

The reviewed decomposition → worker → reviewer → repair → integration flow is the
project direction. It must be implemented by extending the existing runtime, not by
building parallel machinery.

## Operating principles

### One profile, scoped children

The launching Hermes profile owns the run. Child agents inherit the runtime connection
and approved tool surface, but they receive fresh sessions and scoped task packets.
They do **not** automatically inherit the parent conversation, memory, SOUL, or project
context files.

### Existing function first

Before adding code, find the canonical function that already owns the responsibility.

- If it already performs the job, edit or extend it.
- Do not create a parallel implementation, duplicate wrapper, or second source of truth.
- Extract a shared service only when the mechanic is genuinely reused.
- Refactor incrementally: migrate one caller, verify it, then migrate the rest.

### Actions and Services

The architecture follows a two-layer responsibility split:

- **Actions** own meaning: orchestration, policy, state transitions, retry decisions,
  failure classification, and user-facing outcomes.
- **Services** own reusable mechanics: storage, child execution, transcript export,
  validation, worktree management, and other composable operations.

Services use explicit inputs, structured outputs, and explicit failures. They do not
silently mutate domain state or decide workflow policy.

### Review is a gate

A reviewer is not a summarizer. Each task must end with a structured verdict:

```text
PASS | FAIL | BLOCKED
```

The verdict includes evidence and actionable feedback. Only accepted work may be
integrated. A successful tool call or fluent answer is not proof of correctness.

### Preserve the control plane

Run records, snapshots, `journal.jsonl`, transcripts, notifications, `/workflows`, and
the TUI are the canonical telemetry. New reviewed-task state must extend these surfaces
rather than create a side database or disconnected dashboard model.

## Source map

These files form the project knowledge layer:

| File | Responsibility |
|---|---|
| `CHATGPT_PROJECT_INSTRUCTIONS.md` | Persistent ChatGPT project-agent kernel |
| `README.md` | Project identity, mission, operating contract, usage, and boundaries |
| `TECHNICAL.md` | Agent roles, runtime architecture, state, tools, controls, and extension rules |
| `plugin.yaml` | Hermes plugin metadata |
| `hermes_dynamic_workflows/entry.py` | Hermes registration entrypoint |
| `hermes_dynamic_workflows/adapters/` | Hermes-facing workflow, command, hook, and task adapters |
| `hermes_dynamic_workflows/run/` | Background lifecycle, transcripts, completion artifacts, and notifications |
| `hermes_dynamic_workflows/engine/` | Script validation, execution, workflow API, cache, and runtime semantics |
| `hermes_dynamic_workflows/child/` | Child-agent construction, agent types, tools, and workspace isolation |
| `hermes_dynamic_workflows/storage/` | Persistent run records and control-channel storage |
| `hermes_dynamic_workflows/tui/` | Interactive workflow monitor and controls |
| `hermes_dynamic_workflows/agents/` | Built-in `agentType` definitions |
| `tests/` | Behavioral contracts and regression protection |

Read `TECHNICAL.md` before changing orchestration, agents, persistence, approvals,
resume, telemetry, or dashboard behavior.

## Installation

Install this fork:

```bash
hermes plugins install bordi21/hermes-dynamic-workflows --enable
```

Gateway users should restart Hermes after installation:

```bash
hermes gateway restart
```

Then ask Hermes naturally:

```text
Run a workflow that audits this repository in parallel and verifies every finding.
```

Top-level workflow launch approval is enabled by default.

## Live progress

### In Hermes

Use:

```text
/workflows
```

It shows recent runs, agent status, model, token use, tool calls, duration, and errors.

When a run finishes, the originating session receives a `<task-notification>` with the
terminal status, result preview, usage, output path, and recovery location.

### Interactive dashboard

The plugin clone does not automatically install the console script. Install it once:

```bash
python3 "${HERMES_HOME:-$HOME/.hermes}/plugins/dynamic-workflows/scripts/install-hermes-workflows.py"
```

Open the monitor in a separate terminal:

```bash
hermes-workflows
```

The TUI shows sessions, runs, phases, agents, prompts, recent tool activity, outcomes,
models, tokens, tool calls, and duration.

Controls:

```text
p  pause / resume
x  stop
r  restart as a new run
s  save a Markdown transcript
```

Pause is cooperative: active children may finish, but no new child or next pipeline
stage starts until the run resumes.

## Configuration

Configuration lives under the plugin entry in `~/.hermes/config.yaml`. Every setting
also supports a `HERMES_DYNAMIC_WORKFLOWS_*` environment-variable override.

```yaml
plugins:
  entries:
    dynamic-workflows:
      dynamic_workflows:
        concurrency: 8
        max_concurrency: 16
        max_agents: 1000
        workflow_timeout_seconds: 900
        child_timeout_seconds: 300

        blocked_child_toolsets:
          - workflow
          - delegation
          - code_execution
          - memory
          - messaging
          - clarify

        default_child_toolsets:
          - web
          - file
          - terminal
          - skills

        keep_worktrees: false
        allow_model_override: true

        require_launch_approval: true
        child_approval_policy: inherit
        ask_fallback: smart

        notify_on_complete: true
        notify_result_preview_chars: 2000
```

Role-based planner/worker/reviewer/integrator model routing is a project goal. Until a
canonical role configuration is added, current workflows can select a model through
`agent(model=...)`, phase metadata, or `agentType` frontmatter.

## Workflow API

A workflow is async Python whose first statement is a literal `meta` dictionary:

```python
meta = {
    "name": "reviewed-audit",
    "description": "Audit targets in parallel and verify the findings",
    "phases": [
        {"title": "Audit"},
        {"title": "Review"},
    ],
}

findings = await pipeline(
    args["targets"],
    lambda target, _original, index: agent(
        f"Audit this target and return evidence: {target}",
        {
            "label": f"worker:{index}",
            "phase": "Audit",
            "model": args.get("worker_model"),
        },
    ),
    lambda finding, target, index: agent(
        "Review the finding against the target. Reject unsupported claims.\n\n"
        + json.dumps({"target": target, "finding": finding}),
        {
            "label": f"reviewer:{index}",
            "phase": "Review",
            "agentType": "verification",
            "model": args.get("reviewer_model"),
        },
    ),
)

return findings
```

Available globals:

| Global | Purpose |
|---|---|
| `agent(prompt, opts)` | Spawn one child agent |
| `pipeline(items, stages...)` | Move each item independently through stages, without a global barrier |
| `parallel(thunks)` | Run calls concurrently and wait for the full batch |
| `phase(title)` | Start or select a progress phase |
| `log(message)` | Add visible workflow progress |
| `workflow(name_or_ref, args)` | Run one nested named workflow |
| `args` | Launch arguments |
| `budget` | Per-run token budget view |

A child can request:

- `label`
- `phase`
- `model`
- `agentType`
- `schema`
- `isolation="worktree"`

See `TECHNICAL.md` for exact runtime semantics.

## Agent types

Built-in types:

| Type | Intended use |
|---|---|
| `general-purpose` | Broad tool-enabled execution |
| `explore` | Read-only code and repository exploration |
| `plan` | Read-only implementation planning |
| `verification` | Build, test, lint, inspect, and return verification evidence |

Resolution order:

1. `<project>/.hermes/dynamic-workflows/agents/`
2. `~/.hermes/dynamic-workflows/agents/`
3. built-ins under `hermes_dynamic_workflows/agents/`

Example:

```markdown
---
name: reviewer
description: Evidence-driven reviewer for child-task results.
model: inherit
toolsets: [web, file, terminal]
---

Return PASS, FAIL, or BLOCKED. Cite concrete evidence and provide actionable feedback.
```

Agent types are lightweight role definitions. They are not Hermes profiles.

## Boundaries

This project does not:

- replace Hermes;
- copy the parent conversation into every child;
- treat synthesis as verification;
- force success when evidence is missing;
- bypass Hermes approval governance;
- promise automatic crash continuation without end-to-end proof;
- create a web dashboard backed by a second state model;
- add LangGraph or another orchestrator without a demonstrated missing capability.

## Development status

This fork currently preserves the upstream runtime. The next implementation milestone is
to define and add the smallest reviewed default workflow using existing canonical
functions and telemetry.

For active decisions, verified state, and tasks, use the project L3 memory at:

```text
bordi21/chatgpt-memory/projects/hermes-dynamic-workflows/
```

## Upstream and license

Upstream: [`lingjiuu/hermes-dynamic-workflows`](https://github.com/lingjiuu/hermes-dynamic-workflows)

License: [MIT](./LICENSE)
