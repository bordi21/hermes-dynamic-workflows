from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any

from hermes_dynamic_workflows.actions.reporting import TerminalReportAction
from hermes_dynamic_workflows.core.types import WorkflowFrame, WorkflowState


OBJECTIVE = "Deliver a dependency-aware result."
CRITERION = "The complete dependency chain succeeds."


def _evidence(reference: str) -> list[dict[str, str]]:
    return [{"kind": "state", "reference": reference, "summary": "Persisted evidence."}]


def _task(task_id: str, *, depends_on: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": task_id,
        "objective": f"Complete {task_id}.",
        "depends_on": list(depends_on or []),
        "paths": ["src"],
        "constraints": ["Stay scoped."],
        "allowed_mutations": ["src"],
        "acceptance_criteria": [f"{task_id} succeeds."],
        "evidence_requirements": ["State evidence."],
        "worker_instructions": f"Execute {task_id}.",
        "reviewer_guidelines": [f"Review {task_id}."],
    }


def _plan() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "cycle": 0,
        "original_objective": OBJECTIVE,
        "tasks": [_task("A"), _task("B", depends_on=["A"])],
        "final_validation_criteria": [CRITERION],
        "max_repairs_per_task": 0,
        "max_replanning_cycles": 0,
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
    def __init__(self):
        self.context = _Context()


class TerminalReportSkippedTests(unittest.TestCase):
    def test_skipped_task_is_visible_with_zero_attempts_and_exact_reason(self):
        api = _API()
        state = api.context.state.reviewed
        state.register_plan(_plan())
        state.start_task("A")
        state.submit_worker_result(
            "A",
            {
                "plan_id": "plan-1",
                "task_id": "A",
                "attempt": 1,
                "status": "FAILED",
                "summary": "A failed.",
                "evidence": _evidence("worker:A"),
            },
        )
        state.submit_review_verdict(
            "A",
            {
                "plan_id": "plan-1",
                "task_id": "A",
                "attempt": 1,
                "verdict": "FAIL",
                "summary": "A did not pass review.",
                "feedback": ["Repair A."],
                "evidence": _evidence("review:A"),
            },
        )
        state.mark_task_failed("A")
        reason = "Required dependency did not integrate: A=FAILED"
        state.skip_task("B", reason)
        state.record_final_validation(
            {
                "schema_version": "1.0",
                "plan_id": "plan-1",
                "cycle": 0,
                "verdict": "NOT_APPROVED",
                "summary": "Dependency chain did not complete.",
                "requirement_results": [
                    {
                        "requirement": CRITERION,
                        "satisfied": False,
                        "evidence": _evidence("requirement:chain"),
                        "gap": "A failed and B could not run.",
                    }
                ],
                "delta_tasks": [],
                "evidence": _evidence("validation:0"),
            }
        )

        report = TerminalReportAction().run(api)

        self.assertEqual(report["outcome"], "FAILED")
        skipped = next(item for item in report["task_summaries"] if item["task_id"] == "B")
        self.assertEqual(skipped["outcome"], "SKIPPED")
        self.assertEqual(skipped["attempts"], 0)
        self.assertEqual(skipped["summary"], reason)
        self.assertTrue(any(f"Task B skipped: {reason}" == item for item in report["unresolved"]))
        self.assertIn("1 skipped", report["summary"])


if __name__ == "__main__":
    unittest.main()
