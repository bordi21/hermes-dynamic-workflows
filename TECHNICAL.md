# Hermes Dynamic Workflow — Agent System and Runtime Contract

This document is the canonical L2 source for agents, tools, orchestration, review,
execution state, persistence, approvals, recovery, and extension boundaries.

Use `README.md` for project identity and user-facing operation. Use this file when a
change affects how work is decomposed, executed, reviewed, controlled, observed, or
recovered.

## 1. System model

Hermes remains the host agent and the single control plane.

```text
User
  ↓
Launching Hermes profile
  ↓ workflow tool
WorkflowRunManager
  ↓
sandboxed workflow script
  ↓
WorkflowAPI
  ├── agent()
  ├── pipeline()
  ├── parallel()
  └── workflow()
        ↓
HermesChildAgentRunner
        ↓
independent Hermes AIAgent children
        ↓
tools / workspace / structured result
```

A workflow run is not a second Hermes profile. It is a background execution owned by
the launching Hermes process, with persisted state and multiple fresh child sessions.

## 2. Current actors

| Actor | Current responsibility |
|---|---|
| Launching Hermes agent | Understands the user request, writes or selects a workflow, requests launch, and receives completion |
| Workflow script | Expresses deterministic orchestration and control flow |
| `WorkflowRunManager` | Owns launch approval, run lifecycle, persistence, background thread, completion, and controls |
| `WorkflowAPI` | Implements workflow semantics such as `agent`, `pipeline`, `parallel`, phases, logs, nesting, and budget |
| `HermesChildAgentRunner` | Constructs and runs independent Hermes `AIAgent` children |
| Child `AIAgent` | Executes one scoped prompt with the allowed tools and selected model |
| `agentType` | Supplies reusable role instructions, tool policy, model default, and isolation default |
| Reviewer child | Currently just a child selected by workflow logic; no universal reviewed-flow contract exists yet |
| TUI and `/workflows` | Read persisted state and transcripts; expose progress and run-level controls |

## 3. Target project roles

The fork will add a canonical reviewed workflow without requiring separately managed
profiles.

| Role | Required behavior |
|---|---|
| Parent / Orchestrator | Resolve the objective, decompose it into bounded tasks, define dependencies and acceptance criteria |
| Worker | Execute exactly one task packet, produce a result and evidence, and avoid expanding scope |
| Reviewer | Evaluate one worker result against the task packet and return `PASS`, `FAIL`, or `BLOCKED` |
| Repair worker | Run in a fresh child session with the original packet, prior attempt, and reviewer feedback |
| Integrator | Combine only accepted results and resolve controlled merge or composition concerns |
| Final reviewer | Verify the integrated result against the original objective and evidence |

These are logical roles. They may be implemented through `agentType`, workflow metadata,
schemas, and model routing. They are not durable Hermes profiles.

## 4. Context inheritance contract

A child is a real Hermes `AIAgent`, but it is intentionally not a clone of the parent
conversation.

The child runtime can inherit:

- provider and API endpoint;
- credentials and credential pool;
- current model and fallback model;
- token limits;
- reasoning configuration and service tier;
- selected toolsets;
- Hermes command approval behavior;
- the current workspace or an isolated worktree.

The child does not automatically inherit:

- the parent conversation history;
- Hermes memory;
- project context files;
- SOUL or identity documents;
- unstated assumptions accumulated by the parent.

The runner currently creates children with `skip_context_files=True` and
`skip_memory=True`. The workflow must therefore pass the necessary context explicitly.

### Task packet

Each worker-facing packet should contain only what the task needs:

```text
task ID
objective
workspace and relevant paths
inputs and dependencies
constraints
allowed mutations
acceptance criteria
required evidence
expected output schema
```

Reviewer packets additionally include the worker result and evidence. Repair packets
also include the previous attempt and reviewer feedback.

Do not solve missing context by copying the full parent transcript into every child.

## 5. Model routing

Current runtime model selection can come from:

1. explicit `agent(..., {"model": "..."})`;
2. `agentType` frontmatter;
3. phase metadata;
4. inherited parent model.

The project target is role-based configuration for parent, worker, reviewer, repair,
integrator, and final reviewer. The configuration must:

- remain provider-neutral;
- use the existing config-loading path;
- preserve explicit per-call overrides where allowed;
- avoid hardcoded model names in workflow logic;
- expose the selected model in canonical telemetry.

