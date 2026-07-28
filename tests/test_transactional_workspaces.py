from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from hermes_dynamic_workflows.child.worktree import create_workspace_lease
from hermes_dynamic_workflows.contracts.packages import INTEGRATION_RESULT_PACKAGE_SCHEMA
from hermes_dynamic_workflows.core.reviewed_state import ReviewedWorkflowState
from hermes_dynamic_workflows.core.schema import validate_schema
from hermes_dynamic_workflows.engine.integration import (
    integrate_reviewed_workspace,
    reviewed_workspace_context,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "app.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-qm", "initial")
    return repo


def _task() -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": "A",
        "objective": "Update app.txt",
        "depends_on": [],
        "paths": ["app.txt"],
        "constraints": ["stay scoped"],
        "allowed_mutations": ["app.txt"],
        "acceptance_criteria": ["app.txt is correct"],
        "evidence_requirements": ["diff and test"],
        "worker_instructions": "Update app.txt.",
        "reviewer_guidelines": ["Inspect the diff and tests."],
    }


def _reviewed(verdict: str = "PASS") -> ReviewedWorkflowState:
    state = ReviewedWorkflowState()
    state.register_plan(
        {
            "schema_version": "1.0",
            "plan_id": "plan-1",
            "cycle": 0,
            "original_objective": "Update the repository safely.",
            "tasks": [_task()],
            "final_validation_criteria": ["Task A is integrated."],
            "max_repairs_per_task": 1,
            "max_replanning_cycles": 0,
        }
    )
    state.start_task("A")
    worker_status = {
        "PASS": "COMPLETED",
        "FAIL": "FAILED",
        "BLOCKED": "BLOCKED",
    }[verdict]
    state.submit_worker_result(
        "A",
        {
            "schema_version": "1.0",
            "plan_id": "plan-1",
            "task_id": "A",
            "attempt": 1,
            "status": worker_status,
            "summary": "Worker finished.",
            "changed_paths": ["app.txt"],
            "evidence": [{"kind": "diff", "reference": "app.txt"}],
            "tests": [{"name": "unit", "status": "PASS"}],
            "blocker": "external dependency" if verdict == "BLOCKED" else None,
        },
    )
    state.submit_review_verdict(
        "A",
        {
            "schema_version": "1.0",
            "plan_id": "plan-1",
            "task_id": "A",
            "attempt": 1,
            "verdict": verdict,
            "summary": f"Reviewer returned {verdict}.",
            "criteria_results": [
                {
                    "criterion": "app.txt is correct",
                    "passed": verdict == "PASS",
                    "evidence": [{"kind": "diff", "reference": "app.txt"}],
                    "feedback": "" if verdict == "PASS" else "Not accepted.",
                }
            ],
            "feedback": [] if verdict == "PASS" else ["Not accepted."],
            "evidence": [{"kind": "diff", "reference": "app.txt"}],
        },
    )
    return state


