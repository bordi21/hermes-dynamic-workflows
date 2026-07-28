"""PASS-only reviewed-workspace integration action."""

from __future__ import annotations

from typing import Any

from ..child.worktree import WorkspaceIntegrationOutcome, WorkspaceLease
from ..core.errors import ReviewedStateError
from ..core.reviewed_state import ReviewedWorkflowState


def reviewed_workspace_context(lease: WorkspaceLease) -> dict[str, Any]:
    """Return the stable workspace packet a reviewer can inspect."""

    return lease.review_context().snapshot()


def integrate_reviewed_workspace(
    reviewed: ReviewedWorkflowState,
    task_id: str,
    lease: WorkspaceLease,
) -> dict[str, Any]:
    """Integrate one workspace only after the canonical state records PASS.

    FAIL, BLOCKED, unfinished, and already-integrated tasks return SKIPPED and do
    not invoke git integration. A conflict is returned explicitly and leaves the
    task at PASS so a later action can resolve or retry it without pretending the
    task was integrated.
    """

    task = _task_snapshot(reviewed, task_id)
    plan_id = str(task.get("plan_id") or "")
    status = str(task.get("status") or "")
    if status != "PASS":
        return {
            "schema_version": "1.0",
            "plan_id": plan_id,
            "task_id": str(task.get("task_id") or task_id),
            "status": "SKIPPED",
            "summary": f"Task is {status or 'UNKNOWN'}; only PASS tasks can be integrated.",
            "integrated_commit": None,
            "evidence": [
                {
                    "kind": "state",
                    "reference": f"task:{task_id}:status:{status or 'UNKNOWN'}",
                    "summary": "Integration was not attempted.",
                }
            ],
        }

    outcome = lease.integrate(commit_message=f"Hermes workflow task {task_id}")
    package = _integration_package(plan_id, task_id, lease, outcome)
    if package["status"] == "INTEGRATED":
        reviewed.integrate_task(task_id, package)
    return package


def _task_snapshot(reviewed: ReviewedWorkflowState, task_id: str) -> dict[str, Any]:
    clean = str(task_id or "").strip()
    snapshot = reviewed.snapshot()
    for task in snapshot.get("tasks") or []:
        if isinstance(task, dict) and str(task.get("task_id") or "") == clean:
            return task
    raise ReviewedStateError(f"reviewed workflow task not found: {clean or task_id!r}")


def _integration_package(
    plan_id: str,
    task_id: str,
    lease: WorkspaceLease,
    outcome: WorkspaceIntegrationOutcome,
) -> dict[str, Any]:
    status = outcome.status if outcome.status in {"INTEGRATED", "CONFLICT", "SKIPPED", "FAILED"} else "FAILED"
    evidence = [
        {
            "kind": "state",
            "reference": f"task:{task_id}:review:PASS",
            "summary": "Canonical reviewed state authorized integration.",
        },
        {
            "kind": "state",
            "reference": f"workspace:{lease.cwd}",
            "summary": f"mode={lease.isolation or 'shared'} branch={outcome.source_branch or 'none'}",
        },
        {
            "kind": "diff",
            "reference": (
                f"base:{outcome.source_base_commit or 'unknown'}"
                f"..source:{outcome.source_commit or 'unknown'}"
            ),
            "summary": ", ".join(outcome.changed_paths) or "No changed paths.",
        },
        {
            "kind": "state",
            "reference": (
                f"base-head:{outcome.base_head_before or 'unknown'}"
                f"->{outcome.base_head_after or 'unknown'}"
            ),
            "summary": (
                f"before_status={len(outcome.base_status_before)} "
                f"after_status={len(outcome.base_status_after)}"
            ),
        },
    ]
    if outcome.error:
        evidence.append(
            {
                "kind": "command",
                "reference": "git:integration-error",
                "summary": outcome.error,
            }
        )
    return {
        "schema_version": "1.0",
        "plan_id": plan_id,
        "task_id": task_id,
        "status": status,
        "summary": outcome.summary,
        "integrated_commit": outcome.integrated_commit,
        "evidence": evidence,
    }
