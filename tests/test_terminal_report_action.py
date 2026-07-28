from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any

from hermes_dynamic_workflows.actions.reporting import TerminalReportAction
from hermes_dynamic_workflows.core.errors import ReviewedStateError
from hermes_dynamic_workflows.core.types import WorkflowFrame, WorkflowState


OBJECTIVE = "Deliver the requested feature with evidence."
CRITERIA = ["The feature works.", "The result is evidence-backed."]


def _evidence(reference: str) -> list[dict[str, str]]:
    return [{"kind": "test", "reference": reference, "summary": "Verified."}]


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
        "acceptance_criteria": [f"{task_id} is verified."],
        "evidence_requirements": ["Focused test evidence."],
        "worker_instructions": f"Implement {task_id}.",
        "reviewer_guidelines": [f"Reject {task_id} without evidence."],
    }


def _plan(*tasks: dict[str, Any], max_replans: int = 0) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "cycle": 0,
        "original_objective": OBJECTIVE,
        "tasks": list(tasks or (_task("A"),)),
        "final_validation_criteria": list(CRITERIA),
        "max_repairs_per_task": 1,
        "max_replanning_cycles": max_replans,
    }


def _validation(
    verdict: str,
    *,
    satisfied: tuple[bool, bool] = (True, True),
) -> dict[str, Any]:
    results = []
    for criterion, is_satisfied in zip(CRITERIA, satisfied, strict=True):
        results.append(
            {
                "requirement": criterion,
                "satisfied": is_satisfied,
                "evidence": _evidence(f"criterion:{criterion}"),
                "gap": "" if is_satisfied else f"Gap for {criterion}",
            }
        )
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "cycle": 0,
        "verdict": verdict,
        "summary": f"Final verdict: {verdict}.",
        "requirement_results": results,
        "delta_tasks": [],
        "evidence": _evidence("final:0"),
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


def _finish_task(
    api: _API,
    task_id: str,
    *,
    outcome: str,
    blocker: str | None = None,
) -> None:
    state = api.context.state.reviewed
    state.start_task(task_id)
    worker_status = {
        "INTEGRATED": "COMPLETED",
        "FAILED": "FAILED",
        "BLOCKED": "BLOCKED",
    }[outcome]
    result = {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": task_id,
        "attempt": 1,
        "status": worker_status,
        "summary": f"Worker ended {worker_status}.",
        "changed_paths": [f"src/{task_id}.py"],
        "evidence": _evidence(f"worker:{task_id}"),
        "tests": [{"name": f"test-{task_id}", "status": "PASS" if outcome == "INTEGRATED" else "FAIL"}],
        "blocker": blocker,
    }
    state.submit_worker_result(task_id, result)
    verdict = {
        "INTEGRATED": "PASS",
        "FAILED": "FAIL",
        "BLOCKED": "BLOCKED",
    }[outcome]
    review = {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": task_id,
        "attempt": 1,
        "verdict": verdict,
        "summary": f"Reviewer returned {verdict}.",
        "criteria_results": [
            {
                "criterion": f"{task_id} is verified.",
                "passed": verdict == "PASS",
                "evidence": _evidence(f"review-criterion:{task_id}"),
                "feedback": "" if verdict == "PASS" else f"Resolve {task_id}.",
            }
        ],
        "feedback": [] if verdict == "PASS" else [f"Resolve {task_id}."],
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
                "summary": f"Integrated {task_id}.",
                "integrated_commit": f"commit-{task_id}",
                "evidence": _evidence(f"integration:{task_id}"),
            },
        )
    elif outcome == "FAILED":
        state.mark_task_failed(task_id)


