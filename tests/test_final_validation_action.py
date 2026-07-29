from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any

from hermes_dynamic_workflows.actions.final_validation import FinalValidationAction
from hermes_dynamic_workflows.core.errors import ReviewedStateError
from hermes_dynamic_workflows.core.types import WorkflowFrame, WorkflowState


OBJECTIVE = "Deliver the requested feature with evidence."
CRITERIA = ["The feature works.", "The result is evidence-backed."]


def _task(
    task_id: str,
    *,
    plan_id: str = "plan-1",
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": plan_id,
        "task_id": task_id,
        "objective": f"Complete {task_id}.",
        "depends_on": list(depends_on or []),
        "paths": ["src"],
        "constraints": ["Stay scoped."],
        "allowed_mutations": ["src"],
        "acceptance_criteria": [f"{task_id} is verified."],
        "evidence_requirements": ["Focused test evidence."],
        "worker_instructions": f"Implement {task_id}.",
        "reviewer_guidelines": [f"Reject {task_id} without evidence."],
    }


def _plan(
    *tasks: dict[str, Any],
    plan_id: str = "plan-1",
    cycle: int = 0,
    max_replans: int = 1,
) -> dict[str, Any]:
    selected = list(tasks or (_task("A", plan_id=plan_id),))
    return {
        "schema_version": "1.0",
        "plan_id": plan_id,
        "cycle": cycle,
        "original_objective": OBJECTIVE,
        "tasks": selected,
        "final_validation_criteria": list(CRITERIA),
        "max_repairs_per_task": 2,
        "max_replanning_cycles": max_replans,
    }


def _evidence(reference: str) -> list[dict[str, str]]:
    return [{"kind": "test", "reference": reference, "summary": "Verified."}]