Do not create a second configuration file when the current Hermes plugin configuration
can be extended.

## 6. Agent types

Agent types are lightweight reusable child definitions resolved by
`hermes_dynamic_workflows/child/presets.py`.

Supported formats:

```text
.md
.yaml
.yml
.json
```

Resolution precedence:

1. `<project>/.hermes/dynamic-workflows/agents/`
2. `~/.hermes/dynamic-workflows/agents/`
3. `hermes_dynamic_workflows/agents/`

An `AgentTypeSpec` may define:

- name;
- description;
- instructions;
- model;
- toolsets;
- allowed tools;
- disallowed tools;
- isolation.

Built-in types currently include:

- `general-purpose`;
- `explore`;
- `plan`;
- `verification`.

Agent types should define stable role behavior. Per-task facts belong in the first user
message, not the system prompt. Keeping same-role system prompts stable also preserves
cross-child prompt-cache reuse.

## 7. Core execution path

The main agent calls the `workflow` tool.

### Launch

`WorkflowRunManager.start_from_params`:

1. resolves `script`, `scriptPath`, or named workflow;
2. parses and validates the script;
3. extracts the literal first-statement `meta`;
4. requests top-level launch approval;
5. creates Run ID and Task ID;
6. persists script and initial run record;
7. captures parent runtime and session context;
8. starts a background daemon thread;
9. returns synchronously with run metadata.

The tool returning successfully means the run was launched. It does not mean the work
completed.

### Runtime

The background thread:

1. builds `HermesChildAgentRunner`;
2. transitions the run to `running`;
3. invokes `run_workflow`;
4. executes the validated script with restricted globals;
5. writes snapshots and journal events on state changes;
6. exports active child transcripts;
7. records `completed`, `failed`, `stopped`, or another terminal state;
8. writes final output and transcripts;
9. sends the completion notification.

### Child call

`await agent(...)` flows through:

```text
WorkflowAPI.agent
  → reserve agent record
  → resolve model / agentType / tools / isolation
  → concurrency slot
  → HermesChildAgentRunner.run
  → fresh AIAgent session
  → child tools and workspace
  → text or schema-validated object
  → journal + snapshot + cache
```

## 8. Workflow script contract

A workflow script is async Python. The first statement must be a pure literal:

```python
meta = {
    "name": "workflow-name",
    "description": "What this workflow does",
    "phases": [
        {"title": "Build"},
        {"title": "Review"},
    ],
}
```

Required:

- `meta.name`;
- `meta.description`.

Optional:

- `meta.whenToUse`;
- `meta.phases`.

The script body can use top-level `await` and `return`. It must not define its own
`workflow()` function.

### Exposed globals

| Global | Contract |
|---|---|
| `agent(prompt, opts=None)` | Spawn one child; return text, a validated object, or `None` when skipped |
| `pipeline(items, stage1, ...)` | Run each item independently through all stages; no global stage barrier |
| `parallel(thunks)` | Run calls concurrently and wait for all submitted calls |
| `phase(title)` | Select or create a visible phase |
| `log(message)` | Append bounded progress text |
| `workflow(name_or_ref, args=None)` | Run one nested workflow inline |
| `args` | Launch arguments passed verbatim |
| `budget` | Read total, spent, and remaining run tokens |

Common `agent` options:

```text
label
phase
model
agentType
schema
isolation
```

Nested workflows share the parent run's concurrency, stop signal, budget, and agent
count. Nesting is limited to one level.

## 9. Pipeline and parallel semantics

Use `pipeline` when every item should advance independently through several stages.

```text
item A: worker → reviewer → repair
item B: worker ─────────→ reviewer
item C: worker → blocked
```

A later stage for item A may begin while item B is still in an earlier stage.

Use `parallel` when the caller needs a batch barrier before continuing.

A child failure inside `pipeline` or `parallel` currently becomes `None` for that item
and is logged. Reviewed workflows must not confuse `None` with success. They should
classify it explicitly as failure or blocked state.

## 10. Structured output and review contract

When `schema` is supplied, the runner temporarily registers the child-only
`structured_output` tool. The child must call it before finishing.

The runtime:

- validates against JSON Schema;
- keeps the same child session for correction attempts;
- allows at most five structured-output attempts;
- returns the validated object to the workflow;
- records validation metadata in agent state.

