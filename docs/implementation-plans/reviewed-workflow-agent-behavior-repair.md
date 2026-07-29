# Reviewed Workflow Agent Behavior Repair Plan

Status: PLANNED  
Branch: `plan/reviewed-workflow-agent-behavior`  
Base commit: `83da73588f9bbe71efadad357891a017c22daebc`  
Execution rule: implement exactly one numbered step per chat and one reviewable commit per step.

## 1. Objective

Repair the canonical `reviewed-workflow` so its model-driven roles behave like capable Hermes sessions operating on a scoped local workspace:

- the Initial Orchestrator decides the smallest sensible decomposition instead of being forced into unnecessary planning activity;
- a simple objective normally becomes one precise task because the model judges that one task is sufficient, not because Python classifies it through a deterministic shortcut;
- each worker receives only its scoped task packet and the local workspace context required to execute it;
- reviewers, repair workers, and final validators receive only the structured handoffs required for their role, never another agent's conversational history;
- all child roles retain the launching Hermes profile's applicable context, memory, skills, tools, integrations, permissions, approvals, and safety governance;
- role prompts refer to the target as a workspace, folder, project, or explicitly named path, and do not assume that every target is a repository;
- structured handoffs remain fail-closed and observable;
- safety limits stop pathological loops but do not replace model judgment or become consumption targets.

The intended default flow remains:

`parent -> initial orchestrator -> one worker per task -> reviewer -> bounded repair -> accepted integration -> final validation -> deterministic report`

## 2. Non-negotiable design rules

1. **No deterministic simple-task fast path.** Python must not decide that a request is simple based on filenames, wording, task count, or other heuristics. The Initial Orchestrator owns decomposition judgment.
2. **Python transports and validates; agents reason.** Runtime code supplies the objective, role packet, schema, limits, workspace metadata, and tool surface. It must not synthesize fake plans or encode planning decisions in example payloads.
3. **Minimum sufficient decomposition.** The planner must use the fewest independently executable and reviewable tasks that preserve correctness. It must not create artificial discovery, planning, summarization, or verification tasks.
4. **Scoped retrieval.** Start from named files, paths, known entrypoints, supplied evidence, or the local workspace root. Read additional material only for a concrete dependency or unresolved ambiguity.
5. **Conversation isolation.** No child receives the parent transcript or another child's transcript. Cross-role information moves only through validated structured packages and bounded runtime metadata.
6. **Profile capability inheritance.** Children remain fresh sessions of the launching Hermes profile and retain applicable SOUL/project instructions, memory, skills, safe tools, integrations, runtime model routing, approvals, and command guards.
7. **Role authority is narrow.** The role packet controls task scope and output contract. It must not erase relevant profile knowledge or tools. General profile guidance remains active unless it conflicts with the role's exact responsibility or structured handoff requirement.
8. **Workspace-neutral language.** Prompts must not instruct agents to inspect a repository unless the objective explicitly concerns one. Existing Git worktree isolation may still be used internally when the target is Git-backed and the task requires mutations.
9. **Fail-closed structured output.** A required tool call must actually occur. Runtime code must not silently convert prose or fenced JSON into a successful structured submission.
10. **Limits are circuit breakers.** Time, token, tool-call, retry, task-count, and repair limits exist to stop pathological behavior. Prompts must teach self-restraint before a limit is reached.
11. **Preserve canonical Hermes behavior.** Do not bypass approvals, command guards, persistence, telemetry, notifications, accounting, resume cache, worktrees, or existing APIs.
12. **Do not implement future steps opportunistically.** Each step below ends with focused tests, a plan status update, and one commit.

## 3. Current defects to correct

The current implementation distributes overlapping instructions across the generic child system prompt, role files, action-generated prompts, structured-output retry messages, and the launching profile context. The Initial Orchestrator is repeatedly told to submit a schema but receives weak guidance for judging task granularity. `planning.py` also constructs a large generic example plan that can anchor the model toward broad paths and generic work.

Additional verified risks include:

