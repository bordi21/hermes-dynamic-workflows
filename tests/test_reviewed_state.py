from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_dynamic_workflows.core.errors import ReviewedStateError
from hermes_dynamic_workflows.core.reviewed_state import ReviewedWorkflowState
from hermes_dynamic_workflows.core.types import WorkflowFrame, WorkflowState
from hermes_dynamic_workflows.storage.store import WorkflowStore


def _task(task_id: str, *, depends_on: list[str] | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": task_id,
        "objective": f"Complete {task_id}",
        "depends_on": list(depends_on or []),
        "paths": ["src"],
        "constraints": ["stay scoped"],
        "allowed_mutations": ["src"],
        "acceptance_criteria": ["verified"],
        "evidence_requirements": ["test output"],
        "worker_instructions": "Execute the task.",
        "reviewer_guidelines": ["Reject missing evidence."],
    }


def _plan(*tasks: dict) -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "cycle": 0,
        "original_objective": "Deliver a reviewed result.",
        "tasks": list(tasks),
        "final_validation_criteria": ["All required tasks are integrated."],
        "max_repairs_per_task": 2,
        "max_replanning_cycles": 1,
    }


def _worker_result(task_id: str, *, attempt: int = 1, status: str = "COMPLETED") -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": task_id,
        "attempt": attempt,
        "status": status,
        "summary": f"Worker result for {task_id}",
        "changed_paths": ["src/example.py"],
        "evidence": [{"kind": "test", "reference": "tests:green"}],
        "tests": [{"name": "unit", "status": "PASS"}],
        "blocker": None,
    }


def _review(task_id: str, *, attempt: int = 1, verdict: str = "PASS") -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": task_id,
        "attempt": attempt,
        "verdict": verdict,
        "summary": f"Review {verdict}",
        "criteria_results": [
            {
                "criterion": "verified",
                "passed": verdict == "PASS",
                "evidence": [{"kind": "test", "reference": "tests:green"}],
                "feedback": "" if verdict == "PASS" else "Fix the defect.",
            }
        ],
        "feedback": [] if verdict == "PASS" else ["Fix the defect."],
        "evidence": [{"kind": "test", "reference": "tests:green"}],
    }


def _repair(task_id: str, *, repair_attempt: int = 1) -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": task_id,
        "repair_attempt": repair_attempt,
        "original_task": _task(task_id),
        "previous_result": _worker_result(task_id, status="FAILED"),
        "review_verdict": _review(task_id, verdict="FAIL"),
    }


def _integration(task_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": task_id,
        "status": "INTEGRATED",
        "summary": f"Integrated {task_id}",
        "integrated_commit": "abc123",
        "evidence": [{"kind": "diff", "reference": "commit:abc123"}],
    }


def _final_validation() -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "cycle": 0,
        "verdict": "APPROVED",
        "summary": "Objective satisfied.",
        "requirement_results": [
            {
                "requirement": "All required tasks are integrated.",
                "satisfied": True,
                "evidence": [{"kind": "state", "reference": "task:A:INTEGRATED"}],
                "gap": "",
            }
        ],
        "delta_tasks": [],
        "evidence": [{"kind": "state", "reference": "reviewed-snapshot"}],
    }


def _terminal_report() -> dict:
    return {
        "schema_version": "1.0",
        "original_objective": "Deliver a reviewed result.",
        "outcome": "APPROVED",
        "summary": "Complete.",
        "planning_cycles": 1,
        "task_summaries": [
            {"task_id": "A", "outcome": "PASS", "attempts": 1, "summary": "Integrated."}
        ],
        "final_validation": _final_validation(),
        "unresolved": [],
        "evidence": [{"kind": "state", "reference": "reviewed-snapshot"}],
    }


