from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any

from hermes_dynamic_workflows.actions.execution import ReviewedTaskExecutionAction
from hermes_dynamic_workflows.core.errors import ReviewedStateError
from hermes_dynamic_workflows.core.types import WorkflowFrame, WorkflowState


def _task(task_id: str = "A", depends_on: list[str] | None = None) -> dict[str, Any]:
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


def _plan(*tasks: dict[str, Any], repairs: int = 2) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "cycle": 0,
        "original_objective": "Deliver reviewed work.",
        "tasks": list(tasks or (_task(),)),
        "final_validation_criteria": ["The original objective is satisfied."],
        "max_repairs_per_task": repairs,
        "max_replanning_cycles": 1,
    }


def _worker(
    *,
    attempt: int,
    status: str = "COMPLETED",
    task_id: str = "A",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": task_id,
        "attempt": attempt,
        "status": status,
        "summary": f"Worker attempt {attempt}.",
        "changed_paths": ["src/example.py"],
        "evidence": [{"kind": "test", "reference": f"attempt:{attempt}"}],
        "tests": [{"name": "focused", "status": "PASS" if status == "COMPLETED" else "FAIL"}],
        "blocker": "external dependency" if status == "BLOCKED" else None,
    }


def _review(*, attempt: int, verdict: str = "PASS", task_id: str = "A") -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": task_id,
        "attempt": attempt,
        "verdict": verdict,
        "summary": f"Reviewer returned {verdict}.",
        "criteria_results": [
            {
                "criterion": f"{task_id} is verified.",
                "passed": verdict == "PASS",
                "evidence": [{"kind": "test", "reference": f"attempt:{attempt}"}],
                "feedback": "" if verdict == "PASS" else "Fix the defect.",
            }
        ],
        "feedback": [] if verdict == "PASS" else ["Fix the defect."],
        "evidence": [{"kind": "test", "reference": f"attempt:{attempt}"}],
    }


@dataclass
class _Context:
    state: WorkflowState = field(
        default_factory=lambda: WorkflowState(
            WorkflowFrame(id="root", meta={"name": "test"}, args=None, cwd="/tmp")
        )
    )
    events: list[dict[str, Any]] = field(default_factory=list)
    notifications: int = 0

    def journal(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def notify(self) -> None:
        self.notifications += 1


class _API:
    def __init__(self, results: list[dict[str, Any]]):
        self.context = _Context()
        self.results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def agent(self, prompt: str, opts: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((prompt, opts))
        if not self.results:
            raise AssertionError("unexpected agent call")
        return self.results.pop(0)


class ReviewedTaskExecutionActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_pass_path_launches_one_worker_and_one_reviewer(self):
        api = _API([_worker(attempt=1), _review(attempt=1)])
        api.context.state.reviewed.register_plan(_plan(_task()))

        result = await ReviewedTaskExecutionAction().run(api, task_id="A")

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["repairs_used"], 0)
        self.assertEqual([call[1]["agentType"] for call in api.calls], ["worker", "reviewer"])
        self.assertEqual(api.calls[0][1]["isolation"], "worktree")
        self.assertNotIn("isolation", api.calls[1][1])
        task = api.context.state.reviewed.snapshot()["tasks"][0]
        self.assertEqual(task["status"], "PASS")
        self.assertEqual(len(task["worker_attempts"]), 1)
        self.assertEqual(task["review_verdicts"][0]["verdict"], "PASS")

    async def test_fail_spawns_fresh_bounded_repair_then_passes(self):
        api = _API(
            [
                _worker(attempt=1, status="FAILED"),
                _review(attempt=1, verdict="FAIL"),
                _worker(attempt=2),
                _review(attempt=2, verdict="PASS"),
            ]
        )
        api.context.state.reviewed.register_plan(_plan(_task(), repairs=2))

        result = await ReviewedTaskExecutionAction().run(api, task_id="A")

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["repairs_used"], 1)
        self.assertEqual(
            [call[1]["agentType"] for call in api.calls],
            ["worker", "reviewer", "repair-worker", "reviewer"],
        )
        repair_prompt = api.calls[2][0]
        self.assertIn('"repair_attempt": 1', repair_prompt)
        self.assertIn('"verdict": "FAIL"', repair_prompt)
        task = api.context.state.reviewed.snapshot()["tasks"][0]
        self.assertEqual(task["status"], "PASS")
        self.assertEqual([item["attempt"] for item in task["worker_attempts"]], [1, 2])
        self.assertEqual([item["verdict"] for item in task["review_verdicts"]], ["FAIL", "PASS"])
        self.assertEqual(len(task["repair_attempts"]), 1)

    async def test_repair_limit_exhaustion_marks_task_failed(self):
        api = _API(
            [
                _worker(attempt=1, status="FAILED"),
                _review(attempt=1, verdict="FAIL"),
                _worker(attempt=2, status="FAILED"),
                _review(attempt=2, verdict="FAIL"),
            ]
        )
        api.context.state.reviewed.register_plan(_plan(_task(), repairs=1))

        result = await ReviewedTaskExecutionAction().run(api, task_id="A")

        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["repairs_used"], 1)
        task = api.context.state.reviewed.snapshot()["tasks"][0]
        self.assertEqual(task["status"], "FAILED")
        self.assertTrue(any(event["type"] == "reviewed_task_failed" for event in api.context.events))

    async def test_blocked_verdict_is_terminal_without_repair(self):
        api = _API([_worker(attempt=1, status="BLOCKED"), _review(attempt=1, verdict="BLOCKED")])
        api.context.state.reviewed.register_plan(_plan(_task(), repairs=3))

        result = await ReviewedTaskExecutionAction().run(api, task_id="A")

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["repairs_used"], 0)
        self.assertEqual(len(api.calls), 2)
        self.assertEqual(api.context.state.reviewed.snapshot()["tasks"][0]["status"], "BLOCKED")

    async def test_dependency_and_lineage_fail_closed(self):
        api = _API([])
        api.context.state.reviewed.register_plan(_plan(_task("A"), _task("B", ["A"])))

        with self.assertRaisesRegex(ReviewedStateError, "not dependency-ready"):
            await ReviewedTaskExecutionAction().run(api, task_id="B")
        self.assertEqual(api.calls, [])

        wrong = _API([_worker(attempt=1, task_id="wrong")])
        wrong.context.state.reviewed.register_plan(_plan(_task()))
        with self.assertRaisesRegex(ReviewedStateError, "lineage"):
            await ReviewedTaskExecutionAction().run(wrong, task_id="A")
        self.assertEqual(wrong.context.state.reviewed.snapshot()["tasks"][0]["status"], "EXECUTING")

    async def test_run_ready_uses_canonical_plan_order(self):
        api = _API(
            [
                _worker(attempt=1, task_id="A"),
                _review(attempt=1, task_id="A"),
                _worker(attempt=1, task_id="B"),
                _review(attempt=1, task_id="B"),
            ]
        )
        api.context.state.reviewed.register_plan(_plan(_task("A"), _task("B")))

        results = await ReviewedTaskExecutionAction().run_ready(api)

        self.assertEqual([item["task_id"] for item in results], ["A", "B"])
        self.assertEqual(
            [call[1]["label"] for call in api.calls],
            [
                "worker:A:attempt-1",
                "reviewer:A:attempt-1",
                "worker:B:attempt-1",
                "reviewer:B:attempt-1",
            ],
        )


if __name__ == "__main__":
    unittest.main()