The canonical reviewer schema should be narrow and fail closed, for example:

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["verdict", "evidence", "feedback"],
  "properties": {
    "verdict": {
      "type": "string",
      "enum": ["PASS", "FAIL", "BLOCKED"]
    },
    "evidence": {
      "type": "array",
      "items": {"type": "string"}
    },
    "feedback": {
      "type": "string"
    }
  }
}
```

Semantics:

- `PASS`: acceptance criteria are satisfied and supported by evidence;
- `FAIL`: the task is repairable and feedback identifies what must change;
- `BLOCKED`: required information, permission, dependency, or environment is unavailable.

Never:

- default an absent verdict to `PASS`;
- force a review transition;
- treat schema validity as correctness;
- label synthesis as verification;
- integrate failed or blocked work.

## 11. Bounded repair

A failed review may trigger a fresh repair child.

The repair input must include:

```text
original task packet
previous result
previous evidence
review verdict
review feedback
attempt number
remaining retry budget
```

Rules:

- retries are bounded;
- each attempt must be materially informed by feedback;
- retry count is visible in canonical telemetry;
- repeated identical attempts must stop;
- exhausted retries become an explicit terminal failure or blocked result;
- a repair result must pass review before integration.

Resume cache fingerprints include the prompt and relevant options. Repair prompts must
therefore change when the feedback or attempt changes.

## 12. Workspaces, worktrees, and integration

Default isolation is the shared current workspace.

`isolation="worktree"` creates an isolated Git worktree and branch for a child. Use it
when concurrent agents may modify overlapping repository state.

Worktree isolation prevents checkout conflicts. It is not a security sandbox.

Current behavior:

- a clean worktree can be removed automatically;
- a worktree with changes is retained;
- the plugin does not universally guarantee semantic merging of child changes.

The integrator must:

- use only accepted child outputs;
- inspect actual diffs and dependencies;
- merge in a deterministic order;
- surface conflicts;
- run final validation;
- avoid overwriting unrelated changes.

For read-only work, shared workspace concurrency is usually sufficient.

## 13. State and persistence

The run record is the canonical persisted state.

Important fields include:

```text
runId
taskId
status
createdAt / startedAt / finishedAt
cwd
workflowSessionId
controlOwner
scriptPath
transcriptDir
journalFile
source
resumeFromRunId
restartedFromRunId
args
tokenBudget
result
error
workflow snapshot
agentCache
outputFile
transcript files
```

Current active statuses include:

```text
queued
running
paused
stopping
```

Current terminal statuses include:

```text
completed
failed
error
stopped
```

Reviewed-task lineage, dependencies, verdicts, retry attempts, and integration state
must be added to this canonical model or its workflow snapshot—not placed in a second
database.

## 14. On-disk artifacts

For a sanitized working directory and Hermes session:

```text
~/.hermes/projects/<cwd>/<sessionId>/workflows/scripts/<name>-<runId>.py

~/.hermes/projects/<cwd>/<sessionId>/subagents/workflows/<runId>/
  journal.jsonl
  agent-<sessionId>.jsonl
  agent-<sessionId>.meta.json
```

The run store also persists the run record and output artifact.

`journal.jsonl` is the append-only execution event stream. It includes child start,
activity, approval, result, skip, and error events.

Child messages originate in Hermes `SessionDB`. The transcript exporter reconstructs
compaction lineage and emits viewable JSONL transcripts in real time.

## 15. Observability

Canonical observability surfaces:

- run snapshot;
- `journal.jsonl`;
- exported child transcripts;
- `/workflows`;
- `hermes-workflows`;
- completion notification;
- final output file;
- saved Markdown transcript.

Per child, preserve:

- ID and label;
- logical phase;
- status;
- prompt;
- model;
- agent type;
- isolation;
- token counts;
- cache counts;
- tool-call count;
- duration;
- recent activity;
- structured-output status;
- result;
- error.

The live transcript exporter refreshes active child transcripts approximately every
0.5 seconds and performs a final validated rebuild at run termination.

A future web interface must read the same state and use the same control channel as the
TUI.

## 16. Controls

The standalone TUI sends owner-scoped, expiring requests to the Hermes process that
owns the run. It does not open a local network port.

Current controls:

| Control | Behavior |
|---|---|
| Stop | Set stop signal and interrupt active children |
| Pause | Prevent new children and later pipeline stages from starting |
| Resume | Reopen the pause gate |
| Restart | Stop if needed and launch a brand-new run from saved script and args |
| Save | Export a Markdown transcript |

Pause is cooperative. Children already running may finish. Paused time is excluded
from the run deadline.

The backend also supports skipping one active child. The current TUI does not expose a
dedicated skip key.

## 17. Completion notification

On terminal state, the originating session can receive:

```xml
<task-notification>
  <task-id>...</task-id>
  <output-file>...</output-file>
  <status>completed|failed|stopped|...</status>
  <summary>...</summary>
  <result>...</result>
  <recovery>...</recovery>
  <usage>
    <agent_count>...</agent_count>
    <subagent_tokens>...</subagent_tokens>
    <tool_uses>...</tool_uses>
    <duration_ms>...</duration_ms>
  </usage>