- `toolsets: ["*"]` expands primarily through configured default child toolsets and may not reproduce the safe tool and integration surface available to the launching Hermes session;
- worker, reviewer, repair, and final prompts are correct at a high level but remain too generic about starting points, stopping conditions, and avoiding lateral exploration;
- final validation receives an oversized workflow snapshot rather than a purpose-built final-validation packet;
- the runner currently accepts JSON extracted from final prose as if the mandatory structured-output tool had been called;
- loop limits operate mostly as terminal timeouts/retry caps rather than detecting repeated non-progress activity;
- prompt language often assumes a repository or codebase where the actual target may simply be a local Hermes workspace or folder.

## 4. Stepwise implementation

### Step 1 — Lock the behavioral contract with focused tests

Status: TODO

#### Goal

Create a failing-first test baseline that describes the desired behavior without changing production behavior beyond small test seams required for observability.

#### Work

- Map the exact instruction stack received by each canonical role:
  - launching profile context and memory;
  - generic child system prompt;
  - role `agentType` instructions;
  - task-specific first user message;
  - structured-output instruction and retry message;
  - tool definitions and allowed/disallowed surfaces.
- Add focused tests proving the assembled inputs for Initial Orchestrator, Worker, Reviewer, Repair Worker, and Final Orchestrator.
- Add behavioral prompt-contract tests for:
  - a named single-file read-only objective;
  - a small single-deliverable mutation;
  - a genuinely decomposable multi-part objective;
  - no automatic assumption that the target is a repository;
  - no fabricated discovery task before a directly executable task.
- Add context-boundary tests proving:
  - children use fresh session IDs;
  - parent and sibling conversation history is not passed;
  - profile context and memory remain enabled;
  - task-specific data appears only in the first user message or structured packet.
- Add tool-surface characterization tests documenting the current difference between `toolsets: ["*"]`, configured defaults, installed plugin tools, and MCP tools.
- Add a regression test showing that prose JSON fallback currently permits success without a real `structured_output` tool call. This test should be inverted in Step 6.

#### Likely files

- `tests/test_initial_planning.py`
- child runner/prompt tests under `tests/`
- agent preset/tool-resolution tests under `tests/`
- new focused tests only where no canonical test file exists

#### Completion criteria

- Tests clearly expose the unwanted current behavior and the intended target behavior.
- No broad production refactor is included.
- The full existing suite is not required unless focused changes reveal cross-cutting breakage.
- Update this step to `DONE` with test names and commit SHA.

---

### Step 2 — Rewrite Initial Orchestrator reasoning instructions and simplify the planning prompt

Status: TODO

#### Goal

Make the Initial Orchestrator judge decomposition intelligently and stop after producing the smallest sufficient plan.

#### Work

- Rewrite `initial-orchestrator.md` around decision principles rather than repeated output-format threats.
- Teach the planner to:
  - start from explicit targets and the objective;
  - distinguish one coherent deliverable from independent deliverables;
  - produce one task when one worker can execute and one reviewer can verify the objective cleanly;
  - split only for real dependencies, independent mutation scopes, materially different expertise/tool requirements, or work too large for one bounded attempt;
  - avoid artificial inspect/plan/summarize tasks;
  - place exact named paths in `paths`;
  - use empty `allowed_mutations` for read-only work;
  - write operational worker instructions with a clear stopping condition;
  - write reviewer guidance specific to the objective and evidence;
  - use workspace/folder/project terminology unless Git is explicitly relevant;
  - inspect only minimal context needed to make the plan executable.
- Simplify `InitialPlanningAction._prompt`:
  - remove the generated example `PlanPackage`;
  - remove generic `paths: ["."]` and `allowed_mutations: ["."]` anchoring;
  - remove duplicated `CRITICAL`/`MUST` wording already present in the role and tool contract;
  - pass only the exact objective, cycle, action-owned maxima, and concise transport requirements.
- Keep schema validation and semantic limits unchanged unless a test proves a necessary correction.
- Do not add deterministic objective classification or handcrafted plans in Python.

#### Likely files

- `hermes_dynamic_workflows/agents/initial-orchestrator.md`
- `hermes_dynamic_workflows/actions/planning.py`
- focused planning prompt and semantic tests

#### Completion criteria

