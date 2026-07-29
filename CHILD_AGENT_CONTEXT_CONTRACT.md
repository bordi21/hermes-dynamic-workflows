# Child Agent Context and Capability Contract

> **Status:** Canonical contract for every child launched by Dynamic Workflows.
> **Applies to:** initial orchestrator, worker, reviewer, repair worker, final orchestrator, and custom `agent()` children.

## Required child context

Every child agent is a fresh ephemeral `AIAgent` session of the launching Hermes profile. It must receive:

- the launching profile's complete `SOUL.md` through normal Hermes context loading;
- the launching profile's complete `MEMORY.md` and normal memory retrieval behavior;
- the selected role-specific instructions (`agentType`);
- the scoped task, review, repair, planning, or validation packet supplied by the workflow.

A child must not inherit the complete parent conversation transcript or unrelated session history. Any parent-session fact required for correctness must be transferred deliberately in the scoped packet.

## Skills

Every child must have access to every skill available to the launching Hermes profile.

Skill access is lazy and retrieval-based:

1. expose the complete skill catalog and descriptions to the child;
2. let the child load the full instructions of a relevant skill on demand;
3. do not inject every skill file into the initial prompt;
4. do not silently hide a required skill because of the selected workflow role.

This preserves profile capability parity without paying the context cost of eagerly loading all skill contents.

## Tools and governance

Every child must have access to all tools available to the launching Hermes profile, except toolsets that Dynamic Workflows blocks globally to prevent recursive orchestration or unsafe control-plane use.

Tool execution must use the same:

- runtime integrations and connected MCP servers;
- filesystem and process permissions;
- command guards and hardline restrictions;
- approval engine and `child_approval_policy`;
- authorization boundaries and permanent allowlists;
- structured-output specialization when a schema is required.

A child must never bypass, weaken, replace, or emulate these controls.

Role and packet restrictions govern what the child is authorized to do, even when a capable tool is visible. Read-only planner, reviewer, and final-validator roles must not mutate project state. Worker and repair-worker mutations remain bounded by the packet's authorized paths and mutation types.

## Scoped packets

A scoped packet may restrict:

- objective and role;
- authorized paths and files;
- allowed mutations;
- dependencies and prerequisites;
- acceptance and rejection criteria;
- evidence requirements;
- retry, timeout, and integration expectations.

A scoped packet must not silently remove skills or tools required to complete or verify the task. If the requested task cannot be completed within its authorization boundary, the child must return `BLOCKED` or `FAILED` with the exact missing permission, input, dependency, or capability.

## Runtime mapping

The current implementation maps this contract as follows:

- `HermesChildAgentRunner._build_agent()` constructs a fresh `AIAgent` with `skip_context_files=False` and `skip_memory=False`, preserving normal SOUL/project context and profile memory loading;
- the role prompt is appended through `ephemeral_system_prompt` rather than replacing the profile identity;
- the scoped packet is the first isolated user message in the fresh child session;
- reviewed-workflow role presets use `toolsets: ["*"]`, while global `blocked_child_toolsets` remains authoritative;
- Hermes skill discovery and `tool_search` provide lazy skill/tool schema loading;
- the existing approval callback, pre-tool-call hook, command guards, and hardline restrictions remain authoritative.

## Non-negotiable invariants

1. Same launching profile; no durable child profiles.
2. Full SOUL and MEMORY loading through Hermes.
3. Role instructions augment rather than replace profile identity.
4. Full skill catalog with lazy full-content retrieval.
5. Profile tool parity, subject to global workflow exclusions and normal governance.
6. Scoped packets bound authorization without erasing required capabilities.
7. No blind parent-conversation inheritance.
8. No child may bypass approvals, guards, hardline restrictions, or authorization boundaries.
