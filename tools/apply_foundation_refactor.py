from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "1.0"


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def apply_refactor() -> None:
    runner = ROOT / "hermes_dynamic_workflows" / "child" / "runner.py"
    _replace_once(
        runner,
        '            "skip_context_files": True,\n            "skip_memory": True,\n',
        '            # Workflow children are fresh sessions of the launching Hermes profile.\n'
        '            # They inherit SOUL/project context and profile memory; only the\n'
        '            # task transcript remains isolated and is supplied below as a\n'
        '            # scoped first user message.\n'
        '            "skip_context_files": False,\n'
        '            "skip_memory": False,\n',
    )

    config = ROOT / "hermes_dynamic_workflows" / "core" / "config.py"
    _replace_once(config, '        "memory",\n', "")

    child_tests = ROOT / "tests" / "test_child_agents.py"
    _replace_once(
        child_tests,
        '        self.assertIsNone(seen_kwargs["thinking_callback"]("pondering..."))\n',
        '        self.assertIsNone(seen_kwargs["thinking_callback"]("pondering..."))\n'
        '        self.assertFalse(seen_kwargs["skip_context_files"])\n'
        '        self.assertFalse(seen_kwargs["skip_memory"])\n'
        '        self.assertNotIn("memory", PluginConfig().blocked_child_toolsets)\n',
    )

    _write_contract_package()
    _write_contract_tests()
    _append_technical_status()


def _schema_header(title: str) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": title,
        "type": "object",
        "additionalProperties": False,
    }


def _write_contract_package() -> None:
    init_path = ROOT / "hermes_dynamic_workflows" / "contracts" / "__init__.py"
    _write(
        init_path,
        '''"""Canonical structured handoff contracts for reviewed workflows."""

from .packages import (
    FINAL_REPORT_PACKAGE_SCHEMA,
    FINAL_VALIDATION_PACKAGE_SCHEMA,
    INTEGRATION_RESULT_PACKAGE_SCHEMA,
    PACKAGE_SCHEMAS,
    PLAN_PACKAGE_SCHEMA,
    REPAIR_PACKAGE_SCHEMA,
    REVIEW_REQUEST_PACKAGE_SCHEMA,
    REVIEW_VERDICT_PACKAGE_SCHEMA,
    TASK_PACKAGE_SCHEMA,
    WORKER_RESULT_PACKAGE_SCHEMA,
)

__all__ = [
    "PLAN_PACKAGE_SCHEMA",
    "TASK_PACKAGE_SCHEMA",
    "WORKER_RESULT_PACKAGE_SCHEMA",
    "REVIEW_REQUEST_PACKAGE_SCHEMA",
    "REVIEW_VERDICT_PACKAGE_SCHEMA",
    "REPAIR_PACKAGE_SCHEMA",
    "INTEGRATION_RESULT_PACKAGE_SCHEMA",
    "FINAL_VALIDATION_PACKAGE_SCHEMA",
    "FINAL_REPORT_PACKAGE_SCHEMA",
    "PACKAGE_SCHEMAS",
]
''',
    )

    packages_path = ROOT / "hermes_dynamic_workflows" / "contracts" / "packages.py"
    _write(
        packages_path,
        '''"""JSON Schemas for every handoff in the canonical reviewed workflow.

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
''',
    )


def _write_contract_tests() -> None:
    path = ROOT / "tests" / "test_workflow_contracts.py"
    _write(
        path,
        '''from __future__ import annotations

import unittest

from hermes_dynamic_workflows.contracts import (
    PACKAGE_SCHEMAS,
    PLAN_PACKAGE_SCHEMA,
    REPAIR_PACKAGE_SCHEMA,
    REVIEW_VERDICT_PACKAGE_SCHEMA,
)
from hermes_dynamic_workflows.core.schema import StructuredOutputError, validate_json_schema, validate_schema


def valid_task() -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": "task-1",
        "objective": "Implement one bounded change.",
        "depends_on": [],
        "paths": ["src/example.py"],
        "constraints": ["Preserve existing APIs."],
        "allowed_mutations": ["src/example.py"],
        "acceptance_criteria": ["The requested behavior is implemented."],
        "evidence_requirements": ["Provide the focused test result."],
        "worker_instructions": "Implement only the scoped objective.",
        "reviewer_guidelines": ["Verify the acceptance criterion against evidence."],
    }


def valid_worker_result() -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": "task-1",
        "attempt": 1,
        "status": "COMPLETED",
        "summary": "Implemented the scoped change.",
        "changed_paths": ["src/example.py"],
        "evidence": [{"kind": "test", "reference": "python -m unittest", "summary": "passed"}],
        "tests": [{"name": "focused", "status": "PASS", "details": "ok"}],
        "blocker": None,
    }


def valid_review_verdict() -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "plan-1",
        "task_id": "task-1",
        "attempt": 1,
        "verdict": "PASS",
        "summary": "All criteria passed.",
        "criteria_results": [
            {
                "criterion": "The requested behavior is implemented.",
                "passed": True,
                "evidence": [{"kind": "test", "reference": "focused"}],
                "feedback": "",
            }
        ],
        "feedback": [],
        "evidence": [{"kind": "diff", "reference": "task-1.diff"}],
    }


class WorkflowContractSchemaTests(unittest.TestCase):
    def test_every_canonical_package_is_a_valid_json_schema(self):
        self.assertEqual(len(PACKAGE_SCHEMAS), 9)
        for name, schema in PACKAGE_SCHEMAS.items():
            with self.subTest(name=name):
                validate_json_schema(schema)

    def test_plan_requires_planner_authored_reviewer_guidelines(self):
        plan = {
            "schema_version": "1.0",
            "plan_id": "plan-1",
            "cycle": 0,
            "original_objective": "Complete the requested change.",
            "tasks": [valid_task()],
            "final_validation_criteria": ["All original requirements are satisfied."],
            "max_repairs_per_task": 2,
            "max_replanning_cycles": 2,
        }
        validate_schema(plan, PLAN_PACKAGE_SCHEMA)
        del plan["tasks"][0]["reviewer_guidelines"]
        with self.assertRaises(StructuredOutputError):
            validate_schema(plan, PLAN_PACKAGE_SCHEMA)

    def test_review_verdict_is_fail_closed_to_three_values(self):
        verdict = valid_review_verdict()
        validate_schema(verdict, REVIEW_VERDICT_PACKAGE_SCHEMA)
        verdict["verdict"] = "MAYBE"
        with self.assertRaises(StructuredOutputError):
            validate_schema(verdict, REVIEW_VERDICT_PACKAGE_SCHEMA)

    def test_repair_packet_carries_original_task_previous_result_and_feedback(self):
        repair = {
            "schema_version": "1.0",
            "plan_id": "plan-1",
            "task_id": "task-1",
            "repair_attempt": 1,
            "original_task": valid_task(),
            "previous_result": valid_worker_result(),
            "review_verdict": {**valid_review_verdict(), "verdict": "FAIL", "feedback": ["Fix the defect."]},
        }
        validate_schema(repair, REPAIR_PACKAGE_SCHEMA)
        del repair["previous_result"]
        with self.assertRaises(StructuredOutputError):
            validate_schema(repair, REPAIR_PACKAGE_SCHEMA)


if __name__ == "__main__":
    unittest.main()
''',
    )


