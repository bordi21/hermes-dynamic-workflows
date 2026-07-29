"""Worker, reviewer, repair, and PASS-only integration lifecycle."""

from __future__ import annotations

import asyncio
import json
from copy import copy, deepcopy
from typing import Any

from ..child.worktree import WorkspaceLease, create_workspace_lease
from ..contracts.packages import (
    REPAIR_PACKAGE_SCHEMA,
    REVIEW_VERDICT_PACKAGE_SCHEMA,
    WORKER_RESULT_PACKAGE_SCHEMA,
)
from ..core.errors import ReviewedStateError
from ..core.schema import validate_schema
from ..engine.integration import integrate_reviewed_workspace, reviewed_workspace_context


class ReviewedTaskExecutionAction:
    """Execute one ready task through review, bounded repair, and integration.

    The action owns the concrete task worktree for the entire lifecycle. Every
    child still runs through ``WorkflowAPI.agent`` so routing, approvals,
    structured output, accounting, transcripts, and runtime limits remain
    canonical. Workers, reviewers, and fresh repair sessions all operate on the
    same isolated workspace; only an evidence-backed PASS is integrated.
    """

    async def run(self, api: Any, *, task_id: str) -> dict[str, Any]:
        task_state, plan = _task_and_plan(api, task_id)
        if task_state["status"] != "PLANNED":
            raise ReviewedStateError(
                f"task {task_id} must be PLANNED before execution, got {task_state['status']}"
            )
        if task_id not in api.context.state.reviewed.ready_task_ids():
            raise ReviewedStateError(f"task {task_id} is not dependency-ready")

        task = deepcopy(task_state["task"])
        lease = _create_task_workspace(api, task)
        try:
            workspace_api = _workspace_api(api, lease.cwd)
            max_repairs = int(plan["max_repairs_per_task"])
            repair_attempt = 0
            integration_result: dict[str, Any] | None = None

            api.context.state.reviewed.start_task(task_id)
            _journal(
                api,
                "reviewed_task_started",
                task,
                attempt=1,
                workspace=reviewed_workspace_context(lease),
            )

            result = await self._worker(workspace_api, task=task, attempt=1)
            api.context.state.reviewed.submit_worker_result(task_id, result)
            _journal(
                api,
                "reviewed_worker_result",
                task,
                attempt=1,
                status=result["status"],
                workspace=reviewed_workspace_context(lease),
            )

            verdict = await self._review(
                workspace_api,
                plan=plan,
                task=task,
                result=result,
                lease=lease,
            )
            api.context.state.reviewed.submit_review_verdict(task_id, verdict)
            _journal(
                api,
                "reviewed_task_verdict",
                task,
                attempt=1,
                verdict=verdict["verdict"],
            )

            while verdict["verdict"] == "FAIL" and repair_attempt < max_repairs:
                repair_attempt += 1
                worker_attempt = repair_attempt + 1
                repair = {
                    "schema_version": "1.0",
                    "plan_id": task["plan_id"],
                    "task_id": task["task_id"],
                    "repair_attempt": repair_attempt,
                    "original_task": deepcopy(task),
                    "previous_result": deepcopy(result),
                    "review_verdict": deepcopy(verdict),
                }
                validate_schema(repair, REPAIR_PACKAGE_SCHEMA)
                api.context.state.reviewed.start_repair(task_id, repair)
                _journal(
                    api,
                    "reviewed_repair_started",
                    task,
                    attempt=worker_attempt,
                    repairAttempt=repair_attempt,
                    workspace=reviewed_workspace_context(lease),
                )

                result = await self._repair_worker(
                    workspace_api,
                    repair=repair,
                    attempt=worker_attempt,
                )
                api.context.state.reviewed.submit_repair_result(task_id, result)
                _journal(
                    api,
                    "reviewed_repair_result",
                    task,
                    attempt=worker_attempt,
                    repairAttempt=repair_attempt,
                    status=result["status"],
                    workspace=reviewed_workspace_context(lease),
                )

                verdict = await self._review(
                    workspace_api,
                    plan=plan,
                    task=task,
                    result=result,
                    lease=lease,
                )
                api.context.state.reviewed.submit_review_verdict(task_id, verdict)
                _journal(
                    api,
                    "reviewed_task_verdict",
                    task,
                    attempt=worker_attempt,
                    repairAttempt=repair_attempt,
                    verdict=verdict["verdict"],
                )

            exhausted = verdict["verdict"] == "FAIL"
            if exhausted:
                api.context.state.reviewed.mark_task_failed(task_id)
                _journal(
                    api,
                    "reviewed_task_failed",
                    task,
                    attempt=int(result["attempt"]),
                    reason="repair limit exhausted",
                )
                status = "FAILED"
            elif verdict["verdict"] == "PASS":
                integration_result = integrate_reviewed_workspace(
                    api.context.state.reviewed,
                    task_id=task_id,
                    lease=lease,
                )
                status = str(integration_result["status"])
                if status in {"CONFLICT", "FAILED"}:
                    api.context.state.reviewed.record_integration_failure(
                        task_id,
                        integration_result,
                    )
                _journal(
                    api,
                    "reviewed_task_integration",
                    task,
                    attempt=int(result["attempt"]),
                    status=status,
                    summary=integration_result["summary"],
                    integratedCommit=integration_result.get("integrated_commit"),
                    evidence=deepcopy(integration_result["evidence"]),
                )
            else:
                status = verdict["verdict"]

            workspace = reviewed_workspace_context(lease)
            api.context.notify()
            return {
                "task_id": task_id,
                "status": status,
                "worker_result": deepcopy(result),
                "review_verdict": deepcopy(verdict),
                "repairs_used": repair_attempt,
                "repairs_allowed": max_repairs,
                "workspace": workspace,
                "integration": deepcopy(integration_result),
            }
        finally:
            lease.cleanup()

    async def run_ready(self, api: Any) -> list[dict[str, Any]]:
        """Run each dependency-ready wave concurrently in canonical order.

        Independent tasks receive separate retained worktrees and execute in one
        wave, bounded by the existing workflow semaphore. Git integration remains
        serialized per repository by the canonical integration service. Readiness
        is recalculated only after the whole wave settles, so dependants start in
        the next wave against accepted integrated predecessors.
        """

        results: list[dict[str, Any]] = []
        while True:
            ready = list(api.context.state.reviewed.ready_task_ids())
            if not ready:
                return results
            wave = await asyncio.gather(
                *(self.run(api, task_id=task_id) for task_id in ready)
            )
            results.extend(wave)

    async def _worker(self, api: Any, *, task: dict[str, Any], attempt: int) -> dict[str, Any]:
        prompt = (
            "Execute exactly this reviewed-workflow TaskPackage inside the current isolated task "
            "workspace. Return only the required WorkerResultPackage through structured output. "
            "Do not self-review or broaden scope.\n\n"
            f"Attempt: {attempt}\nTaskPackage:\n{_json(task)}"
        )
        result = await api.agent(
            prompt,
            {
                "label": f"worker:{task['task_id']}:attempt-{attempt}",
                "phase": "Execution",
                "schema": WORKER_RESULT_PACKAGE_SCHEMA,
                "agentType": "worker",
            },
        )
        _validate_worker_result(result, task=task, attempt=attempt)
        return deepcopy(result)

    async def _repair_worker(
        self,
        api: Any,
        *,
        repair: dict[str, Any],
        attempt: int,
    ) -> dict[str, Any]:
        prompt = (
            "Start a fresh repair-agent session in the retained task workspace. Perform a "
            "materially different repair using this RepairPackage, preserve the original criteria, "
            "and return only a WorkerResultPackage through structured output.\n\n"
            f"Worker attempt: {attempt}\nRepairPackage:\n{_json(repair)}"
        )
        result = await api.agent(
            prompt,
            {
                "label": f"repair-worker:{repair['task_id']}:attempt-{attempt}",
                "phase": "Repair",
                "schema": WORKER_RESULT_PACKAGE_SCHEMA,
                "agentType": "repair-worker",
            },
        )
        _validate_worker_result(result, task=repair["original_task"], attempt=attempt)
        return deepcopy(result)

    async def _review(
        self,
        api: Any,
        *,
        plan: dict[str, Any],
        task: dict[str, Any],
        result: dict[str, Any],
        lease: WorkspaceLease,
    ) -> dict[str, Any]:
        request = {
            "schema_version": "1.0",
            "plan_id": task["plan_id"],
            "task_id": task["task_id"],
            "original_objective": plan["original_objective"],
            "task": deepcopy(task),
            "worker_result": deepcopy(result),
        }
        workspace = reviewed_workspace_context(lease)
        prompt = (
            "Review this attempt fail-closed against every acceptance criterion and the planner's "
            "reviewer guidelines. Inspect the current task workspace and its concrete diff evidence, "
            "not only the worker's claims. Return PASS, FAIL, or BLOCKED only through the required "
            "ReviewVerdictPackage. Do not repair the work.\n\n"
            f"ReviewRequestPackage:\n{_json(request)}\n\n"
            f"WorkspaceReviewContext:\n{_json(workspace)}"
        )
        verdict = await api.agent(
            prompt,
            {
                "label": f"reviewer:{task['task_id']}:attempt-{result['attempt']}",
                "phase": "Review",
                "schema": REVIEW_VERDICT_PACKAGE_SCHEMA,
                "agentType": "reviewer",
            },
        )
        validate_schema(verdict, REVIEW_VERDICT_PACKAGE_SCHEMA)
        if not isinstance(verdict, dict):
            raise ReviewedStateError("reviewer returned a non-object ReviewVerdictPackage")
        if verdict.get("plan_id") != task["plan_id"] or verdict.get("task_id") != task["task_id"]:
            raise ReviewedStateError("review verdict lineage does not match the task")
        if verdict.get("attempt") != result["attempt"]:
            raise ReviewedStateError("review verdict attempt does not match the worker result")
        return deepcopy(verdict)


