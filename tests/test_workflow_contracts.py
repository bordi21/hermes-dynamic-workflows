from __future__ import annotations

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
