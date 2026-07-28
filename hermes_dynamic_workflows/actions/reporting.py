"""Deterministic evidence-backed terminal reporting for reviewed workflows."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from ..contracts.packages import FINAL_REPORT_PACKAGE_SCHEMA
from ..core.errors import ReviewedStateError
from ..core.reviewed_state import TERMINAL_TASK_STATUSES
from ..core.schema import validate_schema


class TerminalReportAction:
    """Build and persist one terminal report from canonical reviewed state.

    No model authors this report. Outcome, task coverage, unresolved items, and
    evidence are derived from persisted plans, attempts, reviews, integrations,
    and final validation so fluent synthesis cannot hide failures or blockers.
    """

    def run(self, api: Any) -> dict[str, Any]:
        snapshot = api.context.state.reviewed.snapshot()
        report = build_terminal_report(snapshot)
        try:
            validate_schema(report, FINAL_REPORT_PACKAGE_SCHEMA)
        except Exception as exc:
            raise ReviewedStateError(
                f"derived terminal report did not match FinalReportPackage: {exc}"
            ) from exc

        api.context.state.reviewed.set_terminal_report(report)
        api.context.journal(
            {
                "type": "reviewed_terminal_report_recorded",
                "outcome": report["outcome"],
                "planningCycles": report["planning_cycles"],
                "taskCount": len(report["task_summaries"]),
                "unresolvedCount": len(report["unresolved"]),
                "evidenceCount": len(report["evidence"]),
            }
        )
        api.context.notify()
        return deepcopy(report)


def build_terminal_report(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Derive a schema-shaped terminal report without mutating state."""

    if not isinstance(snapshot, dict):
        raise ReviewedStateError("reviewed workflow snapshot must be an object")
    if snapshot.get("terminal_report") is not None:
        raise ReviewedStateError("terminal report is already recorded")

    cycles = snapshot.get("planning_cycles")
    if not isinstance(cycles, list) or not cycles:
        raise ReviewedStateError("terminal report requires at least one planning cycle")
    ordered_cycles = sorted(cycles, key=lambda item: int(item.get("cycle", -1)))
    _validate_cycle_lineage(ordered_cycles)
    latest_cycle = ordered_cycles[-1]
    final_validation = latest_cycle.get("final_validation")
    if not isinstance(final_validation, dict):
        raise ReviewedStateError(
            "terminal report requires final validation for the latest planning cycle"
        )

    tasks = snapshot.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ReviewedStateError("terminal report requires persisted task state")
    nonterminal = [
        str(task.get("task_id") or "<unknown>")
        for task in tasks
        if task.get("status") not in TERMINAL_TASK_STATUSES
    ]
    if nonterminal:
        raise ReviewedStateError(
            "terminal report requires every task to be terminal; still active: "
            + ", ".join(nonterminal)
        )

    objective = str(ordered_cycles[0]["original_objective"])
    latest_plan = latest_cycle.get("plan")
    if not isinstance(latest_plan, dict):
        raise ReviewedStateError("latest planning cycle is missing its PlanPackage")
    outcome = _derive_outcome(
        final_validation=final_validation,
        latest_cycle=latest_cycle,
        latest_plan=latest_plan,
        tasks=tasks,
    )
    task_summaries = [_task_summary(task) for task in tasks]
    unresolved = _collect_unresolved(
        final_validation=final_validation,
        tasks=tasks,
        outcome=outcome,
    )
    evidence = _collect_evidence(final_validation=final_validation, tasks=tasks)
    if not evidence:
        raise ReviewedStateError("terminal report has no persisted evidence")

    integrated = sum(1 for task in tasks if task.get("status") == "INTEGRATED")
    failed = sum(1 for task in tasks if task.get("status") == "FAILED")
    blocked = sum(1 for task in tasks if task.get("status") == "BLOCKED")
    summary = _report_summary(
        outcome=outcome,
        cycle_count=len(ordered_cycles),
        task_count=len(tasks),
        integrated=integrated,
        failed=failed,
        blocked=blocked,
    )
    return {
        "schema_version": "1.0",
        "original_objective": objective,
        "outcome": outcome,
        "summary": summary,
        "planning_cycles": len(ordered_cycles),
        "task_summaries": task_summaries,
        "final_validation": deepcopy(final_validation),
        "unresolved": unresolved,
        "evidence": evidence,
    }


def _validate_cycle_lineage(cycles: list[dict[str, Any]]) -> None:
    expected = 0
    objective: str | None = None
    seen_plan_ids: set[str] = set()
    for item in cycles:
        if not isinstance(item, dict):
            raise ReviewedStateError("planning cycle state must be an object")
        cycle = item.get("cycle")
        if cycle != expected:
            raise ReviewedStateError(
                f"planning cycles must be contiguous from 0; expected {expected}, got {cycle!r}"
            )
        plan_id = str(item.get("plan_id") or "").strip()
        if not plan_id or plan_id in seen_plan_ids:
            raise ReviewedStateError("planning cycles must have unique non-empty plan IDs")
        seen_plan_ids.add(plan_id)
        current_objective = str(item.get("original_objective") or "").strip()
        if not current_objective:
            raise ReviewedStateError("planning cycle is missing original_objective")
        if objective is None:
            objective = current_objective
        elif current_objective != objective:
            raise ReviewedStateError("planning cycles do not preserve one original objective")
        expected += 1