- A simple named-file objective is represented by tests as one precise task because of planner instructions, not a Python branch.
- Complex objectives remain free to produce multiple tasks.
- The planner prompt is materially shorter and contains no fake example plan.
- Existing PlanPackage validation remains fail-closed.
- Update this step to `DONE` with evidence and commit SHA.

---

### Step 3 — Make handoff packets and conversation boundaries explicit

Status: TODO

#### Goal

Ensure every role sees exactly the information required for its responsibility while retaining shared Hermes profile knowledge and memory.

#### Work

- Define and test the assembled input contract for each role:
  - Initial Orchestrator: exact objective, cycle, limits, workspace identity, profile context/memory, role instructions.
  - Worker: one TaskPackage, workspace identity, attempt number, profile context/memory, available skills/tools.
  - Reviewer: TaskPackage, WorkerResultPackage, relevant workspace/diff evidence, planner reviewer guidance.
  - Repair Worker: original TaskPackage, previous WorkerResultPackage, ReviewVerdictPackage, retained workspace identity.
  - Final Orchestrator: original objective, final criteria, terminal task summaries, accepted integration evidence, unresolved failures/blockers, remaining cycle count.
- Prohibit transcript inheritance by construction and tests. Do not pass chain-of-thought, full conversation history, or prior child message arrays between roles.
- Preserve `skip_context_files=False` and `skip_memory=False` unless verified Hermes runtime behavior requires a more precise supported mechanism.
- Replace oversized or redundant packet content with bounded purpose-built structures while preserving lineage and evidence.
- Ensure task labels, phase labels, workspace paths, and display metadata remain telemetry rather than hidden scope instructions.

#### Likely files

- `hermes_dynamic_workflows/child/runner.py`
- `hermes_dynamic_workflows/actions/execution.py`
- `hermes_dynamic_workflows/actions/final_validation.py`
- contract schemas only if a bounded packet requires a formal schema
- context-isolation and packet-construction tests

#### Completion criteria

- Tests prove no parent/sibling transcript leakage.
- Tests prove profile context and memory remain available.
- Every cross-role transfer is represented by explicit structured data.
- Final validation no longer receives irrelevant full-run data when a bounded packet is sufficient.
- Update this step to `DONE` with evidence and commit SHA.

---

### Step 4 — Align child tools, skills, permissions, and workspace semantics with Hermes

Status: TODO

#### Goal

Make a workflow child capable of executing the same scoped prompt as a manually launched Hermes session, subject to the same safety governance and the role's mutation policy.

#### Work

- Correct the meaning of `toolsets: ["*"]` for Worker and Repair Worker so it includes the safe, discoverable tool/integration surface of the launching profile, including relevant installed plugin and MCP tools.
- Preserve blocked recursive-orchestration and unsafe toolsets already governed by plugin configuration.
- Preserve model routing, credentials, approvals, command guards, hardline restrictions, session approval reuse, and runtime integrations.
- Make read-only roles genuinely read-only through tool capability filtering, not prompt claims alone.
- Keep skills lazily discoverable and load full skill instructions only when relevant.
- Make role prompts and runtime metadata workspace-neutral:
  - treat the launch directory as the local workspace;
  - do not assume Git in task language;
  - retain Git worktree isolation as an internal implementation when the workspace is Git-backed and mutations require it;
  - fail clearly or select an existing supported non-Git execution mode when Git isolation is unavailable; do not silently pretend integration occurred.
- Do not create a second approval system or tool registry.

#### Likely files

- `hermes_dynamic_workflows/child/runner.py`
- `hermes_dynamic_workflows/child/presets.py`
- canonical agent role frontmatter
- configuration and tool-resolution tests
- workspace/worktree tests where affected

#### Completion criteria

- Capability parity tests cover safe plugin/MCP discovery for Worker and Repair Worker.
- Read-only roles cannot call mutation tools through the exposed tool surface.
- Safety and approval governance remain unchanged.
- Workspace wording and behavior no longer require the user objective to describe a repository.
- Update this step to `DONE` with evidence and commit SHA.

---

### Step 5 — Rewrite Worker, Reviewer, Repair Worker, and Final Orchestrator role behavior

Status: TODO

#### Goal

Give every execution and verification role precise behavioral guidance for retrieval, execution, evidence, and stopping.

#### Work

