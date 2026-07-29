from __future__ import annotations

import re
import sys
from pathlib import Path
from textwrap import dedent


def snippet(value: str) -> str:
    return dedent(value).lstrip("\n")


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement target, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def insert_after(path: str, marker: str, addition: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if marker not in text:
        raise SystemExit(f"{path}: insertion marker missing")
    target.write_text(text.replace(marker, marker + addition, 1), encoding="utf-8")


def apply_changes() -> None:
    replace_once(
        "hermes_dynamic_workflows/child/presets.py",
        snippet('''
            disallowed_tools: tuple[str, ...] = ()
            model: str | None = None
        '''),
        snippet('''
            disallowed_tools: tuple[str, ...] = ()
            read_only: bool = False
            model: str | None = None
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/child/presets.py",
        snippet('''
                disallowed_tools=_as_tuple(frontmatter.get("disallowed_tools")),
                model=_as_optional_str(frontmatter.get("model")),
        '''),
        snippet('''
                disallowed_tools=_as_tuple(frontmatter.get("disallowed_tools")),
                read_only=_as_bool(frontmatter.get("read_only")),
                model=_as_optional_str(frontmatter.get("model")),
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/child/presets.py",
        snippet('''
                disallowed_tools=_as_tuple(data.get("disallowed_tools")),
                model=_as_optional_str(data.get("model")),
        '''),
        snippet('''
                disallowed_tools=_as_tuple(data.get("disallowed_tools")),
                read_only=_as_bool(data.get("read_only")),
                model=_as_optional_str(data.get("model")),
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/child/presets.py",
        snippet('''
            def _as_optional_str(value: Any) -> str | None:
                if value in (None, ""):
                    return None
                clean = str(value).strip()
                return clean or None
        '''),
        snippet('''
            def _as_bool(value: Any) -> bool:
                if isinstance(value, bool):
                    return value
                return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


            def _as_optional_str(value: Any) -> str | None:
                if value in (None, ""):
                    return None
                clean = str(value).strip()
                return clean or None
        '''),
    )

    replace_once(
        "hermes_dynamic_workflows/child/runner.py",
        snippet('''
            _CHILD_EXCLUDED_TOOL_NAMES = frozenset({"skill_manage"})


            class _WorkflowApprovalCoordinator:
        '''),
        snippet('''
            _CHILD_EXCLUDED_TOOL_NAMES = frozenset({"skill_manage"})
            _READ_ONLY_TOOL_NAMES = frozenset(
                {
                    "browser_back",
                    "browser_console",
                    "browser_get_images",
                    "browser_navigate",
                    "browser_scroll",
                    "browser_snapshot",
                    "browser_vision",
                    "read_file",
                    "read_terminal",
                    "search_files",
                    "session_search",
                    "skill_view",
                    "skills_list",
                    "structured_output",
                    "video_analyze",
                    "vision_analyze",
                    "web_extract",
                    "web_search",
                    "x_search",
                }
            )
            _READ_ONLY_NAME_TOKENS = frozenset(
                {
                    "analyze",
                    "check",
                    "console",
                    "describe",
                    "diff",
                    "extract",
                    "fetch",
                    "find",
                    "get",
                    "history",
                    "inspect",
                    "list",
                    "log",
                    "lookup",
                    "poll",
                    "query",
                    "read",
                    "search",
                    "show",
                    "snapshot",
                    "status",
                    "view",
                    "wait",
                }
            )
            _MUTATING_NAME_TOKENS = frozenset(
                {
                    "add",
                    "approve",
                    "assign",
                    "block",
                    "close",
                    "comment",
                    "complete",
                    "create",
                    "delete",
                    "deploy",
                    "dispatch",
                    "edit",
                    "execute",
                    "install",
                    "invite",
                    "kill",
                    "label",
                    "link",
                    "lock",
                    "manage",
                    "merge",
                    "move",
                    "patch",
                    "play",
                    "post",
                    "publish",
                    "push",
                    "put",
                    "react",
                    "reject",
                    "remove",
                    "rename",
                    "reply",
                    "restart",
                    "resume",
                    "run",
                    "save",
                    "schedule",
                    "send",
                    "set",
                    "start",
                    "stop",
                    "submit",
                    "switch",
                    "transfer",
                    "trigger",
                    "unblock",
                    "uninstall",
                    "unlock",
                    "update",
                    "upload",
                    "vote",
                    "write",
                }
            )


            class _WorkflowApprovalCoordinator:
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/child/runner.py",
        snippet('''
                    disallowed_tools=agent_type.disallowed_tools if agent_type else (),
                )
        '''),
        snippet('''
                    disallowed_tools=agent_type.disallowed_tools if agent_type else (),
                    read_only=bool(agent_type.read_only) if agent_type else False,
                )
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/child/runner.py",
        snippet('''
            raw = requested or list(agent_type_toolsets) or list(config.default_child_toolsets)
            # "*" expands to all default child toolsets (like general-purpose)
            if "*" in raw:
                wildcard = [ts for ts in config.default_child_toolsets if ts not in raw]
                raw = [item for item in raw if item != "*"] + wildcard
            if include_discoverable:
                raw = list(raw) + _discoverable_child_toolsets(config)
        '''),
        snippet('''
            raw = requested or list(agent_type_toolsets) or list(config.default_child_toolsets)
            wildcard_requested = "*" in raw
            if wildcard_requested:
                wildcard = [ts for ts in config.default_child_toolsets if ts not in raw]
                raw = [item for item in raw if item != "*"] + wildcard
            if include_discoverable or wildcard_requested:
                raw = list(raw) + _discoverable_child_toolsets(config)
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/child/runner.py",
        snippet('''
            def _configure_child_tools(
                child: Any,
                *,
                toolsets: list[str],
                blocked_toolsets: tuple[str, ...],
                allowed_tools: tuple[str, ...] = (),
                disallowed_tools: tuple[str, ...] = (),
            ) -> None:
        '''),
        snippet('''
            def _configure_child_tools(
                child: Any,
                *,
                toolsets: list[str],
                blocked_toolsets: tuple[str, ...],
                allowed_tools: tuple[str, ...] = (),
                disallowed_tools: tuple[str, ...] = (),
                read_only: bool = False,
            ) -> None:
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/child/runner.py",
        snippet('''
                    definitions,
                    allowed_tools=allowed_tools,
                    disallowed_tools=disallowed_tools,
                )
                direct: list[dict[str, Any]] = []
        '''),
        snippet('''
                    definitions,
                    allowed_tools=allowed_tools,
                    disallowed_tools=disallowed_tools,
                    read_only=read_only,
                )
                direct: list[dict[str, Any]] = []
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/child/runner.py",
        snippet('''
                    ],
                    allowed_tools=allowed_tools,
                    disallowed_tools=disallowed_tools,
                )

            child.valid_tool_names = {
        '''),
        snippet('''
                    ],
                    allowed_tools=allowed_tools,
                    disallowed_tools=disallowed_tools,
                    read_only=read_only,
                )

            child.valid_tool_names = {
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/child/runner.py",
        snippet('''
            def _filter_child_tool_definitions(
                definitions: list[dict[str, Any]],
                *,
                allowed_tools: tuple[str, ...] = (),
                disallowed_tools: tuple[str, ...] = (),
            ) -> list[dict[str, Any]]:
        '''),
        snippet('''
            def _filter_child_tool_definitions(
                definitions: list[dict[str, Any]],
                *,
                allowed_tools: tuple[str, ...] = (),
                disallowed_tools: tuple[str, ...] = (),
                read_only: bool = False,
            ) -> list[dict[str, Any]]:
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/child/runner.py",
        snippet('''
                if name in disallowed:
                    continue
                filtered.append(definition)
            return filtered


            def _tool_definition_name(definition: Any) -> str:
        '''),
        snippet('''
                if name in disallowed:
                    continue
                if read_only and not _is_read_only_tool_definition(definition):
                    continue
                filtered.append(definition)
            return filtered


            def _is_read_only_tool_definition(definition: Any) -> bool:
                # Capability filtering stays on Hermes' canonical definitions and registry.
                name = _tool_definition_name(definition)
                if not name:
                    return False
                folded = name.casefold()
                if folded in _READ_ONLY_TOOL_NAMES:
                    return True
                tokens = {
                    token
                    for token in re.split(r"[^a-z0-9]+", folded)
                    if token
                }
                if tokens.intersection(_MUTATING_NAME_TOKENS):
                    return False
                return bool(tokens.intersection(_READ_ONLY_NAME_TOKENS))


            def _tool_definition_name(definition: Any) -> str:
        '''),
    )

    for role in ("initial-orchestrator", "reviewer", "final-orchestrator"):
        replace_once(
            f"hermes_dynamic_workflows/agents/{role}.md",
            "model: inherit\n",
            "model: inherit\nread_only: true\n",
        )

    replace_once(
        "hermes_dynamic_workflows/actions/execution.py",
        snippet('''
            The action owns the concrete task worktree for the entire lifecycle. Every
            child still runs through ``WorkflowAPI.agent`` so routing, approvals,
            structured output, accounting, transcripts, and runtime limits remain
            canonical. Workers, reviewers, and fresh repair sessions all operate on the
            same isolated workspace; only an evidence-backed PASS is integrated.
        '''),
        snippet('''
            The action owns the concrete task workspace for the entire lifecycle. Mutation
            tasks use one retained Git worktree; read-only tasks use the launch workspace.
            Every child still runs through ``WorkflowAPI.agent`` so routing, approvals,
            structured output, accounting, transcripts, and runtime limits remain
            canonical. Only an evidence-backed PASS is accepted.
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/actions/execution.py",
        snippet('''
            async def _worker(self, api: Any, *, task: dict[str, Any], attempt: int) -> dict[str, Any]:
                prompt = (
                    "Execute exactly this reviewed-workflow TaskPackage inside the current isolated task "
                    "workspace. Return only the required WorkerResultPackage through structured output. "
                    "Do not self-review or broaden scope.\\n\\n"
                    f"Attempt: {attempt}\\nTaskPackage:\\n{_json(task)}"
                )
        '''),
        snippet('''
            async def _worker(self, api: Any, *, task: dict[str, Any], attempt: int) -> dict[str, Any]:
                request = {
                    "schema_version": "1.0",
                    "task": deepcopy(task),
                    "attempt": attempt,
                }
                prompt = (
                    "Execute exactly the supplied TaskPackage in the current workspace. Return only "
                    "the required WorkerResultPackage through structured output. Do not self-review or "
                    "broaden scope.\\n\\n"
                    f"WorkerRequestPacket:\\n{_json(request)}"
                )
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/actions/execution.py",
        snippet('''
                    "and return only a WorkerResultPackage through structured output.\\n\\n"
                    f"Worker attempt: {attempt}\\nRepairPackage:\\n{_json(repair)}"
        '''),
        snippet('''
                    "and return only a WorkerResultPackage through structured output.\\n\\n"
                    f"RepairRequestPacket:\\n{_json({'repair': repair, 'worker_attempt': attempt})}"
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/actions/execution.py",
        snippet('''
                request = {
                    "schema_version": "1.0",
                    "plan_id": task["plan_id"],
                    "task_id": task["task_id"],
                    "original_objective": plan["original_objective"],
                    "task": deepcopy(task),
                    "worker_result": deepcopy(result),
                }
                workspace = reviewed_workspace_context(lease)
        '''),
        snippet('''
                request = {
                    "schema_version": "1.0",
                    "plan_id": task["plan_id"],
                    "task_id": task["task_id"],
                    "task": deepcopy(task),
                    "worker_result": deepcopy(result),
                    "workspace_evidence": reviewed_workspace_context(lease),
                }
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/actions/execution.py",
        snippet('''
                    "ReviewVerdictPackage. Do not repair the work.\\n\\n"
                    f"ReviewRequestPackage:\\n{_json(request)}\\n\\n"
                    f"WorkspaceReviewContext:\\n{_json(workspace)}"
        '''),
        snippet('''
                    "ReviewVerdictPackage. Do not repair the work.\\n\\n"
                    f"ReviewRequestPacket:\\n{_json(request)}"
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/actions/execution.py",
        snippet('''
            def _create_task_workspace(api: Any, task: dict[str, Any]) -> WorkspaceLease:
                try:
                    return create_workspace_lease(
                        cwd=api.frame.cwd,
                        isolation="worktree",
        '''),
        snippet('''
            def _create_task_workspace(api: Any, task: dict[str, Any]) -> WorkspaceLease:
                isolation = "worktree" if task.get("allowed_mutations") else "shared"
                try:
                    return create_workspace_lease(
                        cwd=api.frame.cwd,
                        isolation=isolation,
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/actions/execution.py",
        snippet('''
                except (OSError, ValueError) as exc:
                    raise ReviewedStateError(
                        f"could not create isolated workspace for task {task['task_id']}: {exc}"
                    ) from exc
        '''),
        snippet('''
                except (OSError, ValueError) as exc:
                    mode = "isolated Git workspace" if isolation == "worktree" else "shared workspace"
                    raise ReviewedStateError(
                        f"could not create {mode} for task {task['task_id']}: {exc}"
                    ) from exc
        '''),
    )

    replace_once(
        "hermes_dynamic_workflows/actions/final_validation.py",
        snippet('''
                prompt = _validation_prompt(
                    snapshot=snapshot,
                    plan=plan,
        '''),
        snippet('''
                prompt = _validation_prompt(
                    plan=plan,
        '''),
    )
    replace_once(
        "hermes_dynamic_workflows/actions/final_validation.py",
        snippet('''
            def _validation_prompt(
                *,
                snapshot: dict[str, Any],
                plan: dict[str, Any],
                task_states: list[dict[str, Any]],
                remaining_cycles: int,
            ) -> str:
                return (
                    "Validate the integrated project state against the original objective and every "
                    "final validation criterion. Operate read-only and inspect the current checkout, "
                    "tests, persisted task lineage, worker evidence, reviewer verdicts, repairs, "
                    "integrations, failures, and blockers. Return only the required "
                    "FinalValidationPackage through structured output.\\n\\n"
                    "Requirement results must appear in exactly the same order and use exactly the "
                    "same requirement strings as final_validation_criteria. APPROVED requires every "
                    "requirement to be satisfied and delta_tasks to be empty. BLOCKED requires a "
                    "specific external blocker and delta_tasks to be empty. NOT_APPROVED requires at "
                    "least one concrete gap.\\n\\n"
                    f"Remaining replanning cycles: {remaining_cycles}\\n"
                    + (
                        "For NOT_APPROVED, create a non-empty, focused delta_tasks array. Every delta "
                        "task must use the same new plan_id, different from the current plan_id. A delta "
                        "task may depend only on already INTEGRATED tasks or earlier delta tasks."
                        if remaining_cycles > 0
                        else "No replanning cycles remain. For NOT_APPROVED, delta_tasks must be empty."
                    )
                    + "\\n\\n"
                    f"Current PlanPackage:\\n{_json(plan)}\\n\\n"
                    f"Current cycle task states:\\n{_json(task_states)}\\n\\n"
                    f"Complete reviewed workflow snapshot:\\n{_json(snapshot)}"
                )
        '''),
        snippet('''
            def _validation_prompt(
                *,
                plan: dict[str, Any],
                task_states: list[dict[str, Any]],
                remaining_cycles: int,
            ) -> str:
                packet = _final_validation_packet(
                    plan=plan,
                    task_states=task_states,
                    remaining_cycles=remaining_cycles,
                )
                return (
                    "Validate the current workspace state against the original objective and every "
                    "final validation criterion. Operate read-only and inspect only the supplied "
                    "terminal evidence plus relevant current workspace state. Return only the required "
                    "FinalValidationPackage through structured output.\\n\\n"
                    "Requirement results must appear in exactly the same order and use exactly the "
                    "same requirement strings as final_validation_criteria. APPROVED requires every "
                    "requirement to be satisfied and delta_tasks to be empty. BLOCKED requires a "
                    "specific external blocker and delta_tasks to be empty. NOT_APPROVED requires at "
                    "least one concrete gap.\\n\\n"
                    + (
                        "For NOT_APPROVED, create a non-empty, focused delta_tasks array. Every delta "
                        "task must use the same new plan_id, different from the current plan_id. A delta "
                        "task may depend only on already INTEGRATED tasks or earlier delta tasks."
                        if remaining_cycles > 0
                        else "No replanning cycles remain. For NOT_APPROVED, delta_tasks must be empty."
                    )
                    + "\\n\\n"
                    f"FinalValidationPacket:\\n{_json(packet)}"
                )


            def _final_validation_packet(
                *,
                plan: dict[str, Any],
                task_states: list[dict[str, Any]],
                remaining_cycles: int,
            ) -> dict[str, Any]:
                return {
                    "schema_version": "1.0",
                    "plan_id": plan["plan_id"],
                    "cycle": plan["cycle"],
                    "original_objective": plan["original_objective"],
                    "final_validation_criteria": deepcopy(plan["final_validation_criteria"]),
                    "remaining_replanning_cycles": remaining_cycles,
                    "terminal_tasks": [
                        _terminal_task_summary(item) for item in task_states
                    ],
                    "accepted_integrations": [
                        deepcopy(item["integration"])
                        for item in task_states
                        if item.get("status") == "INTEGRATED"
                        and isinstance(item.get("integration"), dict)
                    ],
                    "unresolved_outcomes": [
                        {
                            "task_id": item["task_id"],
                            "status": item["status"],
                            "latest_review_verdict": deepcopy(
                                (item.get("review_verdicts") or [None])[-1]
                            ),
                            "skip_reason": item.get("skip_reason"),
                        }
                        for item in task_states
                        if item.get("status") != "INTEGRATED"
                    ],
                }


            def _terminal_task_summary(task_state: dict[str, Any]) -> dict[str, Any]:
                task = task_state.get("task") or {}
                worker_attempts = task_state.get("worker_attempts") or []
                review_verdicts = task_state.get("review_verdicts") or []
                return {
                    "task_id": task_state["task_id"],
                    "objective": task.get("objective"),
                    "status": task_state["status"],
                    "acceptance_criteria": deepcopy(task.get("acceptance_criteria") or []),
                    "latest_worker_result": (
                        deepcopy(worker_attempts[-1]) if worker_attempts else None
                    ),
                    "latest_review_verdict": (
                        deepcopy(review_verdicts[-1]) if review_verdicts else None
                    ),
                    "repair_attempts_used": len(task_state.get("repair_attempts") or []),
                    "integration": deepcopy(task_state.get("integration")),
                    "skip_reason": task_state.get("skip_reason"),
                }
        '''),
    )

    replace_once(
        "tests/test_reviewed_agent_behavior_contract.py",
        '        self.assertIn("Current PlanPackage", final_source)\n',
        '        self.assertIn("FinalValidationPacket", final_source)\n'
        '        self.assertNotIn("Complete reviewed workflow snapshot", final_source)\n',
    )
    replace_once(
        "tests/test_reviewed_agent_behavior_contract.py",
        snippet('''
            def test_wildcard_currently_expands_defaults_not_discoverable_plugin_or_mcp_tools(self):
                config = SimpleNamespace(
                    default_child_toolsets=("file", "terminal"),
                    blocked_child_toolsets=("workflow",),
                )
                with patch(
                    "hermes_dynamic_workflows.child.runner._discoverable_child_toolsets",
                    return_value=["mcp-demo", "plugin-demo"],
                ):
                    wildcard = _resolve_child_toolsets(
                        config,
                        [],
                        ("*",),
                        include_discoverable=False,
                    )
                    anonymous = _resolve_child_toolsets(
                        config,
                        [],
                        (),
                        include_discoverable=True,
                    )

                self.assertEqual(wildcard, ["file", "terminal"])
                self.assertEqual(
                    anonymous,
                    ["file", "terminal", "mcp-demo", "plugin-demo"],
                )
        '''),
        snippet('''
            def test_wildcard_expands_defaults_and_discoverable_plugin_or_mcp_tools(self):
                config = SimpleNamespace(
                    default_child_toolsets=("file", "terminal"),
                    blocked_child_toolsets=("workflow",),
                )
                with patch(
                    "hermes_dynamic_workflows.child.runner._discoverable_child_toolsets",
                    return_value=["mcp-demo", "plugin-demo"],
                ):
                    wildcard = _resolve_child_toolsets(
                        config,
                        [],
                        ("*",),
                        include_discoverable=False,
                    )
                    explicit = _resolve_child_toolsets(
                        config,
                        [],
                        ("file",),
                        include_discoverable=False,
                    )

                self.assertEqual(
                    wildcard,
                    ["file", "terminal", "mcp-demo", "plugin-demo"],
                )
                self.assertEqual(explicit, ["file"])
        '''),
    )
    insert_after(
        "tests/test_reviewed_agent_behavior_contract.py",
        '        self.assertNotIn("parent conversation", build_source.lower())\n\n',
        snippet('''

            def test_read_only_roles_declare_capability_policy(self):
                for role in ("initial-orchestrator", "reviewer", "final-orchestrator"):
                    with self.subTest(role=role):
                        text = (_AGENTS_ROOT / f"{role}.md").read_text(encoding="utf-8")
                        self.assertIn("read_only: true", text.split("\\n---\\n", 1)[0])

        '''),
    )

    replace_once(
        "tests/test_child_agent.py",
        snippet('''
            def test_explicit_agent_type_does_not_gain_discoverable_toolsets(self):
                with patch(
                    "hermes_dynamic_workflows.child.runner._discoverable_child_toolsets",
                    return_value=["mcp-github", "plugin-extra"],
                ):
                    self.assertEqual(
                        _resolve_child_toolsets(
                            PluginConfig(),
                            [],
                            ("file",),
                            include_discoverable=False,
                        ),
                        ["file"],
                    )
        '''),
        snippet('''
            def test_wildcard_agent_type_gains_discoverable_toolsets(self):
                with patch(
                    "hermes_dynamic_workflows.child.runner._discoverable_child_toolsets",
                    return_value=["mcp-github", "plugin-extra"],
                ):
                    self.assertEqual(
                        _resolve_child_toolsets(
                            PluginConfig(),
                            [],
                            ("*",),
                            include_discoverable=False,
                        ),
                        [
                            "web",
                            "file",
                            "terminal",
                            "skills",
                            "mcp-github",
                            "plugin-extra",
                        ],
                    )
                    self.assertEqual(
                        _resolve_child_toolsets(
                            PluginConfig(),
                            [],
                            ("file",),
                            include_discoverable=False,
                        ),
                        ["file"],
                    )
        '''),
    )
    insert_after(
        "tests/test_child_agent.py",
        '        self.assertNotIn("patch", child.valid_tool_names)\n\n',
        snippet('''

            def test_read_only_child_surface_filters_mutation_capabilities(self):
                definitions = [
                    _tool_definition("read_file"),
                    _tool_definition("search_files"),
                    _tool_definition("write_file"),
                    _tool_definition("patch"),
                    _tool_definition("terminal"),
                    _tool_definition("mcp_github_get_file"),
                    _tool_definition("mcp_github_create_issue"),
                    _tool_definition("plugin_list_items"),
                    _tool_definition("plugin_update_item"),
                    _tool_definition("structured_output"),
                ]

                model_tools = types.ModuleType("model_tools")
                model_tools.get_tool_definitions = lambda **kwargs: definitions
                search_mod = types.ModuleType("tools.tool_search")

                class ToolSearchConfig:
                    @staticmethod
                    def from_raw(raw):
                        return raw

                def assemble_tool_defs(tool_defs, *, config):
                    return types.SimpleNamespace(tool_defs=tool_defs)

                search_mod.ToolSearchConfig = ToolSearchConfig
                search_mod.assemble_tool_defs = assemble_tool_defs
                tools_pkg = types.ModuleType("tools")
                tools_pkg.__path__ = []
                tools_pkg.tool_search = search_mod

                class Child:
                    tools = []
                    valid_tool_names = set()
                    enabled_toolsets = []

                child = Child()
                with patch.dict(
                    sys.modules,
                    {
                        "model_tools": model_tools,
                        "tools": tools_pkg,
                        "tools.tool_search": search_mod,
                    },
                ):
                    _configure_child_tools(
                        child,
                        toolsets=["file", "terminal", "mcp-github", "plugin-extra"],
                        blocked_toolsets=PluginConfig().blocked_child_toolsets,
                        read_only=True,
                    )

                self.assertEqual(
                    child.valid_tool_names,
                    {
                        "read_file",
                        "search_files",
                        "mcp_github_get_file",
                        "plugin_list_items",
                        "structured_output",
                    },
                )
                self.assertNotIn("write_file", child.valid_tool_names)
                self.assertNotIn("patch", child.valid_tool_names)
                self.assertNotIn("terminal", child.valid_tool_names)
                self.assertNotIn("mcp_github_create_issue", child.valid_tool_names)
                self.assertNotIn("plugin_update_item", child.valid_tool_names)

        '''),
    )

    replace_once("tests/test_reviewed_task_execution.py", "import unittest\n", "import json\nimport unittest\n")
    replace_once(
        "tests/test_reviewed_task_execution.py",
        '            mode="worktree",\n',
        '            mode="worktree" if self.isolation == "worktree" else "shared",\n',
    )
    insert_after(
        "tests/test_reviewed_task_execution.py",
        '        self.assertIn(\'"workspace": "/tmp/A-workspace"\', api.calls[1]["prompt"])\n',
        snippet('''

                worker_packet = json.loads(
                    api.calls[0]["prompt"].split("WorkerRequestPacket:\\n", 1)[1]
                )
                self.assertEqual(set(worker_packet), {"schema_version", "task", "attempt"})
                self.assertEqual(worker_packet["task"]["task_id"], "A")
                self.assertEqual(worker_packet["attempt"], 1)

                review_prompt = api.calls[1]["prompt"]
                self.assertNotIn("WorkspaceReviewContext", review_prompt)
                review_packet = json.loads(
                    review_prompt.split("ReviewRequestPacket:\\n", 1)[1]
                )
                self.assertEqual(
                    set(review_packet),
                    {
                        "schema_version",
                        "plan_id",
                        "task_id",
                        "task",
                        "worker_result",
                        "workspace_evidence",
                    },
                )
                self.assertNotIn("original_objective", review_packet)
                self.assertEqual(
                    review_packet["workspace_evidence"]["workspace"],
                    "/tmp/A-workspace",
                )
        '''),
    )
    replace_once(
        "tests/test_reviewed_task_execution.py",
        snippet('''
                repair_prompt = api.calls[2]["prompt"]
                self.assertIn('"repair_attempt": 1', repair_prompt)
                self.assertIn('"verdict": "FAIL"', repair_prompt)
        '''),
        snippet('''
                repair_prompt = api.calls[2]["prompt"]
                repair_packet = json.loads(
                    repair_prompt.split("RepairRequestPacket:\\n", 1)[1]
                )
                self.assertEqual(repair_packet["worker_attempt"], 2)
                self.assertEqual(repair_packet["repair"]["repair_attempt"], 1)
                self.assertEqual(
                    repair_packet["repair"]["review_verdict"]["verdict"],
                    "FAIL",
                )
        '''),
    )
    insert_after(
        "tests/test_reviewed_task_execution.py",
        '    async def test_workspace_scope_failure_cleans_lease_before_state_start(self):\n',
        snippet('''
                # Marker replaced below with the shared-workspace coverage.
        '''),
    )
    replace_once(
        "tests/test_reviewed_task_execution.py",
        snippet('''
            async def test_workspace_scope_failure_cleans_lease_before_state_start(self):
                # Marker replaced below with the shared-workspace coverage.
                api = _BrokenScopedAPI([])
        '''),
        snippet('''
            async def test_read_only_task_uses_supported_shared_workspace_mode(self):
                task = _task()
                task["allowed_mutations"] = []
                api = _API([_worker(attempt=1), _review(attempt=1)])
                api.context.state.reviewed.register_plan(_plan(task))
                lease = _Lease(
                    isolation="shared",
                    path=None,
                    branch=None,
                    repo_root=None,
                )

                with patch(
                    "hermes_dynamic_workflows.actions.execution.create_workspace_lease",
                    return_value=lease,
                ) as factory:
                    result = await ReviewedTaskExecutionAction().run(api, task_id="A")

                self.assertEqual(result["status"], "INTEGRATED")
                factory.assert_called_once_with(
                    cwd="/repo",
                    isolation="shared",
                    label="reviewed-A",
                    task_id="reviewed-plan-1-A",
                    keep_worktree=False,
                )
                self.assertTrue(all(call["cwd"] == lease.cwd for call in api.calls))

            async def test_workspace_scope_failure_cleans_lease_before_state_start(self):
                api = _BrokenScopedAPI([])
        '''),
    )

    replace_once("tests/test_final_validation_action.py", "import unittest\n", "import json\nimport unittest\n")
    replace_once(
        "tests/test_final_validation_action.py",
        "from hermes_dynamic_workflows.actions.final_validation import FinalValidationAction\n",
        snippet('''
            from hermes_dynamic_workflows.actions.final_validation import (
                FinalValidationAction,
                _final_validation_packet,
            )
        '''),
    )
    replace_once(
        "tests/test_final_validation_action.py",
        snippet('''
                self.assertIn("Validate the integrated project state", prompt)
                self.assertEqual(opts["agentType"], "final-orchestrator")
        '''),
        snippet('''
                self.assertIn("Validate the current workspace state", prompt)
                self.assertIn("FinalValidationPacket", prompt)
                self.assertNotIn("Complete reviewed workflow snapshot", prompt)
                packet = json.loads(prompt.split("FinalValidationPacket:\\n", 1)[1])
                self.assertEqual(packet["original_objective"], OBJECTIVE)
                self.assertEqual(packet["final_validation_criteria"], CRITERIA)
                self.assertEqual(len(packet["terminal_tasks"]), 1)
                self.assertEqual(len(packet["accepted_integrations"]), 1)
                self.assertEqual(packet["unresolved_outcomes"], [])
                self.assertEqual(opts["agentType"], "final-orchestrator")
        '''),
    )
    insert_after(
        "tests/test_final_validation_action.py",
        "class FinalValidationActionTests(unittest.IsolatedAsyncioTestCase):\n",
        snippet('''
                def test_final_packet_keeps_only_latest_attempt_and_bounded_lineage(self):
                    task_state = {
                        "task_id": "A",
                        "status": "FAILED",
                        "task": _task("A"),
                        "worker_attempts": [
                            {"attempt": 1, "summary": "old"},
                            {"attempt": 2, "summary": "latest"},
                        ],
                        "review_verdicts": [
                            {"attempt": 1, "verdict": "FAIL"},
                            {"attempt": 2, "verdict": "FAIL"},
                        ],
                        "repair_attempts": [{"repair": {"repair_attempt": 1}}],
                        "integration": None,
                        "skip_reason": None,
                    }

                    packet = _final_validation_packet(
                        plan=_plan(),
                        task_states=[task_state],
                        remaining_cycles=1,
                    )

                    terminal = packet["terminal_tasks"][0]
                    self.assertEqual(terminal["latest_worker_result"]["attempt"], 2)
                    self.assertEqual(terminal["latest_review_verdict"]["attempt"], 2)
                    self.assertEqual(terminal["repair_attempts_used"], 1)
                    self.assertNotIn("worker_attempts", terminal)
                    self.assertNotIn("review_verdicts", terminal)
                    self.assertEqual(packet["unresolved_outcomes"][0]["status"], "FAILED")

        '''),
    )


def parse_result(path: str) -> str:
    text = Path(path).read_text(encoding="utf-8")
    match = re.search(r"Ran (\d+) tests? in ([0-9.]+)s\n\n(OK|FAILED[^\n]*)", text)
    if not match:
        raise SystemExit(f"could not parse unittest result from {path}")
    return f"{match.group(1)} tests in {match.group(2)}s, {match.group(3)}"


def complete_plan(log_dir: str) -> None:
    focused = {
        "tests/test_child_agent.py": parse_result(f"{log_dir}/test_child_agent.log"),
        "tests/test_reviewed_agent_behavior_contract.py": parse_result(
            f"{log_dir}/test_reviewed_agent_behavior_contract.log"
        ),
        "tests/test_reviewed_task_execution.py": parse_result(
            f"{log_dir}/test_reviewed_task_execution.log"
        ),
        "tests/test_final_validation_action.py": parse_result(
            f"{log_dir}/test_final_validation_action.log"
        ),
    }
    full = parse_result(f"{log_dir}/full.log")

    plan_path = Path("docs/implementation-plans/reviewed-workflow-agent-behavior-repair.md")
    plan = plan_path.read_text(encoding="utf-8")

    def complete_step(plan_text: str, step: int, next_step: int, record: str) -> str:
        start = plan_text.index(f"### Step {step} —")
        end = plan_text.index(f"### Step {next_step} —")
        section = plan_text[start:end]
        if section.count("Status: TODO") != 1:
            raise SystemExit(f"Step {step} is no longer exactly one TODO section")
        section = section.replace("Status: TODO", "Status: DONE", 1)
        divider = section.rfind("\n---\n")
        if divider == -1:
            raise SystemExit(f"Step {step} divider missing")
        section = section[:divider] + "\n\n" + record.rstrip() + "\n" + section[divider:]
        return plan_text[:start] + section + plan_text[end:]

    focused_lines = "\n".join(
        f"  - `{name}`: {outcome}." for name, outcome in focused.items()
    )
    changed_files = '''  - `hermes_dynamic_workflows/child/runner.py`
  - `hermes_dynamic_workflows/child/presets.py`
  - `hermes_dynamic_workflows/actions/execution.py`
  - `hermes_dynamic_workflows/actions/final_validation.py`
  - `hermes_dynamic_workflows/agents/initial-orchestrator.md`
  - `hermes_dynamic_workflows/agents/reviewer.md`
  - `hermes_dynamic_workflows/agents/final-orchestrator.md`
  - `tests/test_child_agent.py`
  - `tests/test_reviewed_agent_behavior_contract.py`
  - `tests/test_reviewed_task_execution.py`
  - `tests/test_final_validation_action.py`
  - `docs/implementation-plans/reviewed-workflow-agent-behavior-repair.md`'''

    step3 = f'''#### Completion record

- Resulting commit: this implementation-and-plan commit; its exact SHA is recorded in branch history and the execution report because a commit cannot contain its own final SHA.
- Changed files:
{changed_files}
- Implemented behavior:
  - explicit worker, reviewer, repair, and final-validation request packets;
  - fresh child sessions retain profile context and memory while parent and sibling transcripts remain absent;
  - reviewer handoff contains only its TaskPackage, WorkerResultPackage, planner guidance, and current workspace evidence;
  - final validation receives bounded terminal summaries, latest attempt and verdict evidence, accepted integrations, unresolved outcomes, and remaining cycle count instead of the complete run snapshot;
  - labels, phases, and workspace display metadata remain transport and telemetry rather than packet scope.
- Focused tests:
{focused_lines}
- Broader regression suite, required because child tool resolution and agent preset parsing are cross-cutting: `python -m unittest discover -s tests -v` — {full}.
- Residual risks/deferred work:
  - repository tests prove assembly and isolation contracts, not live model behavior;
  - strict mandatory structured-output enforcement remains Step 6;
  - role retrieval and stopping instruction rewrites remain Step 5.
'''

    step4 = f'''#### Completion record

- Resulting commit: this implementation-and-plan commit; its exact SHA is recorded in branch history and the execution report because a commit cannot contain its own final SHA.
- Changed files:
{changed_files}
- Implemented behavior:
  - `toolsets: ["*"]` now expands configured defaults plus safe discoverable plugin and MCP toolsets for Worker and Repair Worker;
  - blocked toolsets, recursive orchestration exclusions, model routing, approvals, command guards, hardline restrictions, runtime integrations, and canonical registry and Tool Search remain in force;
  - read-only roles declare explicit capability policy and receive a fail-closed read-only tool surface, including lazily discoverable read-only plugin and MCP tools while mutation-capable tools are withheld;
  - read-only tasks use Hermes' supported shared-workspace mode; mutation tasks continue to require Git worktree isolation and fail clearly when it cannot be created;
  - task language uses workspace semantics while Git terminology remains limited to actual isolation and integration behavior.
- Focused tests:
{focused_lines}
- Broader regression suite, required because child tool resolution and agent preset parsing are cross-cutting: `python -m unittest discover -s tests -v` — {full}.
- Residual risks/deferred work:
  - plugin and MCP tools do not expose a canonical mutability flag, so unknown tools are filtered fail-closed by explicit safe names and read or mutation action tokens; unusual read-only names may require future classification;
  - non-Git mutation execution remains unsupported and fails clearly rather than claiming integration;
  - no live Hermes canary, installation, or provider-specific capability test was run.
'''

    plan = complete_step(plan, 3, 4, step3)
    plan = complete_step(plan, 4, 5, step4)
    plan_path.write_text(plan, encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: apply_steps_3_4.py apply|plan [log_dir]")
    if sys.argv[1] == "apply":
        apply_changes()
    elif sys.argv[1] == "plan" and len(sys.argv) == 3:
        complete_plan(sys.argv[2])
    else:
        raise SystemExit("usage: apply_steps_3_4.py apply|plan [log_dir]")


if __name__ == "__main__":
    main()
