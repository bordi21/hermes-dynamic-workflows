from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any

from hermes_dynamic_workflows.actions.planning import InitialPlanningAction, PlanningLimits
from hermes_dynamic_workflows.core.errors import ReviewedStateError
from hermes_dynamic_workflows.core.types import WorkflowFrame, WorkflowState


OBJECTIVE = "Implement the requested feature and prove it works."


def _task(task_id: str, *, depends_on: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": task_id,
        "objective": f"Complete {task_id}.",
        "depends_on": list(depends_on or []),
        "paths": ["src"],
        "constraints": ["Stay within the task packet."],
        "allowed_mutations": ["src"],
        "acceptance_criteria": [f"{task_id} is verified."],
        "evidence_requirements": ["Relevant tests and changed paths."],
        "worker_instructions": f"Implement {task_id} only.",
        "reviewer_guidelines": [f"Reject {task_id} when evidence is missing."],
    }


def _plan(*tasks: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "cycle": 0,
        "original_objective": OBJECTIVE,
        "tasks": list(tasks or (_task("A"),)),
        "final_validation_criteria": ["The original objective is satisfied with evidence."],
        "max_repairs_per_task": 2,
        "max_replanning_cycles": 1,
    }


@dataclass
class _FakeContext:
    state: WorkflowState = field(
        default_factory=lambda: WorkflowState(
            WorkflowFrame(id="root", meta={"name": "test"}, args=None, cwd="/tmp")
        )
    )
    journal_events: list[dict[str, Any]] = field(default_factory=list)
    notify_count: int = 0

    def journal(self, event: dict[str, Any]) -> None:
        self.journal_events.append(event)

    def notify(self) -> None:
        self.notify_count += 1


class _FakeAPI:
    def __init__(self, result: Any = None, error: BaseException | None = None):
        self.context = _FakeContext()
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def agent(self, prompt: str, opts: dict[str, Any]) -> Any:
        self.calls.append((prompt, opts))
        if self.error is not None:
            raise self.error
        return self.result


class InitialPlanningActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_initial_orchestrator_builds_and_registers_plan(self):
        expected = _plan(_task("A"), _task("B", depends_on=["A"]))
        api = _FakeAPI(expected)
        action = InitialPlanningAction()

        result = await action.run(api, original_objective=f"  {OBJECTIVE}  ", cycle=0)

        self.assertEqual(result, expected)
        self.assertIsNot(result, expected)
        self.assertEqual(len(api.calls), 1)
        prompt, opts = api.calls[0]
        self.assertIn("Do not execute, review, repair, or integrate", prompt)
        self.assertIn("Maximum tasks: 64", prompt)
        self.assertEqual(opts["agentType"], "initial-orchestrator")
        self.assertEqual(opts["isolation"], "shared")
        self.assertEqual(opts["phase"], "Planning")
        self.assertEqual(opts["schema"]["title"], "PlanPackage")

        reviewed = api.context.state.reviewed.snapshot()
        self.assertEqual(reviewed["planning_cycles"][0]["plan_id"], "plan-1")
        self.assertEqual([item["task_id"] for item in reviewed["tasks"]], ["A", "B"])
        self.assertEqual(api.context.notify_count, 1)
        self.assertEqual(api.context.journal_events[0]["type"], "reviewed_plan_registered")
        self.assertEqual(api.context.journal_events[0]["taskIds"], ["A", "B"])

    async def test_planner_failure_propagates_and_registers_nothing(self):
        error = RuntimeError("planner unavailable")
        api = _FakeAPI(error=error)

        with self.assertRaisesRegex(RuntimeError, "planner unavailable"):
            await InitialPlanningAction().run(api, original_objective=OBJECTIVE)

        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.context.state.reviewed.snapshot()["planning_cycles"], [])
        self.assertEqual(api.context.notify_count, 0)
        self.assertEqual(api.context.journal_events, [])

    async def test_invalid_schema_is_rejected_fail_closed(self):
        invalid = _plan(_task("A"))
        invalid["tasks"][0].pop("reviewer_guidelines")
        api = _FakeAPI(invalid)

        with self.assertRaisesRegex(ReviewedStateError, "invalid PlanPackage"):
            await InitialPlanningAction().run(api, original_objective=OBJECTIVE)

        self.assertEqual(api.context.state.reviewed.snapshot()["tasks"], [])

    async def test_objective_and_cycle_must_be_preserved(self):
        wrong_objective = _plan(_task("A"))
        wrong_objective["original_objective"] = "Narrowed objective."
        with self.assertRaisesRegex(ReviewedStateError, "preserve original_objective"):
            await InitialPlanningAction().run(
                _FakeAPI(wrong_objective), original_objective=OBJECTIVE
            )

        wrong_cycle = _plan(_task("A"))
        wrong_cycle["cycle"] = 1
        with self.assertRaisesRegex(ReviewedStateError, "cycle mismatch"):
            await InitialPlanningAction().run(
                _FakeAPI(wrong_cycle), original_objective=OBJECTIVE, cycle=0
            )

    async def test_dependencies_must_reference_earlier_tasks(self):
        plan = _plan(_task("A", depends_on=["B"]), _task("B"))
        api = _FakeAPI(plan)

        with self.assertRaisesRegex(ReviewedStateError, "dependency must appear earlier: B"):
            await InitialPlanningAction().run(api, original_objective=OBJECTIVE)

        self.assertEqual(api.context.state.reviewed.snapshot()["tasks"], [])

    async def test_duplicate_tasks_and_dependencies_are_rejected(self):
        duplicate_task = _plan(_task("A"), _task("A"))
        with self.assertRaisesRegex(ReviewedStateError, "duplicate task_id"):
            await InitialPlanningAction().run(
                _FakeAPI(duplicate_task), original_objective=OBJECTIVE
            )

        duplicate_dependency = _plan(
            _task("A"), _task("B", depends_on=["A", "A"])
        )
        with self.assertRaisesRegex(ReviewedStateError, "repeats dependency A"):
            await InitialPlanningAction().run(
                _FakeAPI(duplicate_dependency), original_objective=OBJECTIVE
            )

    async def test_action_owned_caps_reject_oversized_plan_and_retry_limits(self):
        limits = PlanningLimits(
            max_tasks=1,
            max_repairs_per_task=1,
            max_replanning_cycles=0,
        )
        action = InitialPlanningAction(limits)

        too_many = _plan(_task("A"), _task("B", depends_on=["A"]))
        too_many["max_repairs_per_task"] = 1
        too_many["max_replanning_cycles"] = 0
        with self.assertRaisesRegex(ReviewedStateError, "exceeds task cap"):
            await action.run(_FakeAPI(too_many), original_objective=OBJECTIVE)

        too_many_repairs = _plan(_task("A"))
        too_many_repairs["max_repairs_per_task"] = 2
        too_many_repairs["max_replanning_cycles"] = 0
        with self.assertRaisesRegex(ReviewedStateError, "max_repairs_per_task cap"):
            await action.run(_FakeAPI(too_many_repairs), original_objective=OBJECTIVE)

        too_many_replans = _plan(_task("A"))
        too_many_replans["max_repairs_per_task"] = 1
        too_many_replans["max_replanning_cycles"] = 1
        with self.assertRaisesRegex(ReviewedStateError, "max_replanning_cycles cap"):
            await action.run(_FakeAPI(too_many_replans), original_objective=OBJECTIVE)

    async def test_input_validation_does_not_launch_planner(self):
        api = _FakeAPI(_plan(_task("A")))
        with self.assertRaisesRegex(ReviewedStateError, "non-empty"):
            await InitialPlanningAction().run(api, original_objective="   ")
        with self.assertRaisesRegex(ReviewedStateError, "non-negative integer"):
            await InitialPlanningAction().run(api, original_objective=OBJECTIVE, cycle=-1)
        self.assertEqual(api.calls, [])


class PlanningLimitsTests(unittest.TestCase):
    def test_invalid_limits_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "max_tasks"):
            PlanningLimits(max_tasks=0)
        with self.assertRaisesRegex(ValueError, "max_repairs_per_task"):
            PlanningLimits(max_repairs_per_task=-1)
        with self.assertRaisesRegex(ValueError, "max_replanning_cycles"):
            PlanningLimits(max_replanning_cycles=-1)


if __name__ == "__main__":
    unittest.main()
