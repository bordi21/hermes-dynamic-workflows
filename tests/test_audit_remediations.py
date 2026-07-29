from __future__ import annotations

import asyncio
import unittest
from typing import Any

from hermes_dynamic_workflows.actions.execution import ReviewedTaskExecutionAction
from hermes_dynamic_workflows.core.errors import ReviewedStateError
from hermes_dynamic_workflows.core.reviewed_state import ReviewedWorkflowState


def _task(task_id: str) -> dict[str, Any]:
    return {
        "plan_id": "plan-1",
        "task_id": task_id,
        "depends_on": [],
    }


def _plan(*task_ids: str) -> dict[str, Any]:
    return {
        "plan_id": "plan-1",
        "cycle": 0,
        "original_objective": "Verify audit remediations.",
        "tasks": [_task(task_id) for task_id in task_ids],
    }


def _worker(task_id: str) -> dict[str, Any]:
    return {
        "plan_id": "plan-1",
        "task_id": task_id,
        "attempt": 1,
        "status": "COMPLETED",
    }


def _review(task_id: str) -> dict[str, Any]:
    return {
        "plan_id": "plan-1",
        "task_id": task_id,
        "attempt": 1,
        "verdict": "PASS",
    }


class IntegrationFailureStateTests(unittest.TestCase):
    def test_conflict_is_persisted_and_terminal(self):
        state = ReviewedWorkflowState()
        state.register_plan(_plan("A"))
        state.start_task("A")
        state.submit_worker_result("A", _worker("A"))
        state.submit_review_verdict("A", _review("A"))
        conflict = {
            "plan_id": "plan-1",
            "task_id": "A",
            "status": "CONFLICT",
            "summary": "Cherry-pick conflicted.",
            "evidence": [{"kind": "command", "reference": "git:integration-error"}],
        }

        state.record_integration_failure("A", conflict)

        task = state.snapshot()["tasks"][0]
        self.assertEqual(task["status"], "FAILED")
        self.assertEqual(task["integration"], conflict)

    def test_success_cannot_be_recorded_as_failure(self):
        state = ReviewedWorkflowState()
        state.register_plan(_plan("A"))
        state.start_task("A")
        state.submit_worker_result("A", _worker("A"))
        state.submit_review_verdict("A", _review("A"))

        with self.assertRaisesRegex(ReviewedStateError, "CONFLICT or FAILED"):
            state.record_integration_failure(
                "A",
                {"plan_id": "plan-1", "task_id": "A", "status": "INTEGRATED"},
            )


class _ReadyState:
    def __init__(self) -> None:
        self.calls = 0

    def ready_task_ids(self) -> list[str]:
        self.calls += 1
        return ["A", "B"] if self.calls == 1 else []


class _Context:
    def __init__(self) -> None:
        self.state = type("State", (), {"reviewed": _ReadyState()})()


class _API:
    def __init__(self) -> None:
        self.context = _Context()


class _WaveAction(ReviewedTaskExecutionAction):
    def __init__(self) -> None:
        self.started: list[str] = []
        self.release = asyncio.Event()

    async def run(self, api: Any, *, task_id: str) -> dict[str, Any]:
        self.started.append(task_id)
        if len(self.started) == 2:
            self.release.set()
        await asyncio.wait_for(self.release.wait(), timeout=1)
        return {"task_id": task_id, "status": "INTEGRATED"}


class DependencyWaveTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_tasks_start_in_one_concurrent_wave(self):
        action = _WaveAction()

        results = await action.run_ready(_API())

        self.assertEqual(action.started, ["A", "B"])
        self.assertEqual([item["task_id"] for item in results], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