def _append_technical_status() -> None:
    path = ROOT / "TECHNICAL.md"
    marker = "## Foundation implementation status (T00-T02)"
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    text += (
        "\n\n" + marker + "\n\n"
        "The first reviewed-workflow foundation slice is implemented as follows:\n\n"
        "- workflow child `AIAgent` sessions load the launching Hermes profile context files and memory;\n"
        "- task-specific context remains isolated in the child session's scoped first user message;\n"
        "- the memory toolset is no longer globally blocked for workflow children, while recursive workflow/delegation surfaces remain blocked;\n"
        "- nine canonical Draft 2020-12 handoff schemas define planner, worker, reviewer, repair, integration, final-validation, and final-report transport.\n\n"
        "This slice does not yet implement the orchestration FSM, repair loop, PASS-only integration, or final replanning. "
        "Those remain subsequent tasks. Live Hermes canary verification is separate from the repository unit-test baseline.\n"
    )
    path.write_text(text, encoding="utf-8")


def _test_count(log_path: Path) -> str:
    if not log_path.exists():
        return "unknown"
    match = re.search(r"Ran (\d+) tests?", log_path.read_text(encoding="utf-8", errors="replace"))
    return match.group(1) if match else "unknown"


def _git_output(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def write_report(args: argparse.Namespace) -> None:
    tracked = _git_output("ls-files").splitlines()
    package_files = [item for item in tracked if item.startswith("hermes_dynamic_workflows/")]
    test_files = [item for item in tracked if item.startswith("tests/") and item.endswith(".py")]
    report = f'''# Foundation Baseline — T00 to T02

- Base commit: `{args.base_commit}`
- Branch: `refactor/t00-t02-foundation`
- Python: `3.11`
- Baseline command: `python -m unittest discover -s tests -v`
- Baseline status: `{"PASS" if args.baseline_status == 0 else "FAIL"}`
- Baseline tests discovered: `{_test_count(Path(args.baseline_log))}`
- Post-change status: `{"PASS" if args.final_status == 0 else "FAIL"}`
- Post-change tests discovered: `{_test_count(Path(args.final_log))}`
- Tracked package files at verification: `{len(package_files)}`
- Tracked test modules at verification: `{len(test_files)}`

## T00 — Executable baseline

The pre-change suite was executed before functional edits. A non-zero baseline stops the one-shot refactor and prevents a success commit, so pre-existing failures cannot be silently relabeled as regressions or successes.

## T01 — Hermes profile inheritance

Workflow children now instantiate fresh `AIAgent` sessions with context files and memory enabled. The generic role prompt remains an additive ephemeral prompt, while the child receives only the scoped workflow task as its first user message. The default blocked-toolset list no longer blocks `memory`.

Repository tests verify the actual constructor arguments. This is code-level evidence, not a live Hermes end-to-end canary; the latter still requires an installed-profile smoke test.

## T02 — Structured package schemas

Nine canonical package schemas are present and validated through the existing Draft 2020-12 validation path. Tests verify schema validity, mandatory planner-authored reviewer guidelines, strict review verdicts, and repair lineage.

## Verification boundary

This report proves repository behavior under GitHub Actions. It does not claim that the plugin has already been installed on the VPS or that a live Hermes profile has passed SOUL/memory canary verification.
'''
    _write(ROOT / "docs" / "FOUNDATION_BASELINE.md", report)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("apply")
    report = sub.add_parser("report")
    report.add_argument("--base-commit", required=True)
    report.add_argument("--baseline-log", required=True)
    report.add_argument("--baseline-status", type=int, required=True)
    report.add_argument("--final-log", required=True)
    report.add_argument("--final-status", type=int, required=True)
    args = parser.parse_args()
    if args.command == "apply":
        apply_refactor()
    else:
        write_report(args)


if __name__ == "__main__":
    main()