- Worker:
  - begin with named paths and packet evidence;
  - execute only the packet objective;
  - expand retrieval only for a direct dependency or unresolved ambiguity;
  - stop when acceptance criteria and evidence requirements are satisfied;
  - report exact tools/commands/checks and never self-approve.
- Reviewer:
  - inspect the task's claims and relevant workspace evidence;
  - check every acceptance criterion and planner guideline;
  - avoid broad audits unrelated to the task;
  - return PASS, FAIL, or BLOCKED without repairing.
- Repair Worker:
  - use the original packet and verdict feedback;
  - make a materially different correction where required;
  - preserve valid work and rerun only relevant checks;
  - never weaken criteria.
- Final Orchestrator:
  - validate the integrated result against the original objective and final criteria;
  - inspect only relevant terminal evidence and current workspace state;
  - avoid turning final validation into a general audit;
  - generate focused delta tasks only for concrete remaining gaps.
- Remove duplicated generic language that is already enforced by the runner or structured-output tool.
- Keep the role instructions authoritative only where necessary for scope and handoff correctness; do not globally suppress useful profile instructions.

#### Likely files

- `hermes_dynamic_workflows/agents/worker.md`
- `hermes_dynamic_workflows/agents/reviewer.md`
- `hermes_dynamic_workflows/agents/repair-worker.md`
- `hermes_dynamic_workflows/agents/final-orchestrator.md`
- `hermes_dynamic_workflows/actions/execution.py`
- `hermes_dynamic_workflows/actions/final_validation.py`
- role prompt tests

#### Completion criteria

- Each role has one clear responsibility, starting point, expansion rule, evidence duty, and stopping condition.
- Prompts do not redundantly repeat schema details.
- Focused tests cover simple, complex, failed, blocked, repaired, and final-validation behavior.
- Update this step to `DONE` with evidence and commit SHA.

---

### Step 6 — Restore strict structured-output semantics

Status: TODO

#### Goal

Require real structured handoff tool calls and keep broker routing safe under concurrency.

#### Work

- Remove `_extract_json_from_text` success fallback from the child conversation path.
- A prose or fenced-JSON response must trigger the explicit continuation instruction and then fail after bounded attempts if the tool is still not called.
- Retain and verify:
  - child-local specialized tool schema;
  - schema sanitization required for provider tool compatibility;
  - ContextVar scope inside the child worker thread;
  - per-task broker expectations and result capture;
  - reset/cleanup in every terminal path;
  - concurrency isolation for simultaneous structured children.
- Review whether the single-expectation fallback in the broker is still necessary. Remove it if explicit task identity is now reliable; otherwise document and constrain it so it cannot misroute concurrent submissions.
- Make error telemetry distinguish:
  - tool never called;
  - invalid payload;
  - retry exhaustion;
  - missing/mismatched task expectation;
  - provider/tool-definition failure.

#### Likely files

- `hermes_dynamic_workflows/child/runner.py`
- `hermes_dynamic_workflows/child/structured_output.py`
- structured-output and concurrency tests

#### Completion criteria

- Tests prove that text JSON cannot be accepted as a successful handoff.
- Valid tool calls succeed concurrently without cross-task capture.
- Invalid payloads receive actionable validation feedback and bounded retries.
- Cleanup leaves no stale expectation or ContextVar identity.
- Update this step to `DONE` with evidence and commit SHA.

---

### Step 7 — Add self-regulation guidance and non-progress circuit breakers

Status: TODO

#### Goal

Prevent planning and child-role exploration loops without turning hard limits into planning logic.

#### Work

- Add role guidance that agents should periodically ask whether they already possess enough information to execute or submit their package.
- Add configurable non-progress detection using observable activity, such as:
  - repeated equivalent searches;
  - repeated reads of unchanged paths;
  - continued exploration outside named or justified targets;
  - many tool calls without movement toward the required structured package;
  - repeated invalid structured submissions with no material correction.
- Use staged intervention:
  1. emit a progress warning and instruct the child to complete with available evidence;
  2. on continued identical behavior, stop fail-closed with a specific non-progress reason.