def _create_task_workspace(api: Any, task: dict[str, Any]) -> WorkspaceLease:
    try:
        return create_workspace_lease(
            cwd=api.frame.cwd,
            isolation="worktree",
            label=f"reviewed-{task['task_id']}",
            task_id=f"reviewed-{task['plan_id']}-{task['task_id']}",
            keep_worktree=bool(getattr(getattr(api, "config", None), "keep_worktrees", False)),
        )
    except (OSError, ValueError) as exc:
        raise ReviewedStateError(
            f"could not create isolated workspace for task {task['task_id']}: {exc}"
        ) from exc


def _workspace_api(api: Any, cwd: str) -> Any:
    """Create a canonical API view rooted at one retained task workspace."""

    factory = getattr(api, "for_workspace", None)
    if callable(factory):
        return factory(cwd)
    if not hasattr(api, "frame") or not hasattr(api, "context"):
        raise ReviewedStateError("workflow API cannot create a scoped task workspace view")
    from ..engine.api import WorkflowAPI

    frame = copy(api.frame)
    frame.cwd = cwd
    return WorkflowAPI(
        context=api.context,
        frame=frame,
        depth=int(getattr(api, "depth", 0)),
    )


def _task_and_plan(api: Any, task_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = api.context.state.reviewed.snapshot()
    task_state = next(
        (item for item in snapshot["tasks"] if item.get("task_id") == task_id),
        None,
    )
    if task_state is None:
        raise ReviewedStateError(f"reviewed workflow task not found: {task_id!r}")
    plan = next(
        (
            item["plan"]
            for item in snapshot["planning_cycles"]
            if item.get("plan_id") == task_state.get("plan_id")
        ),
        None,
    )
    if not isinstance(plan, dict):
        raise ReviewedStateError(f"plan not found for task {task_id!r}")
    return task_state, plan


def _validate_worker_result(result: Any, *, task: dict[str, Any], attempt: int) -> None:
    validate_schema(result, WORKER_RESULT_PACKAGE_SCHEMA)
    if not isinstance(result, dict):
        raise ReviewedStateError("worker returned a non-object WorkerResultPackage")
    if result.get("plan_id") != task["plan_id"] or result.get("task_id") != task["task_id"]:
        raise ReviewedStateError("worker result lineage does not match the task")
    if result.get("attempt") != attempt:
        raise ReviewedStateError(
            f"worker result attempt mismatch: expected {attempt}, got {result.get('attempt')!r}"
        )


def _journal(api: Any, event_type: str, task: dict[str, Any], **extra: Any) -> None:
    api.context.journal(
        {
            "type": event_type,
            "planId": task["plan_id"],
            "taskId": task["task_id"],
            **extra,
        }
    )
    api.context.notify()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
