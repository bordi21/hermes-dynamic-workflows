from __future__ import annotations

import ast
import inspect
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hermes_dynamic_workflows.actions.planning import InitialPlanningAction, PlanningLimits
from hermes_dynamic_workflows.child import runner as child_runner
from hermes_dynamic_workflows.child.presets import AgentTypeSpec
from hermes_dynamic_workflows.child.runner import (
    HermesChildAgentRunner,
    _resolve_child_toolsets,
    build_child_system_prompt,
    build_child_task_message,
)
from hermes_dynamic_workflows.core.types import ChildAgentRequest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_AGENTS_ROOT = _REPO_ROOT / "hermes_dynamic_workflows" / "agents"
_ROLES = (
    "initial-orchestrator",
    "worker",
    "reviewer",
    "repair-worker",
    "final-orchestrator",
)

def _role_body(name: str) -> str:
    text = (_AGENTS_ROOT / f"{name}.md").read_text(encoding="utf-8")
    return text.split("\n---\n", 1)[1].strip()


def _request(role: str, prompt: str) -> ChildAgentRequest:
    return ChildAgentRequest(
        id=1,
        prompt=prompt,
        label=f"{role}:contract",
        phase="Contract",
        toolsets=[],
        schema={"type": "object"},
        agent_type=role,
        structured_tool=True,
    )


class CanonicalRoleInputContractTests(unittest.TestCase):
    def test_all_reviewed_roles_receive_role_system_and_scoped_first_message(self):
        for role in _ROLES:
            with self.subTest(role=role):
                packet_marker = f"scoped-packet-for-{role}"
                body = _role_body(role)
                spec = AgentTypeSpec(
                    name=role,
                    instructions=body,
                    source=str(_AGENTS_ROOT / f"{role}.md"),
                )
                system = build_child_system_prompt(spec, structured_output=True)
                first_message = build_child_task_message(
                    _request(role, packet_marker),
                    workspace="/workspace/example",
                )

                self.assertIn("workflow orchestration script", system)
                self.assertIn(body, system)
                self.assertIn("structured_output", system)
                self.assertNotIn(packet_marker, system)
                self.assertIn("- Workspace: /workspace/example", first_message)
                self.assertIn(packet_marker, first_message)

    def test_children_are_fresh_sessions_with_profile_context_and_memory_enabled(self):
        run_source = inspect.getsource(HermesChildAgentRunner.run)
        build_source = inspect.getsource(HermesChildAgentRunner._build_agent)
        conversation_source = inspect.getsource(
            HermesChildAgentRunner._run_child_with_timeout
        )

        self.assertIn("uuid.uuid4()", run_source)
        self.assertIn('"skip_context_files": False', build_source)
        self.assertIn('"skip_memory": False', build_source)
        self.assertIn('"session_id": lease.task_id', build_source)
        self.assertIn("history = None", conversation_source)
        self.assertIn("conversation_history=history", conversation_source)
        self.assertNotIn("parent conversation", build_source.lower())

    def test_read_only_roles_declare_capability_policy(self):
        for role in ("initial-orchestrator", "reviewer", "final-orchestrator"):
            with self.subTest(role=role):
                text = (_AGENTS_ROOT / f"{role}.md").read_text(encoding="utf-8")
                self.assertIn("read_only: true", text.split("\n---\n", 1)[0])
    def test_role_packets_are_explicit_and_role_specific(self):
        from hermes_dynamic_workflows.actions import execution, final_validation

        execution_source = inspect.getsource(execution.ReviewedTaskExecutionAction)
        final_source = inspect.getsource(final_validation._validation_prompt)
        planning_source = inspect.getsource(InitialPlanningAction.run)

        self.assertIn("WorkerRequestPacket", execution_source)
        self.assertIn("RepairRequestPacket", execution_source)
        self.assertIn("ReviewRequestPacket", execution_source)
        self.assertIn('"agentType": "worker"', execution_source)
        self.assertIn('"agentType": "reviewer"', execution_source)
        self.assertIn('"agentType": "repair-worker"', execution_source)
        self.assertIn("FinalValidationPacket", final_source)
        self.assertNotIn("Complete reviewed workflow snapshot", final_source)
        self.assertIn('"agentType": "initial-orchestrator"', planning_source)


class InitialPlannerBehaviorContractTests(unittest.TestCase):
    def test_role_requires_minimum_sufficient_model_driven_decomposition(self):
        role = _role_body("initial-orchestrator").lower()

        self.assertIn("fewest independently executable and reviewable tasks", role)
        self.assertIn("produce one task", role)
        self.assertIn("independent deliverables", role)
        self.assertIn("real dependencies", role)
        self.assertIn("artificial discovery", role)
        self.assertIn("exact named paths", role)
        self.assertIn("use empty `allowed_mutations`", role)
        self.assertIn("clear stopping condition", role)
        self.assertIn("workspace, folder, or project", role)

    def test_transport_prompt_is_short_neutral_and_contains_no_fake_plan(self):
        objective = "Read docs/guide.md and report its documented launch command."
        prompt = InitialPlanningAction(
            PlanningLimits(
                max_tasks=7,
                max_repairs_per_task=2,
                max_replanning_cycles=1,
            )
        )._prompt(objective=objective, cycle=2)

        self.assertEqual(prompt.count(objective), 1)
        self.assertIn("Required cycle: 2", prompt)
        self.assertIn("Maximum tasks: 7", prompt)
        self.assertIn("Maximum repairs per task: 2", prompt)
        self.assertIn("Maximum replanning cycles: 1", prompt)
        self.assertNotIn("Example valid PlanPackage", prompt)
        self.assertNotIn('"paths"', prompt)
        self.assertNotIn('"allowed_mutations"', prompt)
        self.assertNotIn("inspect-and-report", prompt)
        self.assertNotIn("repository", prompt.lower())
        self.assertNotIn("codebase", prompt.lower())

    def test_planning_python_does_not_classify_objective_complexity(self):
        source = textwrap.dedent(inspect.getsource(InitialPlanningAction._prompt))
        tree = ast.parse(source)

        self.assertFalse(any(isinstance(node, ast.If) for node in ast.walk(tree)))
        self.assertNotIn("is_simple", source)
        self.assertNotIn("single_file", source)
        self.assertNotIn("handcrafted", source)


class ToolAndStructuredOutputCharacterizationTests(unittest.TestCase):
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

    def test_text_json_cannot_bypass_the_structured_tool(self):
        source = inspect.getsource(HermesChildAgentRunner._run_child_with_timeout)
        self.assertFalse(hasattr(child_runner, "_extract_json_from_text"))
        self.assertNotIn("_extract_json_from_text", source)
        self.assertNotIn("_BROKER.submit", source)

    def test_provider_or_tool_definition_failure_is_classified(self):
        source = inspect.getsource(HermesChildAgentRunner.run)
        self.assertIn("structured output tool definition failed", source)


if __name__ == "__main__":
    unittest.main()