- Keep existing wall-clock, token, task-count, repair, and retry caps as final safety boundaries.
- Do not set a small universal tool-call cap and do not treat reaching the budget as desirable.
- Persist the non-progress signature and intervention in canonical run telemetry and transcripts.

#### Likely files

- child runner/activity observer code
- plugin configuration
- run journal/transcript metadata
- role instructions where self-check wording belongs
- focused circuit-breaker tests

#### Completion criteria

- A repeated search/read loop is interrupted and reported specifically.
- Legitimate multi-step work below the configured safety boundaries is not prematurely stopped.
- Intervention is visible through existing workflow telemetry.
- Update this step to `DONE` with evidence and commit SHA.

---

### Step 8 — Integrated validation, documentation, and Hermes deployment handoff

Status: TODO

#### Goal

Prove the repaired lifecycle on the repository branch, then prepare an exact installation and live-canary handoff for Hermes.

#### Work

- Run focused tests for every changed subsystem, then the full regression suite once.
- Execute repository-level integration scenarios:
  1. exact read-only request against one named file;
  2. small precise modification with relevant verification;
  3. genuinely decomposable objective with independent and dependent tasks;
  4. reviewer FAIL followed by a fresh repair and PASS;
  5. BLOCKED and exhausted-repair terminal reporting;
  6. concurrent structured children with isolated results.
- Verify the observed lifecycle reaches:
  - registered plan;
  - worker start and result;
  - reviewer verdict;
  - repair when required;
  - accepted integration only after PASS;
  - final validation;
  - deterministic terminal report.
- Update README/TECHNICAL/WORKFLOW_CONTRACT only where behavior actually changed.
- Record exact branch head SHA, test commands, results, known limitations, and files changed.
- Prepare a separate Hermes deployment prompt that:
  - fetches the exact approved commit;
  - installs/updates the plugin;
  - restarts the gateway only if required;
  - runs three live canaries;
  - reports run IDs, child sessions, phase transitions, prompts/tool activity, verdicts, terminal reports, and exact installed SHA;
  - does not claim success from unit tests alone.
- Do not merge to `master` or update the live Hermes installation without explicit user instruction.

#### Completion criteria

- All focused and full tests pass.
- Repository integration scenarios complete with evidence.
- Documentation matches verified behavior.
- A deployment handoff exists for exact-SHA installation and live proof.
- Update this step to `DONE` with evidence and commit SHA.

## 5. Per-step execution protocol

Every future execution chat must follow this protocol:

1. Read this entire plan from the branch before changing code.
2. Confirm the requested step is still `TODO` and inspect prior completed-step evidence.
3. Inspect only the files and tests relevant to that step.
4. Compare the branch head with the recorded state; do not silently rebase, merge, or overwrite newer work.
5. Implement exactly the requested step. Do not perform later steps early.
6. Run focused tests for the changed behavior. Run broader tests only when needed to expose a cross-cutting regression.
7. Review the diff against this plan's non-negotiable rules.
8. Update this document:
   - set the step status to `DONE`;
   - add the commit SHA;
   - list changed files;
   - list tests and results;
   - record residual risks or deferred work.
9. Commit the implementation and plan update together with a descriptive message.
10. Stop and report. Do not install on Hermes, merge to `master`, or begin the next step.

If a step cannot be completed safely, leave it `TODO` or mark it `BLOCKED` with exact evidence. Never mark a step complete based only on activity or an unverified claim.

## 6. Final acceptance criteria

The repair is complete only when all eight steps are `DONE` and evidence shows:

- the planner autonomously chooses one precise task for simple objectives and bounded decomposition for complex objectives;
- no deterministic Python fast path performs the planner's reasoning;
- workers execute scoped packets using the applicable Hermes profile memory, skills, tools, integrations, permissions, and approvals;
- child conversations remain isolated and exchange only structured packages;
- prompts use workspace-neutral terminology and targeted retrieval;
- reviewers and final validators inspect relevant evidence without broad uncontrolled exploration;
- real structured-output tool calls are mandatory and concurrency-safe;
- non-progress loops stop with explicit telemetry;
- the complete worker/reviewer/repair/integration/final-validation lifecycle is repository-verified;
- the exact approved commit is installed and proven separately in the target Hermes environment before live success is claimed.
