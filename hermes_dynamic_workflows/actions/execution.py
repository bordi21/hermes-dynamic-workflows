"""Worker, reviewer, and bounded repair lifecycle for reviewed tasks."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from ..contracts.packages import (
    REPAIR_PACKAGE_SCHEMA,
    REVIEW_VERDICT_PACKAGE_SCHEMA,
    WORKER_RESULT_PACKAGE_SCHEMA,
)
from ..core.errors import ReviewedStateError
from ..core.schema import validate_schema


class ReviewedTaskExecutionAction:
    """Execute one ready task through worker, review, and bounded repair.

    The action owns lifecycle policy and canonical reviewed-state transitions. Child
    execution still goes through ``WorkflowAPI.agent`` so model routing, approvals,
    structured output, accounting, transcripts, and runtime limits remain canonical.

    PASS stops at the accepted verdict. Workspace integration is deliberately left to
    the existing PASS-only integration action, which needs the concrete workspace lease.
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
        api.context.state.reviewed.start_task(task_id)
        _journal(api, "reviewed_task_started", task, attempt=1)

        result = await self._worker(api, task=task, attempt=1)
        api.context.state.reviewed.submit_worker_result(task_id, result)
        _journal(api, "reviewed_worker_result", task, attempt=1, status=result["status"])

        verdict = await self._review(api, plan=plan, task=task, result=result)
        api.context.state.reviewed.submit_review_verdict(task_id, verdict)
        _journal(api, "reviewed_task_verdict", task, attempt=1, verdict=verdict["verdict"])

        max_repairs = int(plan["max_repairs_per_task"])
        repair_attempt = 0
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
            )

            result = await self._repair_worker(
                api,
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
            )

            verdict = await self._review(api, plan=plan, task=task, result=result)
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

        api.context.notify()
        return {
            "task_id": task_id,
            "status": "FAILED" if exhausted else verdict["verdict"],
            "worker_result": deepcopy(result),
            "review_verdict": deepcopy(verdict),
            "repairs_used": repair_attempt,
            "repairs_allowed": max_repairs,
        }

    async def run_ready(self, api: Any) -> list[dict[str, Any]]:
        """Run the currently ready task set sequentially in canonical plan order."""

        results: list[dict[str, Any]] = []
        for task_id in list(api.context.state.reviewed.ready_task_ids()):
            results.append(await self.run(api, task_id=task_id))
        return results

    async def _worker(self, api: Any, *, task: dict[str, Any], attempt: int) -> dict[str, Any]:
        prompt = (
            "Execute exactly this reviewed-workflow TaskPackage. Return only the required "
            "WorkerResultPackage through structured output. Do not self-review or broaden scope.\n\n"
            f"Attempt: {attempt}\nTaskPackage:\n{_json(task)}"
        )
        result = await api.agent(
            prompt,
            {
                "label": f"worker:{task['task_id']}:attempt-{attempt}",
                "phase": "Execution",
                "schema": WORKER_RESULT_PACKAGE_SCHEMA,
                "agentType": "worker",
                "isolation": "worktree",
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
            "Perform a fresh, materially different repair using this RepairPackage. Preserve "
            "the original criteria and return only a WorkerResultPackage through structured output.\n\n"
            f"Worker attempt: {attempt}\nRepairPackage:\n{_json(repair)}"
        )
        result = await api.agent(
            prompt,
            {
                "label": f"repair-worker:{repair['task_id']}:attempt-{attempt}",
                "phase": "Repair",
                "schema": WORKER_RESULT_PACKAGE_SCHEMA,
                "agentType": "repair-worker",
                "isolation": "worktree",
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
    ) -> dict[str, Any]:
        request = {
            "schema_version": "1.0",
            "plan_id": task["plan_id"],
            "task_id": task["task_id"],
            "original_objective": plan["original_objective"],
            "task": deepcopy(task),
            "worker_result": deepcopy(result),
        }
        prompt = (
            "Review this attempt fail-closed against every acceptance criterion and the planner's "
            "reviewer guidelines. Return PASS, FAIL, or BLOCKED only through the required "
            "ReviewVerdictPackage. Do not repair the work.\n\n"
            f"ReviewRequestPackage:\n{_json(request)}"
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