def _derive_outcome(
    *,
    final_validation: dict[str, Any],
    latest_cycle: dict[str, Any],
    latest_plan: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> str:
    verdict = final_validation.get("verdict")
    if verdict == "APPROVED":
        return "APPROVED"
    if verdict == "BLOCKED":
        return "BLOCKED"
    if verdict != "NOT_APPROVED":
        raise ReviewedStateError(f"unsupported final validation verdict: {verdict!r}")

    cycle = latest_cycle.get("cycle")
    max_cycles = latest_plan.get("max_replanning_cycles")
    if (
        isinstance(cycle, bool)
        or not isinstance(cycle, int)
        or isinstance(max_cycles, bool)
        or not isinstance(max_cycles, int)
    ):
        raise ReviewedStateError("latest plan has invalid replanning limits")
    if cycle < max_cycles:
        raise ReviewedStateError(
            "terminal report cannot be created while replanning remains available"
        )
    return "PARTIAL" if any(task.get("status") == "INTEGRATED" for task in tasks) else "FAILED"


def _task_summary(task: dict[str, Any]) -> dict[str, Any]:
    task_id = str(task.get("task_id") or "").strip()
    if not task_id:
        raise ReviewedStateError("terminal task state is missing task_id")
    status = str(task.get("status") or "")
    outcome_map = {
        "INTEGRATED": "PASS",
        "FAILED": "FAIL",
        "BLOCKED": "BLOCKED",
    }
    outcome = outcome_map.get(status)
    if outcome is None:
        raise ReviewedStateError(
            f"terminal report cannot map task {task_id} status {status!r}"
        )

    attempts = task.get("worker_attempts")
    if not isinstance(attempts, list):
        raise ReviewedStateError(f"task {task_id} worker_attempts must be a list")
    summary = _task_summary_text(task, outcome=outcome)
    return {
        "task_id": task_id,
        "outcome": outcome,
        "attempts": len(attempts),
        "summary": summary,
    }


def _task_summary_text(task: dict[str, Any], *, outcome: str) -> str:
    if outcome == "PASS":
        integration = task.get("integration")
        if isinstance(integration, dict):
            text = str(integration.get("summary") or "").strip()
            if text:
                return text
    reviews = task.get("review_verdicts")
    if isinstance(reviews, list) and reviews:
        text = str(reviews[-1].get("summary") or "").strip()
        if text:
            return text
    attempts = task.get("worker_attempts")
    if isinstance(attempts, list) and attempts:
        text = str(attempts[-1].get("summary") or "").strip()
        if text:
            return text
    return f"Task ended with {outcome}."


def _collect_unresolved(
    *,
    final_validation: dict[str, Any],
    tasks: list[dict[str, Any]],
    outcome: str,
) -> list[str]:
    unresolved: list[str] = []
    for result in final_validation.get("requirement_results") or []:
        if not isinstance(result, dict) or result.get("satisfied") is True:
            continue
        requirement = str(result.get("requirement") or "Unknown requirement").strip()
        gap = str(result.get("gap") or "Unspecified gap").strip()
        unresolved.append(f"Requirement not satisfied: {requirement} — {gap}")

    for task in tasks:
        task_id = str(task.get("task_id") or "<unknown>")
        status = task.get("status")
        if status == "FAILED":
            unresolved.append(f"Task {task_id} failed: {_task_summary_text(task, outcome='FAIL')}")
            unresolved.extend(_review_feedback(task, prefix=f"Task {task_id} feedback"))
        elif status == "BLOCKED":
            blocker = _latest_blocker(task)
            unresolved.append(
                f"Task {task_id} blocked: {blocker or _task_summary_text(task, outcome='BLOCKED')}"
            )
            unresolved.extend(_review_feedback(task, prefix=f"Task {task_id} feedback"))

    if outcome == "PARTIAL":
        unresolved.append("Replanning limit exhausted before the original objective was approved.")
    elif outcome == "FAILED":
        unresolved.append("Workflow failed after the replanning limit was exhausted.")
    return _dedupe_strings(unresolved)


def _review_feedback(task: dict[str, Any], *, prefix: str) -> list[str]:
    reviews = task.get("review_verdicts")
    if not isinstance(reviews, list) or not reviews:
        return []
    feedback = reviews[-1].get("feedback")
    if not isinstance(feedback, list):
        return []
    return [f"{prefix}: {str(item).strip()}" for item in feedback if str(item).strip()]


def _latest_blocker(task: dict[str, Any]) -> str:
    attempts = task.get("worker_attempts")
    if not isinstance(attempts, list):
        return ""
    for attempt in reversed(attempts):
        if isinstance(attempt, dict):
            blocker = str(attempt.get("blocker") or "").strip()
            if blocker:
                return blocker
    return ""


def _collect_evidence(
    *,
    final_validation: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items.extend(_evidence_items(final_validation.get("evidence")))
    for result in final_validation.get("requirement_results") or []:
        if isinstance(result, dict):
            items.extend(_evidence_items(result.get("evidence")))
    for task in tasks:
        integration = task.get("integration")
        if isinstance(integration, dict):
            items.extend(_evidence_items(integration.get("evidence")))
        reviews = task.get("review_verdicts")
        if isinstance(reviews, list) and reviews:
            items.extend(_evidence_items(reviews[-1].get("evidence")))
        attempts = task.get("worker_attempts")
        if isinstance(attempts, list) and attempts:
            items.extend(_evidence_items(attempts[-1].get("evidence")))
    return _dedupe_evidence(items)


def _evidence_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [deepcopy(item) for item in value if isinstance(item, dict)]


def _dedupe_evidence(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (
            str(item.get("kind") or ""),
            str(item.get("reference") or ""),
            str(item.get("summary") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(deepcopy(item))
    return result


def _dedupe_strings(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        clean = str(item).strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _report_summary(
    *,
    outcome: str,
    cycle_count: int,
    task_count: int,
    integrated: int,
    failed: int,
    blocked: int,
) -> str:
    return (
        f"Reviewed workflow ended {outcome} after {cycle_count} planning cycle(s): "
        f"{integrated}/{task_count} task(s) integrated, {failed} failed, {blocked} blocked."
    )