class ReviewedWorkflowStateTests(unittest.TestCase):
    def test_workflow_snapshot_contains_canonical_reviewed_state(self):
        state = WorkflowState(
            WorkflowFrame(id="root", meta={"name": "test"}, args=None, cwd="/tmp")
        )

        snapshot = state.snapshot()

        self.assertEqual(snapshot["reviewed"]["schema_version"], "1.0")
        self.assertEqual(snapshot["reviewed"]["planning_cycles"], [])
        self.assertEqual(snapshot["reviewed"]["tasks"], [])
        self.assertIsNone(snapshot["reviewed"]["terminal_report"])

    def test_dependency_readiness_requires_integrated_dependencies(self):
        state = ReviewedWorkflowState()
        state.register_plan(_plan(_task("A"), _task("B", depends_on=["A"])))

        self.assertEqual(state.ready_task_ids(), ["A"])
        with self.assertRaisesRegex(ReviewedStateError, "dependencies are not integrated"):
            state.start_task("B")

        state.start_task("A")
        state.submit_worker_result("A", _worker_result("A"))
        state.submit_review_verdict("A", _review("A"))
        state.integrate_task("A", _integration("A"))

        self.assertEqual(state.ready_task_ids(), ["B"])

    def test_happy_path_records_complete_lineage(self):
        state = ReviewedWorkflowState()
        state.register_plan(_plan(_task("A")))
        state.start_task("A")
        state.submit_worker_result("A", _worker_result("A"))
        state.submit_review_verdict("A", _review("A"))
        state.integrate_task("A", _integration("A"))
        state.record_final_validation(_final_validation())
        state.set_terminal_report(_terminal_report())

        snapshot = state.snapshot()
        task = snapshot["tasks"][0]

        self.assertEqual(task["status"], "INTEGRATED")
        self.assertEqual(len(task["worker_attempts"]), 1)
        self.assertEqual(task["review_verdicts"][0]["verdict"], "PASS")
        self.assertEqual(task["integration"]["status"], "INTEGRATED")
        self.assertEqual(snapshot["planning_cycles"][0]["status"], "APPROVED")
        self.assertEqual(snapshot["final_validations"][0]["verdict"], "APPROVED")
        self.assertEqual(snapshot["terminal_report"]["outcome"], "APPROVED")

    def test_fail_repair_review_and_integration_lineage(self):
        state = ReviewedWorkflowState()
        state.register_plan(_plan(_task("A")))
        state.start_task("A")
        state.submit_worker_result("A", _worker_result("A", status="FAILED"))
        state.submit_review_verdict("A", _review("A", verdict="FAIL"))
        state.start_repair("A", _repair("A"))
        state.submit_repair_result("A", _worker_result("A", attempt=2))
        state.submit_review_verdict("A", _review("A", attempt=2))
        state.integrate_task("A", _integration("A"))

        task = state.snapshot()["tasks"][0]
        self.assertEqual(task["status"], "INTEGRATED")
        self.assertEqual([item["attempt"] for item in task["worker_attempts"]], [1, 2])
        self.assertEqual([item["verdict"] for item in task["review_verdicts"]], ["FAIL", "PASS"])
        self.assertEqual(task["repair_attempts"][0]["repair"]["repair_attempt"], 1)
        self.assertEqual(task["repair_attempts"][0]["worker_result"]["attempt"], 2)

    def test_illegal_transition_and_accept_without_review_are_rejected(self):
        state = ReviewedWorkflowState()
        state.register_plan(_plan(_task("A")))

        with self.assertRaisesRegex(ReviewedStateError, "PLANNED -> INTEGRATED"):
            state.integrate_task("A", _integration("A"))
        with self.assertRaisesRegex(ReviewedStateError, "PLANNED -> FAILED"):
            state.mark_task_failed("A")

    def test_missing_or_invalid_review_verdict_is_rejected(self):
        state = ReviewedWorkflowState()
        state.register_plan(_plan(_task("A")))
        state.start_task("A")
        state.submit_worker_result("A", _worker_result("A"))
        invalid = _review("A")
        invalid.pop("verdict")

        with self.assertRaisesRegex(ReviewedStateError, "must be PASS, FAIL, or BLOCKED"):
            state.submit_review_verdict("A", invalid)

        self.assertEqual(state.snapshot()["tasks"][0]["status"], "REVIEWING")

    def test_failed_worker_result_cannot_be_passed(self):
        state = ReviewedWorkflowState()
        state.register_plan(_plan(_task("A")))
        state.start_task("A")
        state.submit_worker_result("A", _worker_result("A", status="FAILED"))

        with self.assertRaisesRegex(ReviewedStateError, "cannot PASS"):
            state.submit_review_verdict("A", _review("A", verdict="PASS"))

    def test_unknown_dependency_and_duplicate_plan_are_rejected(self):
        state = ReviewedWorkflowState()
        with self.assertRaisesRegex(ReviewedStateError, "unknown dependency"):
            state.register_plan(_plan(_task("A", depends_on=["missing"])))

        state.register_plan(_plan(_task("A")))
        with self.assertRaisesRegex(ReviewedStateError, "plan_id is already registered"):
            state.register_plan(_plan(_task("B")))

    def test_reviewed_snapshot_persists_in_existing_run_store(self):
        state = WorkflowState(
            WorkflowFrame(id="root", meta={"name": "test"}, args=None, cwd="/tmp")
        )
        state.reviewed.register_plan(_plan(_task("A")))
        state.reviewed.start_task("A")
        state.reviewed.submit_worker_result("A", _worker_result("A"))
        state.reviewed.submit_review_verdict("A", _review("A"))
        state.reviewed.integrate_task("A", _integration("A"))

        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp))
            record = {
                "runId": "wf_abcdef12-345",
                "taskId": "wg1234567",
                "workflow": state.snapshot(),
            }
            store.save_run(record)
            loaded = store.load_run("wf_abcdef12-345")

        self.assertIsNotNone(loaded)
        assert loaded is not None
        reviewed = loaded["workflow"]["reviewed"]
        self.assertEqual(reviewed["tasks"][0]["status"], "INTEGRATED")
        self.assertEqual(reviewed["tasks"][0]["review_verdicts"][0]["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
