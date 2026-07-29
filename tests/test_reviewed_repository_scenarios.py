from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any

from hermes_dynamic_workflows.actions.planning import InitialPlanningAction
from hermes_dynamic_workflows.core.types import WorkflowFrame, WorkflowState


OBJECTIVE = "Verify the requested workspace result."


def task(
    task_id: str,
    *,
    path: str,
    depends_on: list[str] | None = None,
    read_only: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-scenarios",
        "task_id": task_id,
        "objective": f"Complete {task_id} against {path}.",
        "depends_on": list(depends_on or []),
        "paths": [path],
        "constraints": ["Stay inside the exact packet."],
        "allowed_mutations": [] if read_only else [path],
        "acceptance_criteria": [f"{task_id} has focused evidence."],
        "evidence_requirements": ["Record the exact relevant check."],
        "worker_instructions": f"Complete {task_id} and stop after its criterion is evidenced.",
        "reviewer_guidelines": [f"Reject {task_id} without focused evidence."],
    }


def plan(*tasks: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-scenarios",
        "cycle": 0,
        "original_objective": OBJECTIVE,
        "tasks": list(tasks),
        "final_validation_criteria": ["The requested workspace result is verified."],
        "max_repairs_per_task": 1,
        "max_replanning_cycles": 0,
    }


@dataclass
class Context:
    state: WorkflowState = field(
        default_factory=lambda: WorkflowState(
            WorkflowFrame(id="root", meta={"name": "scenario"}, args=None, cwd="/workspace")
        )
    )
    events: list[dict[str, Any]] = field(default_factory=list)

    def journal(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def notify(self) -> None:
        pass


class API:
    def __init__(self, result: dict[str, Any]):
        self.result = result
        self.context = Context()
        self.calls = []

    async def agent(self, prompt: str, opts: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((prompt, opts))
        return self.result


class RepositoryIntegrationScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_named_file_read_only_request_registers_one_precise_task(self):
        expected = plan(task("read-guide", path="docs/guide.md", read_only=True))
        api = API(expected)
        result = await InitialPlanningAction().run(api, original_objective=OBJECTIVE)

        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["paths"], ["docs/guide.md"])
        self.assertEqual(result["tasks"][0]["allowed_mutations"], [])
        self.assertEqual(api.calls[0][1]["agentType"], "initial-orchestrator")

    async def test_small_precise_modification_keeps_one_bounded_deliverable(self):
        expected = plan(task("update-config", path="config/settings.yaml"))
        result = await InitialPlanningAction().run(API(expected), original_objective=OBJECTIVE)

        self.assertEqual([item["task_id"] for item in result["tasks"]], ["update-config"])
        self.assertEqual(result["tasks"][0]["allowed_mutations"], ["config/settings.yaml"])

    async def test_decomposable_objective_preserves_independent_and_dependent_tasks(self):
        expected = plan(
            task("schema", path="src/schema.py"),
            task("docs", path="docs/guide.md", read_only=False),
            task("integration", path="tests/test_integration.py", depends_on=["schema", "docs"]),
        )
        result = await InitialPlanningAction().run(API(expected), original_objective=OBJECTIVE)

        self.assertEqual([item["task_id"] for item in result["tasks"]], ["schema", "docs", "integration"])
        self.assertEqual(result["tasks"][2]["depends_on"], ["schema", "docs"])


if __name__ == "__main__":
    unittest.main()