</task-notification>
```

A completion notification reports the terminal run state. It is not independent proof
that the output is correct.

## 18. Resume, restart, and crash recovery

These terms are different:

- **Resume from run**: launch a new execution with `resumeFromRunId`; unchanged
  content-addressed child calls reuse cached results.
- **Pause/resume**: continue the same live run through its pause gate.
- **Restart**: create a new Run ID from the saved script and args.
- **Crash recovery**: reconstruct and continue an interrupted process after Hermes or
  the container dies.

The runtime persists enough material for inspection and cache-assisted relaunch.
Automatic crash continuation must not be claimed until verified end to end.

When editing a workflow before `resumeFromRunId`, preserve early stable child calls
when possible. Changes early in the dependency chain reduce downstream cache reuse.

## 19. Concurrency and hard limits

Each run owns a semaphore.

Current guards:

- configured concurrency, capped by `max_concurrency`;
- `max_agents`;
- workflow wall-clock timeout, excluding paused time;
- per-child timeout;
- maximum loop iterations;
- optional per-run token budget;
- stop signal.

Run-level hard stops cannot be swallowed by workflow `except Exception`.

The token budget counts completed child input, output, and reasoning tokens. Once
exhausted, new `agent()` calls fail closed.

## 20. Sandbox and determinism

Workflow scripts are AST-validated and executed with restricted globals.

Control flow allowed:

```text
if
for
while
try / except Exception
top-level await
return
```

Capabilities rejected include:

```text
imports
direct file/process/network access
dunder traversal
eval / exec / compile / open / getattr
class definitions
dynamic call targets
time and randomness APIs
bare except
except BaseException
```

Time and randomness are excluded because they break deterministic resume fingerprints.

This is a guardrail, not a strong security boundary. True isolation would require a
separate process and RPC boundary.

## 21. Permission governance

The plugin reuses Hermes approval infrastructure.

### Launch approval

Top-level workflow launch approval is enabled by default.

- CLI can confirm synchronously.
- Gateway can present approve/deny interaction.
- An unattended launch without a valid interactive path is denied.
- Nested workflows inherit the already approved parent run.

### Child command approval

Child terminal operations still pass through Hermes command guards.

`child_approval_policy` controls what happens when a background child reaches a command
that would normally require human interaction:

```text
inherit
smart
deny
approve
ask
```

`ask_fallback` controls unattended fallback for `ask`.

The permanent allowlist and hardline restrictions remain authoritative.

### Hook

The `pre_tool_call` hook restores reliable approval behavior for detached background
threads. Do not bypass or duplicate it.

## 22. Actions and Services

Actions and Services are responsibility layers, not necessarily literal directory names.

### Actions own

- the meaning of the flow;
- decomposition and dependency policy;
- status transitions;
- retry and repair decisions;
- failure classification;
- approval requirements;
- user-facing outcomes;
- what gets integrated.

Likely action boundaries include Hermes adapters, run lifecycle decisions, and workflow
orchestration semantics.

### Services own

- child execution;
- persistent storage;
- transcript export;
- schema validation;
- caching;
- worktree creation and cleanup;
- control request transport;
- other reusable operational mechanics.

Services must:

- accept explicit inputs;
- return structured outputs;
- surface errors explicitly;
- avoid deciding domain state;
- remain composable.

### Existing-function-first rule

Before writing a function:

1. search by responsibility, not only by desired function name;
2. identify the canonical owner;
3. edit or extend that function;
4. update its existing callers and tests;
5. extract a shared service only when mechanics repeat;
6. migrate one caller and verify before expanding.

Do not add:

- a second run manager;
- a second child runner;
- a parallel transcript exporter;
- a second config loader;
- a second workflow-state store;
- wrappers that only rename existing functions;
- a god service that hides policy and mechanics together.

## 23. Canonical source ownership

| Responsibility | Canonical location |
|---|---|
| Plugin registration | `hermes_dynamic_workflows/entry.py` |
| Workflow tool adapter | `hermes_dynamic_workflows/adapters/workflow.py` |
| Stop adapter | `hermes_dynamic_workflows/adapters/task_stop.py` |
| Slash command | `hermes_dynamic_workflows/adapters/commands.py` |
| Approval hook | `hermes_dynamic_workflows/adapters/hooks.py` |
| Background lifecycle and controls | `hermes_dynamic_workflows/run/manager.py` |
| Transcript reconstruction/export | `hermes_dynamic_workflows/run/transcripts.py` |
| Script parsing and AST policy | `hermes_dynamic_workflows/engine/sandbox.py` |
| Script execution | `hermes_dynamic_workflows/engine/runtime.py` |
| `agent` / `pipeline` / `parallel` semantics | `hermes_dynamic_workflows/engine/api.py` |
| Resume fingerprints/cache | `hermes_dynamic_workflows/engine/cache.py` |
| Child construction and execution | `hermes_dynamic_workflows/child/runner.py` |
| Agent-type resolution | `hermes_dynamic_workflows/child/presets.py` |
| Workspace/worktree behavior | `hermes_dynamic_workflows/child/` |
| Run persistence | `hermes_dynamic_workflows/storage/store.py` |
| Control request channel | `hermes_dynamic_workflows/storage/control.py` |
| Configuration | `hermes_dynamic_workflows/core/config.py` |
| Shared types and errors | `hermes_dynamic_workflows/core/types.py`, `core/errors.py` |
| Structured schema validation | `hermes_dynamic_workflows/core/schema.py` |
| Compact text rendering | `hermes_dynamic_workflows/view/render.py` |
| TUI controller/model/rendering | `hermes_dynamic_workflows/tui/` |
| Built-in role instructions | `hermes_dynamic_workflows/agents/` |

If the current source contradicts this table, update the table or follow the actual
canonical owner. Do not preserve documentation fiction.

## 24. Change protocol

For orchestration changes:

1. identify the user-visible contract;
2. inspect current implementation and relevant tests;
3. locate the canonical function;
4. decide whether the change is action policy or reusable service mechanics;
5. make the smallest coherent edit;
6. extend existing state and telemetry;
7. add focused tests;
8. run the narrow test set;
9. run broader regression tests when shared mechanics changed;
10. read back persisted artifacts and docs;
11. report what was verified and what was not.

A new abstraction must name its current consumer. “Might be useful later” is not enough.

## 25. Test expectations

Tests should prove behavior, not implementation theater.

When relevant, cover:

- decomposition bounds;
- one logical worker per task;
- dependency scheduling;
- role-based model selection;
- structured `PASS` / `FAIL` / `BLOCKED`;
- fail-closed missing or invalid verdicts;
- bounded repair;
- accepted-only integration;
- final verification;
- persistence and read-back;
- journal and transcript events;
- pause, resume, stop, restart, and skip;
- completion notification;
- resume cache behavior;
- approval paths;
- worktree isolation and conflict handling;
- timeout and budget limits.

Do not present a synthetic harness as end-to-end proof.

## 26. Known gaps and non-goals

Current gaps relevant to this fork:

- no canonical automatic task decomposer;
- no default role-based planner/worker/reviewer configuration;
- no universal reviewed-task state contract;
- no built-in bounded repair loop;
- no universal integration step;
- no verified automatic crash continuation;
- no web dashboard;
- no graph/DAG visualization in the current TUI;
- no current TUI control for skipping one child.

Non-goals unless a proven requirement changes them:

- separate Hermes profiles per role;
- LangGraph or another workflow engine;
- a second state database;
- a web UI with its own backend model;
- implicit inheritance of full parent memory;
- bypassing Hermes approval rules.

## 27. Configuration

The plugin reads:

```text
plugins.entries.dynamic-workflows.dynamic_workflows
```

from Hermes `config.yaml`, plus `HERMES_DYNAMIC_WORKFLOWS_*` environment overrides.

See `README.md` for the current user-facing configuration example. Keep the canonical
key definitions in `core/config.py`; documentation must follow the implementation.
