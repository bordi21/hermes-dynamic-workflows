"""Initial planning action for the canonical reviewed workflow."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from ..contracts.packages import PLAN_PACKAGE_SCHEMA
from ..core.errors import ReviewedStateError
from ..core.schema import validate_schema


@dataclass(frozen=True)
class PlanningLimits:
    """Fail-closed safety caps for one planner-produced package.

    The planner may choose stricter limits inside the package, but it cannot
    enlarge these action-owned caps. Later lifecycle actions consume the limits
    recorded in the accepted plan.
    """

    max_tasks: int = 64
    max_repairs_per_task: int = 5
    max_replanning_cycles: int = 3

    def __post_init__(self) -> None:
        if self.max_tasks < 1:
            raise ValueError("max_tasks must be at least 1")
        if self.max_repairs_per_task < 0:
            raise ValueError("max_repairs_per_task must be non-negative")
        if self.max_replanning_cycles < 0:
            raise ValueError("max_replanning_cycles must be non-negative")


class InitialPlanningAction:
    """Ask one initial orchestrator for a bounded plan and register it.

    This action owns planning policy and state mutation. It deliberately reuses
    ``WorkflowAPI.agent`` for execution, model routing, structured output,
    approvals, telemetry, cache, timeout, and token accounting.
    """

    def __init__(self, limits: PlanningLimits | None = None):
        self.limits = limits or PlanningLimits()

    async def run(
        self,
        api: Any,
        *,
        original_objective: str,
        cycle: int = 0,
    ) -> dict[str, Any]:
        objective = str(original_objective or "").strip()
        if not objective:
            raise ReviewedStateError("original objective must be a non-empty string")
        if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 0:
            raise ReviewedStateError("planning cycle must be a non-negative integer")

        prompt = self._prompt(objective=objective, cycle=cycle)
        plan = await api.agent(
            prompt,
            {
                "label": f"initial-orchestrator:cycle-{cycle}",
                "phase": "Planning",
                "schema": PLAN_PACKAGE_SCHEMA,
                "agentType": "initial-orchestrator",
                "isolation": "shared",
            },
        )
        try:
            validate_schema(plan, PLAN_PACKAGE_SCHEMA)
        except Exception as exc:
            raise ReviewedStateError(f"initial orchestrator returned an invalid PlanPackage: {exc}") from exc
        if not isinstance(plan, dict):
            raise ReviewedStateError("initial orchestrator returned a non-object PlanPackage")

        self._validate_semantics(plan, objective=objective, cycle=cycle)
        api.context.state.reviewed.register_plan(plan)
        api.context.journal(
            {
                "type": "reviewed_plan_registered",
                "planId": plan["plan_id"],
                "cycle": cycle,
                "taskIds": [task["task_id"] for task in plan["tasks"]],
            }
        )
        api.context.notify()
        return deepcopy(plan)

    def _prompt(self, *, objective: str, cycle: int) -> str:
        limits = self.limits
        return (
            "Create the initial reviewed-workflow PlanPackage for the objective below.\n\n"
            "Preserve the objective exactly in original_objective. Normalize its requirements "
            "through explicit, ordered tasks rather than rewriting or narrowing the request. "
            "Each task must be independently executable and reviewable, with dependencies, "
            "paths, constraints, allowed mutations, acceptance criteria, evidence requirements, "
            "worker instructions, and separate reviewer guidelines. Dependencies must reference "
            "only tasks that appear earlier in the tasks array. Include evidence-based final "
            "validation criteria. Do not execute, review, repair, or integrate any task.\n\n"
            f"Required cycle: {cycle}\n"
            f"Maximum tasks: {limits.max_tasks}\n"
            f"Maximum repairs per task: {limits.max_repairs_per_task}\n"
            f"Maximum replanning cycles: {limits.max_replanning_cycles}\n"
            "The package may select stricter repair/replanning limits, but must not exceed these caps.\n\n"
            f"Original objective (JSON string): {json.dumps(objective, ensure_ascii=False)}"
        )

    def _validate_semantics(
        self,
        plan: dict[str, Any],
        *,
        objective: str,
        cycle: int,
    ) -> None:
        if plan.get("cycle") != cycle:
            raise ReviewedStateError(
                f"initial plan cycle mismatch: expected {cycle}, got {plan.get('cycle')!r}"
            )
        if plan.get("original_objective") != objective:
            raise ReviewedStateError("initial plan must preserve original_objective exactly")

        tasks = plan.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            raise ReviewedStateError("initial plan must contain at least one task")
        if len(tasks) > self.limits.max_tasks:
            raise ReviewedStateError(
                f"initial plan exceeds task cap ({len(tasks)} > {self.limits.max_tasks})"
            )

        repairs = plan.get("max_repairs_per_task")
        replans = plan.get("max_replanning_cycles")
        if not isinstance(repairs, int) or isinstance(repairs, bool):
            raise ReviewedStateError("max_repairs_per_task must be an integer")
        if not isinstance(replans, int) or isinstance(replans, bool):
            raise ReviewedStateError("max_replanning_cycles must be an integer")
        if repairs > self.limits.max_repairs_per_task:
            raise ReviewedStateError(
                "initial plan exceeds max_repairs_per_task cap "
                f"({repairs} > {self.limits.max_repairs_per_task})"
            )
        if replans > self.limits.max_replanning_cycles:
            raise ReviewedStateError(
                "initial plan exceeds max_replanning_cycles cap "
                f"({replans} > {self.limits.max_replanning_cycles})"
            )

        plan_id = str(plan.get("plan_id") or "").strip()
        seen: set[str] = set()
        for index, task in enumerate(tasks):
            if not isinstance(task, dict):
                raise ReviewedStateError(f"tasks[{index}] must be an object")
            task_id = str(task.get("task_id") or "").strip()
            if not task_id:
                raise ReviewedStateError(f"tasks[{index}].task_id must be non-empty")
            if task_id in seen:
                raise ReviewedStateError(f"duplicate task_id in initial plan: {task_id}")
            if task.get("plan_id") != plan_id:
                raise ReviewedStateError(
                    f"task {task_id} plan_id does not match plan {plan_id}"
                )
            depends_on = task.get("depends_on")
            if not isinstance(depends_on, list):
                raise ReviewedStateError(f"task {task_id}.depends_on must be a list")
            duplicates = _duplicates(depends_on)
            if duplicates:
                raise ReviewedStateError(
                    f"task {task_id} repeats dependency {duplicates[0]}"
                )
            unavailable = [dependency for dependency in depends_on if dependency not in seen]
            if unavailable:
                raise ReviewedStateError(
                    f"task {task_id} dependency must appear earlier: {unavailable[0]}"
                )
            seen.add(task_id)


def _duplicates(values: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    duplicates: list[Any] = []
    for value in values:
        try:
            already_seen = value in seen
        except TypeError:
            return [value]
        if already_seen:
            duplicates.append(value)
        else:
            seen.add(value)
    return duplicates
