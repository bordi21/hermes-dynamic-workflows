"""Canonical end-to-end reviewed workflow lifecycle."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..core.errors import ReviewedStateError
from ..core.reviewed_state import TERMINAL_TASK_STATUSES
from .execution import ReviewedTaskExecutionAction
from .final_validation import FinalValidationAction
from .planning import InitialPlanningAction
from .reporting import TerminalReportAction


class ReviewedWorkflowAction:
    """Run planning through deterministic terminal reporting on one runtime.

    This composite Action owns lifecycle sequencing only. Child launches still
    pass through ``WorkflowAPI.agent`` and therefore retain the existing model
    routing, approvals, accounting, transcripts, pause/stop checks, token and
    agent limits, notifications, journal, worktrees, and resume cache.
    """

    def __init__(
        self,
        *,
        planner: InitialPlanningAction | None = None,
        executor: ReviewedTaskExecutionAction | None = None,
        validator: FinalValidationAction | None = None,
        reporter: TerminalReportAction | None = None,
    ) -> None:
        self.planner = planner or InitialPlanningAction()
        self.executor = executor or ReviewedTaskExecutionAction()
        self.validator = validator or FinalValidationAction(planner=self.planner)
        self.reporter = reporter or TerminalReportAction()

    async def run(self, api: Any, *, original_objective: str) -> dict[str, Any]:
        objective = _normalize_objective(original_objective)
        snapshot = api.context.state.reviewed.snapshot()
        terminal_report = snapshot.get("terminal_report")
        if terminal_report is not None:
            if terminal_report.get("original_objective") != objective:
                raise ReviewedStateError(
                    "existing terminal report belongs to a different original objective"
                )
            return deepcopy(terminal_report)

        cycles = snapshot.get("planning_cycles") or []
        if not cycles:
            api.phase("Planning")
            api.log("Creating the bounded reviewed-workflow plan.")
            await self.planner.run(
                api,
                original_objective=objective,
                cycle=0,
            )
        else:
            initial_objective = str(cycles[0].get("original_objective") or "")
            if initial_objective != objective:
                raise ReviewedStateError(
                    "existing reviewed workflow belongs to a different original objective"
                )

        while True:
            api.context.check_runtime()
            latest = _latest_cycle(api.context.state.reviewed.snapshot())
            if latest.get("final_validation") is None:
                api.phase("Execution")
                api.log(
                    f"Executing reviewed workflow cycle {latest['cycle']} "
                    f"({latest['plan_id']})."
                )
                await self.executor.run_ready(api)
                _skip_unrunnable_tasks(api)
                _require_cycle_terminal(
                    api.context.state.reviewed.snapshot(),
                    plan_id=str(latest["plan_id"]),
                )

                api.phase("Final Validation")
                api.log(
                    f"Validating cycle {latest['cycle']} against the original objective."
                )
                validation_result = await self.validator.run(
                    api,
                    plan_id=str(latest["plan_id"]),
                )
                if validation_result["status"] == "REPLANNED":
                    continue
            else:
                _require_cycle_terminal(
                    api.context.state.reviewed.snapshot(),
                    plan_id=str(latest["plan_id"]),
                )
                _require_terminal_validation_state(latest)

            api.phase("Reporting")
            api.log("Building the deterministic evidence-backed terminal report.")
            return self.reporter.run(api)


def _normalize_objective(value: Any) -> str:
    objective = str(value or "").strip()
    if not objective:
        raise ReviewedStateError("reviewed workflow objective must be a non-empty string")
    return objective


def _latest_cycle(snapshot: dict[str, Any]) -> dict[str, Any]:
    cycles = snapshot.get("planning_cycles")
    if not isinstance(cycles, list) or not cycles:
        raise ReviewedStateError("reviewed workflow has no registered planning cycle")
    try:
        return deepcopy(max(cycles, key=lambda item: int(item["cycle"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewedStateError("reviewed workflow has invalid planning-cycle state") from exc


def _skip_unrunnable_tasks(api: Any) -> list[str]:
    """Transitively skip PLANNED tasks whose dependencies ended non-integrated."""

    skipped: list[str] = []
    while True:
        snapshot = api.context.state.reviewed.snapshot()
        by_id = {
            str(task.get("task_id") or ""): task
            for task in snapshot.get("tasks") or []
            if isinstance(task, dict)
        }
        changed = False
        for task in snapshot.get("tasks") or []:
            if not isinstance(task, dict) or task.get("status") != "PLANNED":
                continue
            dependency_outcomes = [
                (dependency, by_id.get(dependency, {}).get("status"))
                for dependency in task.get("depends_on") or []
                if by_id.get(dependency, {}).get("status") in TERMINAL_TASK_STATUSES
                and by_id.get(dependency, {}).get("status") != "INTEGRATED"
            ]
            if not dependency_outcomes:
                continue
            reason = "Required dependency did not integrate: " + ", ".join(
                f"{dependency}={status}" for dependency, status in dependency_outcomes
            )
            task_id = str(task.get("task_id") or "")
            api.context.state.reviewed.skip_task(task_id, reason)
            api.context.journal(
                {
                    "type": "reviewed_task_skipped",
                    "planId": task.get("plan_id"),
                    "taskId": task_id,
                    "cycle": task.get("cycle"),
                    "reason": reason,
                    "dependencies": [
                        {"taskId": dependency, "status": status}
                        for dependency, status in dependency_outcomes
                    ],
                }
            )
            api.context.notify()
            skipped.append(task_id)
            changed = True
        if not changed:
            return skipped


def _require_cycle_terminal(snapshot: dict[str, Any], *, plan_id: str) -> None:
    cycle = next(
        (
            item
            for item in snapshot.get("planning_cycles") or []
            if item.get("plan_id") == plan_id
        ),
        None,
    )
    if not isinstance(cycle, dict):
        raise ReviewedStateError(f"reviewed workflow cycle not found: {plan_id!r}")
    task_ids = set(cycle.get("task_ids") or [])
    active = [
        f"{task.get('task_id')}={task.get('status')}"
        for task in snapshot.get("tasks") or []
        if task.get("task_id") in task_ids
        and task.get("status") not in TERMINAL_TASK_STATUSES
    ]
    if active:
        raise ReviewedStateError(
            "reviewed workflow cycle cannot advance with nonterminal tasks: "
            + ", ".join(active)
        )


def _require_terminal_validation_state(cycle: dict[str, Any]) -> None:
    validation = cycle.get("final_validation")
    if not isinstance(validation, dict):
        raise ReviewedStateError("reviewed workflow cycle is missing final validation")
    verdict = validation.get("verdict")
    if verdict in {"APPROVED", "BLOCKED"}:
        return
    if verdict != "NOT_APPROVED":
        raise ReviewedStateError(f"unsupported final validation verdict: {verdict!r}")
    plan = cycle.get("plan")
    if not isinstance(plan, dict):
        raise ReviewedStateError("reviewed workflow cycle is missing its plan")
    current = cycle.get("cycle")
    maximum = plan.get("max_replanning_cycles")
    if (
        isinstance(current, bool)
        or not isinstance(current, int)
        or isinstance(maximum, bool)
        or not isinstance(maximum, int)
    ):
        raise ReviewedStateError("reviewed workflow has invalid replanning limits")
    if current < maximum:
        raise ReviewedStateError(
            "reviewed workflow has NOT_APPROVED validation but no registered delta cycle"
        )