class TransactionalWorkspaceTests(unittest.TestCase):
    def test_read_only_shared_workspace_integrates_logically_without_git_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp))
            head_before = _git(repo, "rev-parse", "HEAD")
            lease = create_workspace_lease(
                cwd=str(repo), isolation="shared", label="read-only", task_id="A"
            )
            state = _reviewed("PASS")

            context = reviewed_workspace_context(lease)
            first = integrate_reviewed_workspace(state, "A", lease)
            second = integrate_reviewed_workspace(state, "A", lease)

            validate_schema(first, INTEGRATION_RESULT_PACKAGE_SCHEMA)
            validate_schema(second, INTEGRATION_RESULT_PACKAGE_SCHEMA)
            self.assertEqual(context["mode"], "shared")
            self.assertEqual(first["status"], "INTEGRATED")
            self.assertEqual(second["status"], "SKIPPED")
            self.assertEqual(_git(repo, "rev-parse", "HEAD"), head_before)
            self.assertEqual(state.snapshot()["tasks"][0]["status"], "INTEGRATED")

    def test_passed_mutating_worktree_is_reviewable_and_integrated_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp))
            lease = create_workspace_lease(
                cwd=str(repo), isolation="worktree", label="task-a", task_id="A"
            )
            worktree = Path(lease.cwd)
            (worktree / "app.txt").write_text("worker\n", encoding="utf-8")
            state = _reviewed("PASS")

            context = reviewed_workspace_context(lease)
            result = integrate_reviewed_workspace(state, "A", lease)
            head_after = _git(repo, "rev-parse", "HEAD")
            repeated = integrate_reviewed_workspace(state, "A", lease)

            validate_schema(result, INTEGRATION_RESULT_PACKAGE_SCHEMA)
            self.assertEqual(context["mode"], "worktree")
            self.assertEqual(context["base_commit"], lease.base_commit)
            self.assertIn("app.txt", context["changed_paths"])
            self.assertTrue(context["status"])
            self.assertEqual(result["status"], "INTEGRATED")
            self.assertEqual(result["integrated_commit"], head_after)
            self.assertEqual((repo / "app.txt").read_text(encoding="utf-8"), "worker\n")
            self.assertEqual(state.snapshot()["tasks"][0]["status"], "INTEGRATED")
            self.assertEqual(repeated["status"], "SKIPPED")
            self.assertEqual(_git(repo, "rev-parse", "HEAD"), head_after)
            self.assertIsNotNone(lease.source_commit)
            self.assertIsNotNone(lease.integrated_commit)

            worktree_path = Path(lease.path or "")
            branch = str(lease.branch or "")
            lease.cleanup()
            self.assertFalse(worktree_path.exists())
            self.assertEqual(_git(repo, "branch", "--list", branch), "")

    def test_fail_and_blocked_integrate_nothing(self):
        for verdict in ("FAIL", "BLOCKED"):
            with self.subTest(verdict=verdict):
                with tempfile.TemporaryDirectory() as tmp:
                    repo = _init_repo(Path(tmp))
                    head_before = _git(repo, "rev-parse", "HEAD")
                    lease = create_workspace_lease(
                        cwd=str(repo), isolation="worktree", label=verdict, task_id="A"
                    )
                    (Path(lease.cwd) / "app.txt").write_text("worker\n", encoding="utf-8")
                    state = _reviewed(verdict)

                    result = integrate_reviewed_workspace(state, "A", lease)

                    validate_schema(result, INTEGRATION_RESULT_PACKAGE_SCHEMA)
                    self.assertEqual(result["status"], "SKIPPED")
                    self.assertEqual(_git(repo, "rev-parse", "HEAD"), head_before)
                    self.assertEqual((repo / "app.txt").read_text(encoding="utf-8"), "base\n")
                    self.assertEqual(state.snapshot()["tasks"][0]["status"], verdict)
                    self.assertIsNone(lease.integrated_commit)

    def test_conflict_is_explicit_and_base_is_restored(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp))
            lease = create_workspace_lease(
                cwd=str(repo), isolation="worktree", label="conflict", task_id="A"
            )
            (Path(lease.cwd) / "app.txt").write_text("worker\n", encoding="utf-8")
            (repo / "app.txt").write_text("main\n", encoding="utf-8")
            _git(repo, "add", "app.txt")
            _git(repo, "commit", "-qm", "main change")
            head_before = _git(repo, "rev-parse", "HEAD")
            state = _reviewed("PASS")

            result = integrate_reviewed_workspace(state, "A", lease)

            validate_schema(result, INTEGRATION_RESULT_PACKAGE_SCHEMA)
            self.assertEqual(result["status"], "CONFLICT")
            self.assertEqual(result["integrated_commit"], None)
            self.assertEqual(_git(repo, "rev-parse", "HEAD"), head_before)
            self.assertEqual(_git(repo, "status", "--porcelain"), "")
            self.assertEqual((repo / "app.txt").read_text(encoding="utf-8"), "main\n")
            self.assertEqual(state.snapshot()["tasks"][0]["status"], "PASS")
            self.assertIsNone(lease.integrated_commit)

    def test_dirty_base_fails_without_resetting_unrelated_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp))
            lease = create_workspace_lease(
                cwd=str(repo), isolation="worktree", label="dirty-base", task_id="A"
            )
            (Path(lease.cwd) / "app.txt").write_text("worker\n", encoding="utf-8")
            unrelated = repo / "notes.txt"
            unrelated.write_text("keep me\n", encoding="utf-8")
            head_before = _git(repo, "rev-parse", "HEAD")
            state = _reviewed("PASS")

            result = integrate_reviewed_workspace(state, "A", lease)

            validate_schema(result, INTEGRATION_RESULT_PACKAGE_SCHEMA)
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(_git(repo, "rev-parse", "HEAD"), head_before)
            self.assertTrue(unrelated.exists())
            self.assertIn("notes.txt", _git(repo, "status", "--porcelain"))
            self.assertEqual((repo / "app.txt").read_text(encoding="utf-8"), "base\n")
            self.assertEqual(state.snapshot()["tasks"][0]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
