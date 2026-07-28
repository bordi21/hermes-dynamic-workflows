from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from hermes_dynamic_workflows.actions.execution import ReviewedTaskExecutionAction
from hermes_dynamic_workflows.child.worktree import (
    WorkspaceIntegrationOutcome,
    WorkspaceReviewContext,
)
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
class _Lease:
    task_id: str = "reviewed-plan-1-A"
    cwd: str = "/tmp/A-workspace"
    isolation: str = "worktree"
    path: str = "/tmp/A-workspace"
    branch: str = "hermes/reviewed-A"
    repo_root: str = "/repo"
    base_commit: str = "base-commit"
    integration_status: str = "INTEGRATED"
    integrated_commit: str | None = None
    cleanup_calls: int = 0
    integrate_calls: int = 0

    def review_context(self) -> WorkspaceReviewContext:
        return WorkspaceReviewContext(
            mode="worktree",
            workspace=self.cwd,
            repo_root=self.repo_root,
            branch=self.branch,
            base_commit=self.base_commit,
            head_commit="source-commit",
            status=(" M src/example.py",),
            changed_paths=("src/example.py",),
            diff_stat="1 file changed",
            commits=(),
        )

    def integrate(self, *, commit_message: str) -> WorkspaceIntegrationOutcome:
        self.integrate_calls += 1
        integrated = "integrated-commit" if self.integration_status == "INTEGRATED" else None
        self.integrated_commit = integrated
        return WorkspaceIntegrationOutcome(
            status=self.integration_status,
            summary=f"integration {self.integration_status.lower()}",
            source_branch=self.branch,
            source_base_commit=self.base_commit,
            source_commit="source-commit",
            integrated_commit=integrated,
            base_head_before="base-commit",
            base_head_after=integrated or "base-commit",
            source_status=(),
            changed_paths=("src/example.py",),
            commits=("source-commit",),
            error="conflict" if self.integration_status == "CONFLICT" else "",
        )

    def cleanup(self) -> None:
        self.cleanup_calls += 1


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


class _ScopedAPI:
    def __init__(self, parent: "_API", cwd: str):
        self.parent = parent
        self.context = parent.context
        self.cwd = cwd

    async def agent(self, prompt: str, opts: dict[str, Any]) -> dict[str, Any]:
        self.parent.calls.append({"cwd": self.cwd, "prompt": prompt, "opts": opts})
        if not self.parent.results:
            raise AssertionError("unexpected agent call")
        return self.parent.results.pop(0)


class _API:
    def __init__(self, results: list[dict[str, Any]]):
        self.context = _Context()
        self.frame = self.context.state.root
        self.config = SimpleNamespace(keep_worktrees=False)
        self.depth = 0
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    def for_workspace(self, cwd: str) -> _ScopedAPI:
        return _ScopedAPI(self, cwd)


class _BrokenScopedAPI(_API):
    def for_workspace(self, cwd: str) -> _ScopedAPI:
        raise ReviewedStateError("scope failed")


class ReviewedTaskExecutionActionTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self,
        api: _API,
        *,
        task_id: str = "A",
        lease: _Lease | None = None,
    ) -> tuple[dict[str, Any], _Lease]:
        selected = lease or _Lease(task_id=f"reviewed-plan-1-{task_id}", cwd=f"/tmp/{task_id}-workspace")
        with patch(
            "hermes_dynamic_workflows.actions.execution.create_workspace_lease",
            return_value=selected,
        ):
            result = await ReviewedTaskExecutionAction().run(api, task_id=task_id)
        return result, selected

    async def test_pass_reviews_same_workspace_and_integrates(self):
        api = _API([_worker(attempt=1), _review(attempt=1)])
        api.context.state.reviewed.register_plan(_plan(_task()))
        lease = _Lease()

        with patch(
            "hermes_dynamic_workflows.actions.execution.create_workspace_lease",
            return_value=lease,
        ) as factory:
            result = await ReviewedTaskExecutionAction().run(api, task_id="A")

        self.assertEqual(result["status"], "INTEGRATED")
        self.assertEqual(result["integration"]["status"], "INTEGRATED")
        self.assertEqual(result["repairs_used"], 0)
        self.assertEqual([call["opts"]["agentType"] for call in api.calls], ["worker", "reviewer"])
        self.assertTrue(all(call["cwd"] == lease.cwd for call in api.calls))
        self.assertTrue(all("isolation" not in call["opts"] for call in api.calls))
        self.assertIn('"workspace": "/tmp/A-workspace"', api.calls[1]["prompt"])
        factory.assert_called_once_with(
            cwd="/repo",
            isolation="worktree",
            label="reviewed-A",
            task_id="reviewed-plan-1-A",
            keep_worktree=False,
        )
        task = api.context.state.reviewed.snapshot()["tasks"][0]
        self.assertEqual(task["status"], "INTEGRATED")
        self.assertEqual(lease.integrate_calls, 1)
        self.assertEqual(lease.cleanup_calls, 1)

    async def test_fail_spawns_fresh_repair_in_same_workspace_then_integrates(self):
        api = _API(
            [
                _worker(attempt=1, status="FAILED"),
                _review(attempt=1, verdict="FAIL"),
                _worker(attempt=2),
                _review(attempt=2, verdict="PASS"),
            ]
        )
        api.context.state.reviewed.register_plan(_plan(_task(), repairs=2))

        result, lease = await self._run(api)

        self.assertEqual(result["status"], "INTEGRATED")
        self.assertEqual(result["repairs_used"], 1)
        self.assertEqual(
            [call["opts"]["agentType"] for call in api.calls],
            ["worker", "reviewer", "repair-worker", "reviewer"],
        )
        self.assertTrue(all(call["cwd"] == lease.cwd for call in api.calls))
        repair_prompt = api.calls[2]["prompt"]
        self.assertIn('"repair_attempt": 1', repair_prompt)
        self.assertIn('"verdict": "FAIL"', repair_prompt)
        task = api.context.state.reviewed.snapshot()["tasks"][0]
        self.assertEqual(task["status"], "INTEGRATED")
        self.assertEqual([item["attempt"] for item in task["worker_attempts"]], [1, 2])
        self.assertEqual([item["verdict"] for item in task["review_verdicts"]], ["FAIL", "PASS"])
        self.assertEqual(len(task["repair_attempts"]), 1)

    async def test_repair_limit_exhaustion_marks_task_failed_without_integration(self):
        api = _API(
            [
                _worker(attempt=1, status="FAILED"),
                _review(attempt=1, verdict="FAIL"),
                _worker(attempt=2, status="FAILED"),
                _review(attempt=2, verdict="FAIL"),
            ]
        )
        api.context.state.reviewed.register_plan(_plan(_task(), repairs=1))

        result, lease = await self._run(api)

        self.assertEqual(result["status"], "FAILED")
        self.assertIsNone(result["integration"])
        self.assertEqual(result["repairs_used"], 1)
        self.assertEqual(lease.integrate_calls, 0)
        self.assertEqual(lease.cleanup_calls, 1)
        task = api.context.state.reviewed.snapshot()["tasks"][0]
        self.assertEqual(task["status"], "FAILED")
        self.assertTrue(any(event["type"] == "reviewed_task_failed" for event in api.context.events))

    async def test_blocked_verdict_is_terminal_without_repair_or_integration(self):
        api = _API([_worker(attempt=1, status="BLOCKED"), _review(attempt=1, verdict="BLOCKED")])
        api.context.state.reviewed.register_plan(_plan(_task(), repairs=3))

        result, lease = await self._run(api)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["repairs_used"], 0)
        self.assertEqual(len(api.calls), 2)
        self.assertEqual(lease.integrate_calls, 0)
        self.assertEqual(api.context.state.reviewed.snapshot()["tasks"][0]["status"], "BLOCKED")

    async def test_integration_conflict_is_explicit_and_does_not_claim_success(self):
        api = _API([_worker(attempt=1), _review(attempt=1)])
        api.context.state.reviewed.register_plan(_plan(_task()))
        lease = _Lease(integration_status="CONFLICT")

        result, _ = await self._run(api, lease=lease)

        self.assertEqual(result["status"], "CONFLICT")
        self.assertEqual(result["integration"]["status"], "CONFLICT")
        self.assertEqual(api.context.state.reviewed.snapshot()["tasks"][0]["status"], "PASS")
        event = next(item for item in api.context.events if item["type"] == "reviewed_task_integration")
        self.assertEqual(event["status"], "CONFLICT")
        self.assertEqual(event["summary"], "integration conflict")
        self.assertTrue(
            any(
                item["reference"] == "git:integration-error" and item["summary"] == "conflict"
                for item in event["evidence"]
            )
        )

    async def test_dependency_and_lineage_fail_closed(self):
        api = _API([])
        api.context.state.reviewed.register_plan(_plan(_task("A"), _task("B", ["A"])))

        with self.assertRaisesRegex(ReviewedStateError, "not dependency-ready"):
            await ReviewedTaskExecutionAction().run(api, task_id="B")
        self.assertEqual(api.calls, [])

        wrong = _API([_worker(attempt=1, task_id="wrong")])
        wrong.context.state.reviewed.register_plan(_plan(_task()))
        lease = _Lease()
        with patch(
            "hermes_dynamic_workflows.actions.execution.create_workspace_lease",
            return_value=lease,
        ):
            with self.assertRaisesRegex(ReviewedStateError, "lineage"):
                await ReviewedTaskExecutionAction().run(wrong, task_id="A")
        self.assertEqual(wrong.context.state.reviewed.snapshot()["tasks"][0]["status"], "EXECUTING")
        self.assertEqual(lease.cleanup_calls, 1)

    async def test_workspace_scope_failure_cleans_lease_before_state_start(self):
        api = _BrokenScopedAPI([])
        api.context.state.reviewed.register_plan(_plan(_task()))
        lease = _Lease()

        with patch(
            "hermes_dynamic_workflows.actions.execution.create_workspace_lease",
            return_value=lease,
        ):
            with self.assertRaisesRegex(ReviewedStateError, "scope failed"):
                await ReviewedTaskExecutionAction().run(api, task_id="A")

        self.assertEqual(lease.cleanup_calls, 1)
        self.assertEqual(api.context.state.reviewed.snapshot()["tasks"][0]["status"], "PLANNED")

    async def test_run_ready_rechecks_dependencies_after_each_integration(self):
        api = _API(
            [
                _worker(attempt=1, task_id="A"),
                _review(attempt=1, task_id="A"),
                _worker(attempt=1, task_id="B"),
                _review(attempt=1, task_id="B"),
            ]
        )
        api.context.state.reviewed.register_plan(_plan(_task("A"), _task("B", ["A"])))
        leases = [
            _Lease(task_id="reviewed-plan-1-A", cwd="/tmp/A-workspace"),
            _Lease(task_id="reviewed-plan-1-B", cwd="/tmp/B-workspace"),
        ]

        with patch(
            "hermes_dynamic_workflows.actions.execution.create_workspace_lease",
            side_effect=leases,
        ):
            results = await ReviewedTaskExecutionAction().run_ready(api)

        self.assertEqual([item["task_id"] for item in results], ["A", "B"])
        self.assertEqual([item["status"] for item in results], ["INTEGRATED", "INTEGRATED"])
        self.assertEqual(
            [call["opts"]["label"] for call in api.calls],
            [
                "worker:A:attempt-1",
                "reviewer:A:attempt-1",
                "worker:B:attempt-1",
                "reviewer:B:attempt-1",
            ],
        )
        self.assertEqual(
            [call["cwd"] for call in api.calls],
            [
                "/tmp/A-workspace",
                "/tmp/A-workspace",
                "/tmp/B-workspace",
                "/tmp/B-workspace",
            ],
        )


if __name__ == "__main__":
    unittest.main()