def _validation(
    verdict: str,
    *,
    plan_id: str = "plan-1",
    cycle: int = 0,
    satisfied: tuple[bool, bool] = (True, True),
    delta_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    requirement_results = []
    for criterion, is_satisfied in zip(CRITERIA, satisfied, strict=True):
        requirement_results.append(
            {
                "requirement": criterion,
                "satisfied": is_satisfied,
                "evidence": _evidence(f"criterion:{criterion}"),
                "gap": "" if is_satisfied else f"Gap for {criterion}",
            }
        )
    return {
        "schema_version": "1.0",
        "plan_id": plan_id,
        "cycle": cycle,
        "verdict": verdict,
        "summary": f"Final verdict: {verdict}.",
        "requirement_results": requirement_results,
        "delta_tasks": list(delta_tasks or []),
        "evidence": _evidence(f"final:{cycle}"),
    }


@dataclass
class _Context:
    state: WorkflowState = field(
        default_factory=lambda: WorkflowState(
            WorkflowFrame(id="root", meta={"name": "test"}, args=None, cwd="/repo")
        )
    )
    events: list[dict[str, Any]] = field(default_factory=list)
    notifications: int = 0

    def journal(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def notify(self) -> None:
        self.notifications += 1


class _API:
    def __init__(self, result: Any):
        self.context = _Context()
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def agent(self, prompt: str, opts: dict[str, Any]) -> Any:
        self.calls.append((prompt, opts))
        return self.result


def _finish_task(api: _API, task_id: str, *, outcome: str = "INTEGRATED") -> None:
    state = api.context.state.reviewed
    state.start_task(task_id)
    attempt = {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": task_id,
        "attempt": 1,
        "status": "COMPLETED" if outcome == "INTEGRATED" else outcome,
        "summary": "Worker result.",
        "changed_paths": ["src/example.py"],
        "evidence": _evidence(f"worker:{task_id}"),
        "tests": [{"name": "focused", "status": "PASS"}],
        "blocker": "external" if outcome == "BLOCKED" else None,
    }
    state.submit_worker_result(task_id, attempt)
    verdict = "PASS" if outcome == "INTEGRATED" else outcome
    review = {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": task_id,
        "attempt": 1,
        "verdict": verdict,
        "summary": f"Review {verdict}.",
        "criteria_results": [],
        "feedback": [],
        "evidence": _evidence(f"review:{task_id}"),
    }
    state.submit_review_verdict(task_id, review)
    if outcome == "INTEGRATED":
        state.integrate_task(
            task_id,
            {
                "schema_version": "1.0",
                "plan_id": "plan-1",
                "task_id": task_id,
                "status": "INTEGRATED",
                "summary": "Integrated.",
                "integrated_commit": "abc123",
                "evidence": _evidence(f"integration:{task_id}"),
            },
        )
    elif outcome == "FAIL":
        state.mark_task_failed(task_id)


class FinalValidationActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_approved_records_terminal_validation_without_replan(self):
        api = _API(_validation("APPROVED"))
        api.context.state.reviewed.register_plan(_plan())
        _finish_task(api, "A")

        result = await FinalValidationAction().run(api)

        self.assertEqual(result["status"], "APPROVED")
        self.assertIsNone(result["next_plan"])
        self.assertEqual(len(api.calls), 1)
        prompt, opts = api.calls[0]
        self.assertIn("Validate the integrated project state", prompt)
        self.assertEqual(opts["agentType"], "final-orchestrator")
        self.assertNotIn("isolation", opts)
        snapshot = api.context.state.reviewed.snapshot()
        self.assertEqual(snapshot["planning_cycles"][0]["status"], "APPROVED")
        self.assertEqual(snapshot["final_validations"][0]["verdict"], "APPROVED")
        self.assertTrue(
            any(event["type"] == "reviewed_final_validation_recorded" for event in api.context.events)
        )

    async def test_not_approved_registers_one_bounded_delta_plan(self):
        delta = _task("B", plan_id="plan-2", depends_on=["A"])
        api = _API(
            _validation(
                "NOT_APPROVED",
                satisfied=(True, False),
                delta_tasks=[delta],
            )
        )
        api.context.state.reviewed.register_plan(_plan(max_replans=1))
        _finish_task(api, "A")

        result = await FinalValidationAction().run(api)

        self.assertEqual(result["status"], "REPLANNED")
        self.assertEqual(result["remaining_replanning_cycles"], 0)
        self.assertEqual(result["next_plan"]["plan_id"], "plan-2")
        self.assertEqual(result["next_plan"]["cycle"], 1)
        self.assertEqual(result["next_plan"]["original_objective"], OBJECTIVE)
        self.assertEqual(result["next_plan"]["final_validation_criteria"], CRITERIA)
        snapshot = api.context.state.reviewed.snapshot()
        self.assertEqual([item["plan_id"] for item in snapshot["planning_cycles"]], ["plan-1", "plan-2"])
        self.assertEqual(snapshot["planning_cycles"][0]["status"], "NOT_APPROVED")
        self.assertEqual(snapshot["tasks"][-1]["task_id"], "B")
        self.assertEqual(api.context.state.reviewed.ready_task_ids(), ["B"])
        event = next(item for item in api.context.events if item["type"] == "reviewed_delta_plan_registered")
        self.assertEqual(event["sourcePlanId"], "plan-1")
        self.assertEqual(event["taskIds"], ["B"])

    async def test_blocked_is_explicit_and_does_not_replan(self):
        api = _API(_validation("BLOCKED", satisfied=(True, False)))
        api.context.state.reviewed.register_plan(_plan())
        _finish_task(api, "A", outcome="BLOCKED")

        result = await FinalValidationAction().run(api)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertIsNone(result["next_plan"])
        self.assertEqual(len(api.context.state.reviewed.snapshot()["planning_cycles"]), 1)

    async def test_exhausted_not_approved_cannot_create_more_work(self):
        api = _API(_validation("NOT_APPROVED", satisfied=(False, True)))
        api.context.state.reviewed.register_plan(_plan(max_replans=0))
        _finish_task(api, "A", outcome="FAIL")

        result = await FinalValidationAction().run(api)

        self.assertEqual(result["status"], "EXHAUSTED")
        self.assertIsNone(result["next_plan"])
        self.assertEqual(result["remaining_replanning_cycles"], 0)
        self.assertEqual(len(api.context.state.reviewed.snapshot()["planning_cycles"]), 1)
        self.assertTrue(
            any(event["type"] == "reviewed_replanning_exhausted" for event in api.context.events)
        )

    async def test_nonterminal_cycle_is_rejected_before_launch(self):
        api = _API(_validation("APPROVED"))
        api.context.state.reviewed.register_plan(_plan())

        with self.assertRaisesRegex(ReviewedStateError, "requires terminal task states"):
            await FinalValidationAction().run(api)

        self.assertEqual(api.calls, [])
        self.assertEqual(api.context.state.reviewed.snapshot()["final_validations"], [])

    async def test_requirement_order_and_verdict_semantics_fail_closed(self):
        wrong_order = _validation("APPROVED")
        wrong_order["requirement_results"].reverse()
        api = _API(wrong_order)
        api.context.state.reviewed.register_plan(_plan())
        _finish_task(api, "A")
        with self.assertRaisesRegex(ReviewedStateError, "exactly match"):
            await FinalValidationAction().run(api)

        false_approval = _validation("APPROVED", satisfied=(True, False))
        other = _API(false_approval)
        other.context.state.reviewed.register_plan(_plan())
        _finish_task(other, "A")
        with self.assertRaisesRegex(ReviewedStateError, "APPROVED requires"):
            await FinalValidationAction().run(other)

    async def test_delta_cannot_depend_on_failed_or_blocked_work(self):
        delta = _task("B", plan_id="plan-2", depends_on=["A"])
        api = _API(
            _validation(
                "NOT_APPROVED",
                satisfied=(False, True),
                delta_tasks=[delta],
            )
        )
        api.context.state.reviewed.register_plan(_plan())
        _finish_task(api, "A", outcome="FAIL")

        with self.assertRaisesRegex(ReviewedStateError, "integrated or appear earlier: A"):
            await FinalValidationAction().run(api)

        snapshot = api.context.state.reviewed.snapshot()
        self.assertEqual(snapshot["final_validations"], [])
        self.assertEqual(len(snapshot["planning_cycles"]), 1)

    async def test_delta_ids_and_cycle_lineage_cannot_be_reused(self):
        reused_plan = _task("B", plan_id="plan-1")
        api = _API(
            _validation(
                "NOT_APPROVED",
                satisfied=(False, True),
                delta_tasks=[reused_plan],
            )
        )
        api.context.state.reviewed.register_plan(_plan())
        _finish_task(api, "A")
        with self.assertRaisesRegex(ReviewedStateError, "new plan_id"):
            await FinalValidationAction().run(api)

        duplicate_task = _task("A", plan_id="plan-2")
        other = _API(
            _validation(
                "NOT_APPROVED",
                satisfied=(False, True),
                delta_tasks=[duplicate_task],
            )
        )
        other.context.state.reviewed.register_plan(_plan())
        _finish_task(other, "A")
        with self.assertRaisesRegex(ReviewedStateError, "already registered"):
            await FinalValidationAction().run(other)


if __name__ == "__main__":
    unittest.main()
