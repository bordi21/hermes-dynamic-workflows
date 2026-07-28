# Hermes Dynamic Workflows

> **Claude-Code-style dynamic workflows for [Hermes Agent](https://github.com/NousResearch/hermes-agent).**

English | [简体中文](./README.zh-CN.md) | [日本語](./README.ja-JP.md)

You can now use **Dynamic Workflows** in Hermes: have the model write a sandboxed Python
script on the fly, execute it in the background runtime, and orchestrate large numbers
of independent subagents with `agent()/parallel()/pipeline()` — ideal for codebase
audits, large-scale migrations, and cross-validated research. Inspired by
[Dynamic Workflows in Claude Code](https://claude.com/blog/introducing-dynamic-workflows-in-claude-code).

https://github.com/user-attachments/assets/06ef3d0d-4d89-48c4-9851-e1cae690e9b0

## Quick Start

Install and enable in one line:

```bash
hermes plugins install lingjiuu/hermes-dynamic-workflows --enable
```

> Gateway users: run `hermes gateway restart` after installing.

Once it's installed, just tell Hermes "run a workflow that …" and you're set.

### Live Dashboard (optional, requires a separate step)

`hermes plugins install` only clones the plugin — it does not install its console
scripts, so the dashboard command has to be installed once separately:

```bash
python3 "${HERMES_HOME:-$HOME/.hermes}/plugins/dynamic-workflows/scripts/install-hermes-workflows.py"
# Installs to ~/.local/bin
```

Then, in **a separate terminal**, run `hermes-workflows` to open the interactive
dashboard, where you can watch the run list, per-phase/per-agent progress, and each
subagent's prompt and output in real time.

## Configuration (optional)

The plugin reads the following section from Hermes's `~/.hermes/config.yaml` (every key
can also be overridden via a `HERMES_DYNAMIC_WORKFLOWS_*` environment variable):

```yaml
plugins:
  entries:
    dynamic-workflows:
      dynamic_workflows:
        concurrency: 8                # Max concurrent agents (default: min(16, cpu-2))
        max_concurrency: 16           # Hard cap on concurrency
        max_agents: 1000              # Max total agents per run (runaway guard)
        workflow_timeout_seconds: 900 # Wall-clock timeout for the whole run (excludes paused time)
        child_timeout_seconds: 300    # Timeout for a single child agent
        blocked_child_toolsets: [workflow, workflows, delegation, code_execution, messaging, clarify]
                                      # Toolsets child agents are forbidden to use
        default_child_toolsets: [web, file, terminal, skills]
                                      # Default toolsets for child agents (used when no agentType is given)
        keep_worktrees: false         # Whether to keep each agent's git worktree (auto-cleaned by default)
        allow_model_override: true    # Whether agent(model=...) may override the model

        initial_orchestrator_model: inherit
        worker_model: inherit
        reviewer_model: inherit
        repair_worker_model: inherit
        final_orchestrator_model: inherit
        initial_orchestrator_agent_type: initial-orchestrator
        worker_agent_type: worker
        reviewer_agent_type: reviewer
        repair_worker_agent_type: repair-worker
        final_orchestrator_agent_type: final-orchestrator
                                      # Logical reviewed-workflow role routing

        require_launch_approval: true # Require confirmation before a top-level workflow launches (denied if nobody is online)
        child_approval_policy: inherit # Child agent approval policy: inherit|smart|deny|approve|ask
        ask_fallback: smart           # Fallback when "ask" has no one to reach: smart|deny|approve
        notify_on_complete: true      # Notify the originating CLI or gateway session on completion
        notify_result_preview_chars: 2000  # Truncation length (chars) for the result preview in notifications
```

For a canonical reviewed-workflow role, model precedence is: an explicit workflow
`model` override (including a phase model) → the role's configured model → the selected
agentType's model → the launching Hermes session model. `inherit` skips that level.
Provider-specific model names remain configuration values; orchestration code does not
hardcode providers or models.

## Script API

A workflow script is just a piece of async Python whose first statement is a literal
`meta`; after that you orchestrate child agents using the sandboxed globals:

```python
meta = {
    "name": "repo-audit",
    "description": "Parallel review, then adversarial verify",
    "phases": [{"title": "Review"}, {"title": "Verify"}],
}

# Each target flows through review → verify independently
# (pipeline has no barrier: A can be at verify while B is still at review)
findings = await pipeline(
    args["targets"],
    lambda t, _o, i: agent(f"Review for bugs: {t}", {"label": f"review:{i}", "phase": "Review"}),
    lambda r, _o, i: agent(f"Verify adversarially: {json.dumps(r)}", {"label": f"verify:{i}", "phase": "Verify"}),
)
return await agent("Synthesize the verified findings:\n" + json.dumps(findings))
```

- `agent(prompt, opts)` spawns a child agent; `opts` may include `schema` (enforce
  structured output), `model`, `agentType`, and `isolation="worktree"`.
- `pipeline` (default, no barrier) / `parallel` (with barrier) handle concurrency;
  `phase`/`log` report progress; `workflow()` runs a named workflow inline; `args` /
  `budget` access the input arguments and the token budget.

### Agent Type

Specify a child agent's type via `agentType` in the script; if omitted, it defaults to
`general-purpose` (full toolset):

| Type | Toolset | Description |
|------|---------|-------------|
| `general-purpose` | `*` (all safe tools) | Default; good for searching code, researching complex problems, and multi-step tasks |
| `explore` | Read-only (read_file, search_files, terminal) | Fast codebase exploration; good for locating files and searching keywords |
| `plan` | Read-only (read_file, search_files, terminal) | Software architecture design; outputs a step-by-step implementation plan |
| `verification` | web + file + terminal + browser | Verifies implementation correctness; runs build/test/lint to emit PASS/FAIL |
| `initial-orchestrator` | Read-only file + terminal | Creates bounded task packets plus separate worker and reviewer guidance |
| `worker` | `*` (all safe tools) | Executes exactly one scoped task packet and returns evidence without self-approval |
| `reviewer` | Read-only file + terminal | Evaluates one attempt and returns evidence-backed PASS, FAIL, or BLOCKED |
| `repair-worker` | `*` (all safe tools) | Performs a fresh, feedback-directed repair without weakening criteria |
| `final-orchestrator` | Read-only file + terminal | Validates the integrated result against the original objective |

The five reviewed-workflow names above are logical roles. Their underlying agentType
files and role models can be remapped through plugin configuration without changing
workflow code.

Agent types are resolved from three locations in priority order (on a name collision,
earlier locations override later ones):

1. `<project>/.hermes/dynamic-workflows/agents/*.md`  — project level, applies only to the current project
2. `~/.hermes/dynamic-workflows/agents/*.md`          — user level, applies globally
3. `<plugin>/hermes_dynamic_workflows/agents/*.md`    — built-in defaults

To add a custom type, create a new `.md` file under directory 1 or 2 in the following format:

```markdown
---
name: my-agent
description: "A short description of what this agent is for; the model uses it to automatically pick the right agent."
model: inherit
toolsets: [web, file, terminal]
---

Write the agent's system prompt here to guide its behavior, style, and constraints.
```

`name` and `description` are required; `model` defaults to `inherit` (inherits the
current session's model); `toolsets` defaults to the global `default_child_toolsets`;
optional fields also include `allowed_tools`, `disallowed_tools`, and `isolation`.

At runtime the plugin persists the script and the full execution trace (transcript) of
every child agent, and injects a `<task-notification>` into the conversation on
completion — no polling required. Use `/workflows` to view history and details.

## Deep Dive

The target planner → worker → reviewer → repair → final-validation behavior and all
structured handoff invariants are defined in the [Canonical Orchestration Workflow](./WORKFLOW_CONTRACT.md).

For implementation details (core execution path, tools and full call results, prompt
cache, concurrency and limits, permission governance, rebuilding transcripts from
`state.db`, sandboxing, resume…), see [TECHNICAL.md](./TECHNICAL.md).

## License

[MIT](./LICENSE)
