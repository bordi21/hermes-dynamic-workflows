"""JSON Schemas for every handoff in the canonical reviewed workflow.

These schemas are deliberately provider-neutral and use the same Draft 2020-12
validation path already used by ``agent(..., {"schema": ...})``.  They describe
transport contracts only; orchestration policy and state transitions remain in
Actions/runtime code.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

SCHEMA_VERSION = "1.0"
DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _string(*, nullable: bool = False) -> dict[str, Any]:
    return {"type": ["string", "null"] if nullable else "string", "minLength": 1}


def _strings() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _embedded(schema: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(schema)
    value.pop("$schema", None)
    return value


EVIDENCE_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "reference"],
    "properties": {
        "kind": {"type": "string", "enum": ["file", "diff", "test", "command", "transcript", "state", "other"]},
        "reference": _string(),
        "summary": {"type": "string"},
    },
}

TEST_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "status"],
    "properties": {
        "name": _string(),
        "status": {"type": "string", "enum": ["PASS", "FAIL", "SKIPPED", "NOT_RUN"]},
        "details": {"type": "string"},
    },
}

TASK_PACKAGE_SCHEMA = {
    "$schema": DRAFT,
    "title": "TaskPackage",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "plan_id",
        "task_id",
        "objective",
        "depends_on",
        "paths",
        "constraints",
        "allowed_mutations",
        "acceptance_criteria",
        "evidence_requirements",
        "worker_instructions",
        "reviewer_guidelines",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "plan_id": _string(),
        "task_id": _string(),
        "objective": _string(),
        "depends_on": _strings(),
        "paths": _strings(),
        "constraints": _strings(),
        "allowed_mutations": _strings(),
        "acceptance_criteria": {"type": "array", "minItems": 1, "items": _string()},
        "evidence_requirements": {"type": "array", "minItems": 1, "items": _string()},
        "worker_instructions": _string(),
        "reviewer_guidelines": {"type": "array", "minItems": 1, "items": _string()},
    },
}

PLAN_PACKAGE_SCHEMA = {
    "$schema": DRAFT,
    "title": "PlanPackage",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "plan_id",
        "cycle",
        "original_objective",
        "tasks",
        "final_validation_criteria",
        "max_repairs_per_task",
        "max_replanning_cycles",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "plan_id": _string(),
        "cycle": {"type": "integer", "minimum": 0},
        "original_objective": _string(),
        "tasks": {"type": "array", "minItems": 1, "items": _embedded(TASK_PACKAGE_SCHEMA)},
        "final_validation_criteria": {"type": "array", "minItems": 1, "items": _string()},
        "max_repairs_per_task": {"type": "integer", "minimum": 0},
        "max_replanning_cycles": {"type": "integer", "minimum": 0},
    },
}

WORKER_RESULT_PACKAGE_SCHEMA = {
    "$schema": DRAFT,
    "title": "WorkerResultPackage",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "plan_id",
        "task_id",
        "attempt",
        "status",
        "summary",
        "changed_paths",
        "evidence",
        "tests",
        "blocker",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "plan_id": _string(),
        "task_id": _string(),
        "attempt": {"type": "integer", "minimum": 1},
        "status": {"type": "string", "enum": ["COMPLETED", "FAILED", "BLOCKED"]},
        "summary": _string(),
        "changed_paths": _strings(),
        "evidence": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
        "tests": {"type": "array", "items": TEST_RESULT_SCHEMA},
        "blocker": {"type": ["string", "null"]},
    },
}

REVIEW_REQUEST_PACKAGE_SCHEMA = {
    "$schema": DRAFT,
    "title": "ReviewRequestPackage",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "plan_id", "task_id", "original_objective", "task", "worker_result"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "plan_id": _string(),
        "task_id": _string(),
        "original_objective": _string(),
        "task": _embedded(TASK_PACKAGE_SCHEMA),
        "worker_result": _embedded(WORKER_RESULT_PACKAGE_SCHEMA),
    },
}

CRITERION_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["criterion", "passed", "evidence", "feedback"],
    "properties": {
        "criterion": _string(),
        "passed": {"type": "boolean"},
        "evidence": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
        "feedback": {"type": "string"},
    },
}

REVIEW_VERDICT_PACKAGE_SCHEMA = {
    "$schema": DRAFT,
    "title": "ReviewVerdictPackage",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "plan_id",
        "task_id",
        "attempt",
        "verdict",
        "summary",
        "criteria_results",
        "feedback",
        "evidence",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "plan_id": _string(),
        "task_id": _string(),
        "attempt": {"type": "integer", "minimum": 1},
        "verdict": {"type": "string", "enum": ["PASS", "FAIL", "BLOCKED"]},
        "summary": _string(),
        "criteria_results": {"type": "array", "minItems": 1, "items": CRITERION_RESULT_SCHEMA},
        "feedback": {"type": "array", "items": _string()},
        "evidence": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
    },
}

REPAIR_PACKAGE_SCHEMA = {
    "$schema": DRAFT,
    "title": "RepairPackage",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "plan_id",
        "task_id",
        "repair_attempt",
        "original_task",
        "previous_result",
        "review_verdict",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "plan_id": _string(),
        "task_id": _string(),
        "repair_attempt": {"type": "integer", "minimum": 1},
        "original_task": _embedded(TASK_PACKAGE_SCHEMA),
        "previous_result": _embedded(WORKER_RESULT_PACKAGE_SCHEMA),
        "review_verdict": _embedded(REVIEW_VERDICT_PACKAGE_SCHEMA),
    },
}

INTEGRATION_RESULT_PACKAGE_SCHEMA = {
    "$schema": DRAFT,
    "title": "IntegrationResultPackage",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "plan_id", "task_id", "status", "summary", "integrated_commit", "evidence"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "plan_id": _string(),
        "task_id": _string(),
        "status": {"type": "string", "enum": ["INTEGRATED", "CONFLICT", "SKIPPED", "FAILED"]},
        "summary": _string(),
        "integrated_commit": {"type": ["string", "null"]},
        "evidence": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
    },
}

REQUIREMENT_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["requirement", "satisfied", "evidence", "gap"],
    "properties": {
        "requirement": _string(),
        "satisfied": {"type": "boolean"},
        "evidence": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
        "gap": {"type": "string"},
    },
}

FINAL_VALIDATION_PACKAGE_SCHEMA = {
    "$schema": DRAFT,
    "title": "FinalValidationPackage",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "plan_id",
        "cycle",
        "verdict",
        "summary",
        "requirement_results",
        "delta_tasks",
        "evidence",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "plan_id": _string(),
        "cycle": {"type": "integer", "minimum": 0},
        "verdict": {"type": "string", "enum": ["APPROVED", "NOT_APPROVED", "BLOCKED"]},
        "summary": _string(),
        "requirement_results": {"type": "array", "minItems": 1, "items": REQUIREMENT_RESULT_SCHEMA},
        "delta_tasks": {"type": "array", "items": _embedded(TASK_PACKAGE_SCHEMA)},
        "evidence": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
    },
}

FINAL_REPORT_PACKAGE_SCHEMA = {
    "$schema": DRAFT,
    "title": "FinalReportPackage",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "original_objective",
        "outcome",
        "summary",
        "planning_cycles",
        "task_summaries",
        "final_validation",
        "unresolved",
        "evidence",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "original_objective": _string(),
        "outcome": {"type": "string", "enum": ["APPROVED", "FAILED", "BLOCKED", "PARTIAL"]},
        "summary": _string(),
        "planning_cycles": {"type": "integer", "minimum": 1},
        "task_summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["task_id", "outcome", "attempts", "summary"],
                "properties": {
                    "task_id": _string(),
                    "outcome": {"type": "string", "enum": ["PASS", "FAIL", "BLOCKED", "SKIPPED"]},
                    "attempts": {"type": "integer", "minimum": 0},
                    "summary": _string(),
                },
            },
        },
        "final_validation": _embedded(FINAL_VALIDATION_PACKAGE_SCHEMA),
        "unresolved": _strings(),
        "evidence": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
    },
}

PACKAGE_SCHEMAS = {
    "plan": PLAN_PACKAGE_SCHEMA,
    "task": TASK_PACKAGE_SCHEMA,
    "worker_result": WORKER_RESULT_PACKAGE_SCHEMA,
    "review_request": REVIEW_REQUEST_PACKAGE_SCHEMA,
    "review_verdict": REVIEW_VERDICT_PACKAGE_SCHEMA,
    "repair": REPAIR_PACKAGE_SCHEMA,
    "integration_result": INTEGRATION_RESULT_PACKAGE_SCHEMA,
    "final_validation": FINAL_VALIDATION_PACKAGE_SCHEMA,
    "final_report": FINAL_REPORT_PACKAGE_SCHEMA,
}
