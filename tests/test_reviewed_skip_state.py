from __future__ import annotations

import unittest

from hermes_dynamic_workflows.core.errors import ReviewedStateError
from hermes_dynamic_workflows.core.reviewed_state import ReviewedWorkflowState


def _task(task_id: str, *, depends_on: list[str] | None = None) -> dict:
    return {
        "plan_id": "plan-1",
        "task_id": task_id,
        "depends_on": list(depends_on or []),
    }


def _plan() -> dict:
    return {
        "plan_id": "plan-1",
        "cycle": 0,
        "original_objective": "Objective.",
        "tasks": [_task("A"), _task("B", depends_on=["A"])],
    }


def _worker_failed() -> dict:
    return {"plan_id": "plan-1", "task_id": "A", "attempt": 1, "status": "FAILED"}


def _review_failed() -> dict:
    return {"plan_id": "plan-1", "task_id": "A", "attempt": 1, "verdict": "FAIL"}


class ReviewedSkippedStateTests(unittest.TestCase):
    def test_planned_task_can_be_skipped_only_after_terminal_nonintegrated_dependency(self):
        state = ReviewedWorkflowState()
        state.register_plan(_plan())

        with self.assertRaisesRegex(ReviewedStateError, "terminal non-integrated dependency"):
            state.skip_task("B", "A is not ready.")
        with self.assertRaisesRegex(ReviewedStateError, "terminal non-integrated dependency"):
            state.skip_task("A", "No dependency.")

        state.start_task("A")
        state.submit_worker_result("A", _worker_failed())
        state.submit_review_verdict("A", _review_failed())
        state.mark_task_failed("A")
        state.skip_task("B", "Required dependency did not integrate: A=FAILED")

        tasks = {item["task_id"]: item for item in state.snapshot()["tasks"]}
        self.assertEqual(tasks["B"]["status"], "SKIPPED")
        self.assertEqual(
            tasks["B"]["skip_reason"],
            "Required dependency did not integrate: A=FAILED",
        )
        self.assertEqual(tasks["B"]["worker_attempts"], [])
        self.assertEqual(state.ready_task_ids(), [])

    def test_skip_reason_and_transition_are_fail_closed(self):
        state = ReviewedWorkflowState()
        state.register_plan(_plan())
        state.start_task("A")
        state.submit_worker_result("A", _worker_failed())
        state.submit_review_verdict("A", _review_failed())
        state.mark_task_failed("A")

        with self.assertRaisesRegex(ReviewedStateError, "non-empty"):
            state.skip_task("B", "   ")
        state.skip_task("B", "Dependency A failed.")
        with self.assertRaisesRegex(ReviewedStateError, "SKIPPED -> SKIPPED"):
            state.skip_task("B", "Again.")


if __name__ == "__main__":
    unittest.main()
