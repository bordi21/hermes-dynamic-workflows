"""Canonical reviewed-workflow lineage and fail-closed task transitions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from .errors import ReviewedStateError


REVIEWED_STATE_VERSION = "1.0"
TASK_STATUSES = frozenset(
    {
        "PLANNED",
        "EXECUTING",
        "REVIEWING",
        "PASS",
        "FAIL",
        "BLOCKED",
        "REPAIRING",
        "INTEGRATED",
        "FAILED",
        "SKIPPED",
    }
)
TERMINAL_TASK_STATUSES = frozenset({"INTEGRATED", "FAILED", "BLOCKED", "SKIPPED"})

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "PLANNED": frozenset({"EXECUTING", "SKIPPED"}),
    "EXECUTING": frozenset({"REVIEWING"}),
    "REVIEWING": frozenset({"PASS", "FAIL", "BLOCKED"}),
    "PASS": frozenset({"INTEGRATED", "FAILED"}),
    "FAIL": frozenset({"REPAIRING", "FAILED"}),
    "REPAIRING": frozenset({"REVIEWING"}),
    "BLOCKED": frozenset(),
    "INTEGRATED": frozenset(),
    "FAILED": frozenset(),
    "SKIPPED": frozenset(),
}


@dataclass
class ReviewedTaskState:
    plan_id: str
    task_id: str
    cycle: int
    depends_on: tuple[str, ...]
    task: dict[str, Any]
    status: str = "PLANNED"
    worker_attempts: list[dict[str, Any]] = field(default_factory=list)
    review_verdicts: list[dict[str, Any]] = field(default_factory=list)
    repair_attempts: list[dict[str, Any]] = field(default_factory=list)
    integration: dict[str, Any] | None = None
    skip_reason: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "cycle": self.cycle,
            "depends_on": list(self.depends_on),
            "status": self.status,
            "task": deepcopy(self.task),
            "worker_attempts": deepcopy(self.worker_attempts),
            "review_verdicts": deepcopy(self.review_verdicts),
            "repair_attempts": deepcopy(self.repair_attempts),
            "integration": deepcopy(self.integration),
            "skip_reason": self.skip_reason,
        }


@dataclass
class PlanningCycleState:
    plan_id: str
    cycle: int
    original_objective: str
    task_ids: tuple[str, ...]
    plan: dict[str, Any]
    status: str = "PLANNED"
    final_validation: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "cycle": self.cycle,
            "original_objective": self.original_objective,
            "task_ids": list(self.task_ids),
            "status": self.status,
            "plan": deepcopy(self.plan),
            "final_validation": deepcopy(self.final_validation),
        }


@dataclass
class ReviewedWorkflowState:
    """Reviewed-workflow state embedded in the existing workflow snapshot.

    The class owns domain transitions only. Execution, scheduling, review, repair,
    integration, persistence, and user-facing policy remain with their existing
    runtime/action owners.
    """

    planning_cycles: list[PlanningCycleState] = field(default_factory=list)
    tasks: dict[str, ReviewedTaskState] = field(default_factory=dict)
    final_validations: list[dict[str, Any]] = field(default_factory=list)
    terminal_report: dict[str, Any] | None = None
    _lock: RLock = field(default_factory=RLock, init=False, repr=False, compare=False)

    def register_plan(self, plan: dict[str, Any]) -> None:
        plan_value = _require_mapping(plan, "plan")
        plan_id = _require_text(plan_value, "plan_id")
        cycle = _require_nonnegative_int(plan_value, "cycle")
        original_objective = _require_text(plan_value, "original_objective")
        raw_tasks = plan_value.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise ReviewedStateError("plan.tasks must be a non-empty list")

        parsed: list[tuple[str, tuple[str, ...], dict[str, Any]]] = []
        new_task_ids: set[str] = set()
        for index, raw_task in enumerate(raw_tasks):
            task = _require_mapping(raw_task, f"plan.tasks[{index}]")
            task_plan_id = _require_text(task, "plan_id")
            if task_plan_id != plan_id:
                raise ReviewedStateError(
                    f"task {task.get('task_id')!r} belongs to plan {task_plan_id!r}, expected {plan_id!r}"
                )
            task_id = _require_text(task, "task_id")
            if task_id in new_task_ids:
                raise ReviewedStateError(f"duplicate task_id in plan: {task_id}")
            new_task_ids.add(task_id)
            depends_on = _require_string_list(task.get("depends_on"), f"task {task_id}.depends_on")
            if task_id in depends_on:
                raise ReviewedStateError(f"task {task_id} cannot depend on itself")
            parsed.append((task_id, tuple(depends_on), deepcopy(task)))

        with self._lock:
            if any(item.plan_id == plan_id for item in self.planning_cycles):
                raise ReviewedStateError(f"plan_id is already registered: {plan_id}")
            if any(item.cycle == cycle for item in self.planning_cycles):
                raise ReviewedStateError(f"planning cycle is already registered: {cycle}")
            duplicate = sorted(new_task_ids.intersection(self.tasks))
            if duplicate:
                raise ReviewedStateError(f"task_id is already registered: {duplicate[0]}")

            known_task_ids = set(self.tasks).union(new_task_ids)
            for task_id, depends_on, _task in parsed:
                unknown = sorted(set(depends_on).difference(known_task_ids))
                if unknown:
                    raise ReviewedStateError(
                        f"task {task_id} has unknown dependency: {unknown[0]}"
                    )

            self.planning_cycles.append(
                PlanningCycleState(
                    plan_id=plan_id,
                    cycle=cycle,
                    original_objective=original_objective,
                    task_ids=tuple(task_id for task_id, _depends, _task in parsed),
                    plan=deepcopy(plan_value),
                )
            )
            for task_id, depends_on, task in parsed:
                self.tasks[task_id] = ReviewedTaskState(
                    plan_id=plan_id,
                    task_id=task_id,
                    cycle=cycle,
                    depends_on=depends_on,
                    task=task,
                )

    def ready_task_ids(self) -> list[str]:
        with self._lock:
            return [
                task.task_id
                for task in self.tasks.values()
                if task.status == "PLANNED"
                and all(
                    dependency in self.tasks
                    and self.tasks[dependency].status == "INTEGRATED"
                    for dependency in task.depends_on
                )
            ]

    def start_task(self, task_id: str) -> None:
        with self._lock:
            task = self._task(task_id)
            blocked = [
                dependency
                for dependency in task.depends_on
                if self.tasks.get(dependency) is None
                or self.tasks[dependency].status != "INTEGRATED"
            ]
            if blocked:
                raise ReviewedStateError(
                    f"task {task.task_id} dependencies are not integrated: {', '.join(blocked)}"
                )
            self._transition(task, "EXECUTING")

    def skip_task(self, task_id: str, reason: str) -> None:
        clean_reason = str(reason or "").strip()
        if not clean_reason:
            raise ReviewedStateError("skipped task reason must be a non-empty string")
        with self._lock:
            task = self._task(task_id)
            if task.status != "PLANNED":
                self._illegal_transition(task, "SKIPPED")
            terminal_dependencies = [
                dependency
                for dependency in task.depends_on
                if dependency in self.tasks
                and self.tasks[dependency].status in TERMINAL_TASK_STATUSES
                and self.tasks[dependency].status != "INTEGRATED"
            ]
            if not terminal_dependencies:
                raise ReviewedStateError(
                    f"task {task.task_id} cannot be skipped without a terminal non-integrated dependency"
                )
            task.skip_reason = clean_reason
            self._transition(task, "SKIPPED")

    def submit_worker_result(self, task_id: str, result: dict[str, Any]) -> None:
        result_value = _require_mapping(result, "worker result")
        with self._lock:
            task = self._task(task_id)
            if task.status != "EXECUTING":
                self._illegal_transition(task, "REVIEWING")
            self._validate_result_lineage(task, result_value)
            attempt = _require_positive_int(result_value, "attempt")
            self._require_new_worker_attempt(task, attempt)
            task.worker_attempts.append(deepcopy(result_value))
            self._transition(task, "REVIEWING")

    def submit_review_verdict(self, task_id: str, verdict: dict[str, Any]) -> None:
        verdict_value = _require_mapping(verdict, "review verdict")
        with self._lock:
            task = self._task(task_id)
            if task.status != "REVIEWING":
                raise ReviewedStateError(
                    f"task {task.task_id} cannot receive a review while {task.status}"
                )
            if not task.worker_attempts:
                raise ReviewedStateError(
                    f"task {task.task_id} cannot be reviewed without a worker attempt"
                )
            self._validate_result_lineage(task, verdict_value)
            attempt = _require_positive_int(verdict_value, "attempt")
            latest_attempt = _require_positive_int(task.worker_attempts[-1], "attempt")
            if attempt != latest_attempt:
                raise ReviewedStateError(
                    f"task {task.task_id} review attempt {attempt} does not match worker attempt {latest_attempt}"
                )
            raw_verdict = verdict_value.get("verdict")
            if not isinstance(raw_verdict, str) or raw_verdict not in {"PASS", "FAIL", "BLOCKED"}:
                raise ReviewedStateError(
                    f"task {task.task_id} review verdict must be PASS, FAIL, or BLOCKED"
                )
            if raw_verdict == "PASS" and task.worker_attempts[-1].get("status") != "COMPLETED":
                raise ReviewedStateError(
                    f"task {task.task_id} cannot PASS without a completed worker result"
                )
            task.review_verdicts.append(deepcopy(verdict_value))
            self._transition(task, raw_verdict)

    def start_repair(self, task_id: str, repair: dict[str, Any]) -> None:
        repair_value = _require_mapping(repair, "repair package")
        with self._lock:
            task = self._task(task_id)
            if task.status != "FAIL":
                self._illegal_transition(task, "REPAIRING")
            self._validate_result_lineage(task, repair_value)
            repair_attempt = _require_positive_int(repair_value, "repair_attempt")
            if task.repair_attempts:
                previous = _require_positive_int(
                    task.repair_attempts[-1]["repair"], "repair_attempt"
                )
                if repair_attempt <= previous:
                    raise ReviewedStateError(
                        f"task {task.task_id} repair attempt must increase beyond {previous}"
                    )
            if not task.review_verdicts or task.review_verdicts[-1].get("verdict") != "FAIL":
                raise ReviewedStateError(
                    f"task {task.task_id} cannot be repaired without a FAIL verdict"
                )
            task.repair_attempts.append(
                {"repair": deepcopy(repair_value), "worker_result": None}
            )
            self._transition(task, "REPAIRING")

    def submit_repair_result(self, task_id: str, result: dict[str, Any]) -> None:
        result_value = _require_mapping(result, "repair worker result")
        with self._lock:
            task = self._task(task_id)
            if task.status != "REPAIRING":
                self._illegal_transition(task, "REVIEWING")
            if not task.repair_attempts or task.repair_attempts[-1]["worker_result"] is not None:
                raise ReviewedStateError(
                    f"task {task.task_id} has no active repair attempt"
                )
            self._validate_result_lineage(task, result_value)
            attempt = _require_positive_int(result_value, "attempt")
            self._require_new_worker_attempt(task, attempt)
            copied = deepcopy(result_value)
            task.worker_attempts.append(copied)
            task.repair_attempts[-1]["worker_result"] = deepcopy(copied)
            self._transition(task, "REVIEWING")

    def integrate_task(self, task_id: str, integration: dict[str, Any]) -> None:
        integration_value = _require_mapping(integration, "integration result")
        with self._lock:
            task = self._task(task_id)
            if task.status != "PASS":
                self._illegal_transition(task, "INTEGRATED")
            if not task.review_verdicts or task.review_verdicts[-1].get("verdict") != "PASS":
                raise ReviewedStateError(
                    f"task {task.task_id} cannot be integrated without a PASS review"
                )
            self._validate_result_lineage(task, integration_value)
            if integration_value.get("status") != "INTEGRATED":
                raise ReviewedStateError(
                    f"task {task.task_id} integration status must be INTEGRATED"
                )
            if task.integration is not None:
                raise ReviewedStateError(f"task {task.task_id} is already integrated")
            task.integration = deepcopy(integration_value)
            self._transition(task, "INTEGRATED")

    def record_integration_failure(self, task_id: str, integration: dict[str, Any]) -> None:
        """Persist a failed PASS-only integration and terminalize the task.

        A reviewer PASS authorizes an integration attempt, not a successful merge.
        Conflicts and mechanical integration failures are evidence-backed task
        failures and must not leave the lifecycle stranded in nonterminal PASS.
        """

        integration_value = _require_mapping(integration, "integration result")
        with self._lock:
            task = self._task(task_id)
            if task.status != "PASS":
                self._illegal_transition(task, "FAILED")
            if not task.review_verdicts or task.review_verdicts[-1].get("verdict") != "PASS":
                raise ReviewedStateError(
                    f"task {task.task_id} cannot record integration failure without a PASS review"
                )
            self._validate_result_lineage(task, integration_value)
            status = integration_value.get("status")
            if status not in {"CONFLICT", "FAILED"}:
                raise ReviewedStateError(
                    f"task {task.task_id} integration failure status must be CONFLICT or FAILED"
                )
            if task.integration is not None:
                raise ReviewedStateError(f"task {task.task_id} already has an integration result")
            task.integration = deepcopy(integration_value)
            self._transition(task, "FAILED")

    def mark_task_failed(self, task_id: str) -> None:
        with self._lock:
            task = self._task(task_id)
            self._transition(task, "FAILED")

    def record_final_validation(self, validation: dict[str, Any]) -> None:
        value = _require_mapping(validation, "final validation")
        plan_id = _require_text(value, "plan_id")
        cycle = _require_nonnegative_int(value, "cycle")
        verdict = value.get("verdict")
        if verdict not in {"APPROVED", "NOT_APPROVED", "BLOCKED"}:
            raise ReviewedStateError(
                "final validation verdict must be APPROVED, NOT_APPROVED, or BLOCKED"
            )
        with self._lock:
            planning_cycle = next(
                (
                    item
                    for item in self.planning_cycles
                    if item.plan_id == plan_id and item.cycle == cycle
                ),
                None,
            )
            if planning_cycle is None:
                raise ReviewedStateError(
                    f"final validation references unknown plan/cycle: {plan_id}/{cycle}"
                )
            copied = deepcopy(value)
            self.final_validations.append(copied)
            planning_cycle.final_validation = deepcopy(copied)
            planning_cycle.status = str(verdict)

    def set_terminal_report(self, report: dict[str, Any]) -> None:
        value = _require_mapping(report, "terminal report")
        if value.get("outcome") not in {"APPROVED", "FAILED", "BLOCKED", "PARTIAL"}:
            raise ReviewedStateError(
                "terminal report outcome must be APPROVED, FAILED, BLOCKED, or PARTIAL"
            )
        with self._lock:
            if self.terminal_report is not None:
                raise ReviewedStateError("terminal report is already recorded")
            if not self.final_validations:
                raise ReviewedStateError(
                    "terminal report cannot be recorded before final validation"
                )
            self.terminal_report = deepcopy(value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": REVIEWED_STATE_VERSION,
                "planning_cycles": [item.snapshot() for item in self.planning_cycles],
                "tasks": [task.snapshot() for task in self.tasks.values()],
                "final_validations": deepcopy(self.final_validations),
                "terminal_report": deepcopy(self.terminal_report),
            }

    def _task(self, task_id: str) -> ReviewedTaskState:
        clean = str(task_id or "").strip()
        task = self.tasks.get(clean)
        if task is None:
            raise ReviewedStateError(f"reviewed workflow task not found: {clean or task_id!r}")
        return task

    def _validate_result_lineage(
        self,
        task: ReviewedTaskState,
        value: dict[str, Any],
    ) -> None:
        plan_id = _require_text(value, "plan_id")
        result_task_id = _require_text(value, "task_id")
        if plan_id != task.plan_id or result_task_id != task.task_id:
            raise ReviewedStateError(
                f"lineage mismatch for task {task.task_id}: got {plan_id}/{result_task_id}"
            )

    def _require_new_worker_attempt(
        self,
        task: ReviewedTaskState,
        attempt: int,
    ) -> None:
        if not task.worker_attempts:
            return
        previous = _require_positive_int(task.worker_attempts[-1], "attempt")
        if attempt <= previous:
            raise ReviewedStateError(
                f"task {task.task_id} worker attempt must increase beyond {previous}"
            )

    def _transition(self, task: ReviewedTaskState, next_status: str) -> None:
        if next_status not in TASK_STATUSES:
            raise ReviewedStateError(f"unknown reviewed task status: {next_status}")
        if next_status not in _ALLOWED_TRANSITIONS[task.status]:
            self._illegal_transition(task, next_status)
        task.status = next_status

    @staticmethod
    def _illegal_transition(task: ReviewedTaskState, next_status: str) -> None:
        raise ReviewedStateError(
            f"illegal reviewed task transition for {task.task_id}: {task.status} -> {next_status}"
        )


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewedStateError(f"{label} must be an object")
    return value


def _require_text(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    clean = str(raw or "").strip()
    if not clean:
        raise ReviewedStateError(f"{key} must be a non-empty string")
    return clean


def _require_nonnegative_int(value: dict[str, Any], key: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ReviewedStateError(f"{key} must be a non-negative integer")
    return raw


def _require_positive_int(value: dict[str, Any], key: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ReviewedStateError(f"{key} must be a positive integer")
    return raw


def _require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ReviewedStateError(f"{label} must be a list of strings")
    return [item for item in (part.strip() for part in value) if item]
