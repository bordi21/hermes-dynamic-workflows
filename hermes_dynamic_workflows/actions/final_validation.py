"""Final validation and bounded delta replanning for reviewed workflows."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from ..contracts.packages import FINAL_VALIDATION_PACKAGE_SCHEMA
from ..core.errors import ReviewedStateError
from ..core.reviewed_state import TERMINAL_TASK_STATUSES
from ..core.schema import validate_schema
from .planning import InitialPlanningAction


class FinalValidationAction:
    """Validate the integrated result and optionally register one bounded delta plan.

    The final orchestrator is read-only. This action owns lifecycle policy,
    fail-closed semantic validation, replanning limits, state mutation, and
    registration of the next complete ``PlanPackage`` through the canonical
    planning action.
    """

    def __init__(self, planner: InitialPlanningAction | None = None):
        self.planner = planner or InitialPlanningAction()

    async def run(
        self,
        api: Any,
        *,
        plan_id: str | None = None,
    ) -> dict[str, Any]:
        snapshot = api.context.state.reviewed.snapshot()
        cycle_state, task_states = _select_terminal_cycle(snapshot, plan_id=plan_id)
        plan = deepcopy(cycle_state["plan"])
        cycle = int(cycle_state["cycle"])
        max_cycles = int(plan["max_replanning_cycles"])
        remaining_cycles = max(0, max_cycles - cycle)

        prompt = _validation_prompt(
            snapshot=snapshot,
            plan=plan,
            task_states=task_states,
            remaining_cycles=remaining_cycles,
        )
        validation = await api.agent(
            prompt,
            {
                "label": f"final-orchestrator:cycle-{cycle}",
                "phase": "Final Validation",
                "schema": FINAL_VALIDATION_PACKAGE_SCHEMA,
                "agentType": "final-orchestrator",
                "isolation": "shared",
            },
        )
        validated = _validate_final_validation(
            validation,
            plan=plan,
            cycle=cycle,
            remaining_cycles=remaining_cycles,
            snapshot=snapshot,
        )

        next_plan: dict[str, Any] | None = None
        if validated["verdict"] == "NOT_APPROVED" and remaining_cycles > 0:
            next_plan = _build_delta_plan(
                validation=validated,
                current_plan=plan,
                next_cycle=cycle + 1,
            )
            integrated_task_ids = {
                task["task_id"]
                for task in snapshot["tasks"]
                if task["status"] == "INTEGRATED"
            }
            self.planner.validate_plan(
                next_plan,
                original_objective=plan["original_objective"],
                cycle=cycle + 1,
                source_label="final orchestrator delta plan",
                plan_label="delta plan",
                allowed_existing_dependencies=integrated_task_ids,
            )

        api.context.state.reviewed.record_final_validation(validated)
        _journal_validation(
            api,
            validation=validated,
            remaining_cycles=remaining_cycles,
        )

        if next_plan is not None:
            next_plan = self.planner.register_plan(
                api,
                next_plan,
                original_objective=plan["original_objective"],
                cycle=cycle + 1,
                source_label="final orchestrator delta plan",
                plan_label="delta plan",
                allowed_existing_dependencies={
                    task["task_id"]
                    for task in snapshot["tasks"]
                    if task["status"] == "INTEGRATED"
                },
                event_type="reviewed_delta_plan_registered",
                source_plan_id=plan["plan_id"],
            )
            status = "REPLANNED"
        elif validated["verdict"] == "NOT_APPROVED":
            status = "EXHAUSTED"
            api.context.journal(
                {
                    "type": "reviewed_replanning_exhausted",
                    "planId": plan["plan_id"],
                    "cycle": cycle,
                    "maxReplanningCycles": max_cycles,
                }
            )
            api.context.notify()
        else:
            status = str(validated["verdict"])

        return {
            "plan_id": plan["plan_id"],
            "cycle": cycle,
            "status": status,
            "validation": deepcopy(validated),
            "remaining_replanning_cycles": max(0, remaining_cycles - (1 if next_plan else 0)),
            "next_plan": deepcopy(next_plan),
        }


def _select_terminal_cycle(
    snapshot: dict[str, Any],
    *,
    plan_id: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cycles = snapshot.get("planning_cycles")
    if not isinstance(cycles, list) or not cycles:
        raise ReviewedStateError("final validation requires a registered planning cycle")

    latest = max(cycles, key=lambda item: int(item["cycle"]))
    requested = str(plan_id or latest["plan_id"]).strip()
    selected = next((item for item in cycles if item.get("plan_id") == requested), None)
    if selected is None:
        raise ReviewedStateError(f"final validation plan not found: {requested!r}")
    if selected["plan_id"] != latest["plan_id"]:
        raise ReviewedStateError("final validation may run only for the latest planning cycle")
    if selected.get("final_validation") is not None:
        raise ReviewedStateError(
            f"planning cycle {selected['cycle']} already has a final validation"
        )

    task_ids = set(selected["task_ids"])
    task_states = [
        deepcopy(task)
        for task in snapshot.get("tasks", [])
        if task.get("task_id") in task_ids
    ]
    if len(task_states) != len(task_ids):
        raise ReviewedStateError("final validation cycle has missing task state")
    nonterminal = [
        task["task_id"]
        for task in task_states
        if task.get("status") not in TERMINAL_TASK_STATUSES
    ]
    if nonterminal:
        raise ReviewedStateError(
            "final validation requires terminal task states; still active: "
            + ", ".join(nonterminal)
        )
    return deepcopy(selected), task_states


def _validation_prompt(
    *,
    snapshot: dict[str, Any],
    plan: dict[str, Any],
    task_states: list[dict[str, Any]],
    remaining_cycles: int,
) -> str:
    return (
        "Validate the integrated project state against the original objective and every "
        "final validation criterion. Operate read-only and inspect the current checkout, "
        "tests, persisted task lineage, worker evidence, reviewer verdicts, repairs, "
        "integrations, failures, and blockers. Return only the required "
        "FinalValidationPackage through structured output.\n\n"
        "Requirement results must appear in exactly the same order and use exactly the "
        "same requirement strings as final_validation_criteria. APPROVED requires every "
        "requirement to be satisfied and delta_tasks to be empty. BLOCKED requires a "
        "specific external blocker and delta_tasks to be empty. NOT_APPROVED requires at "
        "least one concrete gap.\n\n"
        f"Remaining replanning cycles: {remaining_cycles}\n"
        + (
            "For NOT_APPROVED, create a non-empty, focused delta_tasks array. Every delta "
            "task must use the same new plan_id, different from the current plan_id. A delta "
            "task may depend only on already INTEGRATED tasks or earlier delta tasks."
            if remaining_cycles > 0
            else "No replanning cycles remain. For NOT_APPROVED, delta_tasks must be empty."
        )
        + "\n\n"
        f"Current PlanPackage:\n{_json(plan)}\n\n"
        f"Current cycle task states:\n{_json(task_states)}\n\n"
        f"Complete reviewed workflow snapshot:\n{_json(snapshot)}"
    )


def _validate_final_validation(
    validation: Any,
    *,
    plan: dict[str, Any],
    cycle: int,
    remaining_cycles: int,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    try:
        validate_schema(validation, FINAL_VALIDATION_PACKAGE_SCHEMA)
    except Exception as exc:
        raise ReviewedStateError(
            f"final orchestrator returned an invalid FinalValidationPackage: {exc}"
        ) from exc
    if not isinstance(validation, dict):
        raise ReviewedStateError(
            "final orchestrator returned a non-object FinalValidationPackage"
        )
    if validation.get("plan_id") != plan["plan_id"]:
        raise ReviewedStateError("final validation plan_id does not match the current plan")
    if validation.get("cycle") != cycle:
        raise ReviewedStateError("final validation cycle does not match the current plan")

    criteria = list(plan["final_validation_criteria"])
    results = validation["requirement_results"]
    requirements = [item["requirement"] for item in results]
    if requirements != criteria:
        raise ReviewedStateError(
            "final validation requirement_results must exactly match final_validation_criteria"
        )
    for result in results:
        if result["satisfied"] and result["gap"]:
            raise ReviewedStateError(
                f"satisfied requirement must not report a gap: {result['requirement']}"
            )
        if not result["satisfied"] and not str(result["gap"]).strip():
            raise ReviewedStateError(
                f"unsatisfied requirement must report a concrete gap: {result['requirement']}"
            )

    verdict = validation["verdict"]
    all_satisfied = all(item["satisfied"] for item in results)
    delta_tasks = validation["delta_tasks"]
    if verdict == "APPROVED":
        if not all_satisfied:
            raise ReviewedStateError("APPROVED requires every requirement to be satisfied")
        if delta_tasks:
            raise ReviewedStateError("APPROVED cannot include delta tasks")
    elif verdict == "BLOCKED":
        if all_satisfied:
            raise ReviewedStateError("BLOCKED requires at least one unsatisfied requirement")
        if delta_tasks:
            raise ReviewedStateError("BLOCKED cannot include delta tasks")
    else:
        if all_satisfied:
            raise ReviewedStateError("NOT_APPROVED requires at least one unsatisfied requirement")
        if remaining_cycles > 0 and not delta_tasks:
            raise ReviewedStateError(
                "NOT_APPROVED requires delta tasks while replanning remains available"
            )
        if remaining_cycles == 0 and delta_tasks:
            raise ReviewedStateError(
                "NOT_APPROVED cannot include delta tasks after replanning is exhausted"
            )
        if delta_tasks:
            _validate_delta_lineage(
                delta_tasks,
                current_plan_id=plan["plan_id"],
                snapshot=snapshot,
            )
    return deepcopy(validation)


def _validate_delta_lineage(
    delta_tasks: list[dict[str, Any]],
    *,
    current_plan_id: str,
    snapshot: dict[str, Any],
) -> None:
    next_plan_ids = {str(task.get("plan_id") or "").strip() for task in delta_tasks}
    if "" in next_plan_ids or len(next_plan_ids) != 1:
        raise ReviewedStateError("all delta tasks must share one non-empty new plan_id")
    next_plan_id = next(iter(next_plan_ids))
    if next_plan_id == current_plan_id:
        raise ReviewedStateError("delta tasks must use a new plan_id")
    existing_plan_ids = {
        str(item.get("plan_id") or "")
        for item in snapshot.get("planning_cycles", [])
    }
    if next_plan_id in existing_plan_ids:
        raise ReviewedStateError(f"delta plan_id is already registered: {next_plan_id}")

    existing_task_ids = {
        str(task.get("task_id") or "") for task in snapshot.get("tasks", [])
    }
    new_task_ids: set[str] = set()
    for task in delta_tasks:
        task_id = str(task.get("task_id") or "").strip()
        if task_id in existing_task_ids:
            raise ReviewedStateError(f"delta task_id is already registered: {task_id}")
        if task_id in new_task_ids:
            raise ReviewedStateError(f"duplicate delta task_id: {task_id}")
        new_task_ids.add(task_id)


def _build_delta_plan(
    *,
    validation: dict[str, Any],
    current_plan: dict[str, Any],
    next_cycle: int,
) -> dict[str, Any]:
    delta_tasks = deepcopy(validation["delta_tasks"])
    return {
        "schema_version": "1.0",
        "plan_id": delta_tasks[0]["plan_id"],
        "cycle": next_cycle,
        "original_objective": current_plan["original_objective"],
        "tasks": delta_tasks,
        "final_validation_criteria": deepcopy(
            current_plan["final_validation_criteria"]
        ),
        "max_repairs_per_task": current_plan["max_repairs_per_task"],
        "max_replanning_cycles": current_plan["max_replanning_cycles"],
    }


def _journal_validation(
    api: Any,
    *,
    validation: dict[str, Any],
    remaining_cycles: int,
) -> None:
    api.context.journal(
        {
            "type": "reviewed_final_validation_recorded",
            "planId": validation["plan_id"],
            "cycle": validation["cycle"],
            "verdict": validation["verdict"],
            "deltaTaskIds": [task["task_id"] for task in validation["delta_tasks"]],
            "remainingReplanningCycles": remaining_cycles,
        }
    )
    api.context.notify()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