class TerminalReportActionTests(unittest.TestCase):
    def test_approved_report_is_derived_persisted_and_journaled(self):
        api = _API()
        api.context.state.reviewed.register_plan(_plan())
        _finish_task(api, "A", outcome="INTEGRATED")
        api.context.state.reviewed.record_final_validation(_validation("APPROVED"))

        report = TerminalReportAction().run(api)

        self.assertEqual(report["outcome"], "APPROVED")
        self.assertEqual(report["original_objective"], OBJECTIVE)
        self.assertEqual(report["planning_cycles"], 1)
        self.assertEqual(
            report["task_summaries"],
            [{"task_id": "A", "outcome": "PASS", "attempts": 1, "summary": "Integrated A."}],
        )
        self.assertEqual(report["unresolved"], [])
        references = {item["reference"] for item in report["evidence"]}
        self.assertTrue({"final:0", "integration:A", "review:A", "worker:A"}.issubset(references))
        snapshot = api.context.state.reviewed.snapshot()
        self.assertEqual(snapshot["terminal_report"], report)
        self.assertEqual(api.context.notifications, 1)
        self.assertEqual(api.context.events[0]["type"], "reviewed_terminal_report_recorded")
        self.assertEqual(api.context.events[0]["outcome"], "APPROVED")

    def test_blocked_report_exposes_requirement_gap_and_exact_blocker(self):
        api = _API()
        api.context.state.reviewed.register_plan(_plan())
        _finish_task(api, "A", outcome="BLOCKED", blocker="Missing production credential.")
        api.context.state.reviewed.record_final_validation(
            _validation("BLOCKED", satisfied=(False, True))
        )

        report = TerminalReportAction().run(api)

        self.assertEqual(report["outcome"], "BLOCKED")
        self.assertEqual(report["task_summaries"][0]["outcome"], "BLOCKED")
        self.assertTrue(any("Gap for The feature works." in item for item in report["unresolved"]))
        self.assertTrue(any("Missing production credential." in item for item in report["unresolved"]))
        self.assertTrue(any("Resolve A." in item for item in report["unresolved"]))

    def test_exhausted_not_approved_with_integrated_work_is_partial(self):
        api = _API()
        api.context.state.reviewed.register_plan(_plan(_task("A"), _task("B")))
        _finish_task(api, "A", outcome="INTEGRATED")
        _finish_task(api, "B", outcome="FAILED")
        api.context.state.reviewed.record_final_validation(
            _validation("NOT_APPROVED", satisfied=(True, False))
        )

        report = TerminalReportAction().run(api)

        self.assertEqual(report["outcome"], "PARTIAL")
        self.assertEqual(
            [item["outcome"] for item in report["task_summaries"]],
            ["PASS", "FAIL"],
        )
        self.assertTrue(any("Task B failed" in item for item in report["unresolved"]))
        self.assertTrue(
            any("replanning limit exhausted" in item.lower() for item in report["unresolved"])
        )

    def test_exhausted_not_approved_without_integrated_work_is_failed(self):
        api = _API()
        api.context.state.reviewed.register_plan(_plan())
        _finish_task(api, "A", outcome="FAILED")
        api.context.state.reviewed.record_final_validation(
            _validation("NOT_APPROVED", satisfied=(False, False))
        )

        report = TerminalReportAction().run(api)

        self.assertEqual(report["outcome"], "FAILED")
        self.assertTrue(any("Workflow failed" in item for item in report["unresolved"]))

    def test_report_is_rejected_while_replanning_remains_available(self):
        api = _API()
        api.context.state.reviewed.register_plan(_plan(max_replans=1))
        _finish_task(api, "A", outcome="FAILED")
        api.context.state.reviewed.record_final_validation(
            _validation("NOT_APPROVED", satisfied=(False, True))
        )

        with self.assertRaisesRegex(ReviewedStateError, "replanning remains available"):
            TerminalReportAction().run(api)

        self.assertIsNone(api.context.state.reviewed.snapshot()["terminal_report"])
        self.assertEqual(api.context.events, [])

    def test_report_is_rejected_when_any_task_is_nonterminal(self):
        api = _API()
        api.context.state.reviewed.register_plan(_plan(_task("A"), _task("B")))
        _finish_task(api, "A", outcome="INTEGRATED")
        api.context.state.reviewed.record_final_validation(_validation("APPROVED"))

        with self.assertRaisesRegex(ReviewedStateError, "still active: B"):
            TerminalReportAction().run(api)

    def test_approved_outcome_still_exposes_failed_redundant_task(self):
        api = _API()
        api.context.state.reviewed.register_plan(_plan(_task("A"), _task("B")))
        _finish_task(api, "A", outcome="INTEGRATED")
        _finish_task(api, "B", outcome="FAILED")
        api.context.state.reviewed.record_final_validation(_validation("APPROVED"))

        report = TerminalReportAction().run(api)

        self.assertEqual(report["outcome"], "APPROVED")
        failed = next(item for item in report["task_summaries"] if item["task_id"] == "B")
        self.assertEqual(failed["outcome"], "FAIL")
        self.assertTrue(any("Task B failed" in item for item in report["unresolved"]))
        self.assertIn("1 failed", report["summary"])

    def test_terminal_report_can_be_recorded_only_once(self):
        api = _API()
        api.context.state.reviewed.register_plan(_plan())
        _finish_task(api, "A", outcome="INTEGRATED")
        api.context.state.reviewed.record_final_validation(_validation("APPROVED"))
        TerminalReportAction().run(api)

        with self.assertRaisesRegex(ReviewedStateError, "already recorded"):
            TerminalReportAction().run(api)


if __name__ == "__main__":
    unittest.main()
