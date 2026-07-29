from __future__ import annotations

import inspect
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from hermes_dynamic_workflows.child.runner import HermesChildAgentRunner
from hermes_dynamic_workflows.child.structured_output import (
    _CURRENT_CHILD_TASK_ID,
    MAX_STRUCTURED_OUTPUT_RETRIES,
    STRUCTURED_OUTPUT_SUCCESS,
    child_task_id_scope,
    clear_expectation,
    peek_error,
    peek_result,
    register_expectation,
    structured_output_handler,
)


_ROOT = Path(__file__).resolve().parents[1]
_AGENTS = _ROOT / "hermes_dynamic_workflows" / "agents"
_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}


def _role(name: str) -> str:
    return (_AGENTS / f"{name}.md").read_text(encoding="utf-8").lower()


class ReviewedRoleBehaviorTests(unittest.TestCase):
    def test_worker_scope_evidence_and_stop_contract(self):
        role = _role("worker")
        self.assertIn("named paths and supplied evidence", role)
        self.assertIn("direct dependency or unresolved ambiguity", role)
        self.assertIn("every acceptance criterion and evidence requirement", role)
        self.assertIn("exact changed paths", role)
        self.assertIn("never claim an unperformed check", role)
        self.assertIn("self-approve", role)

    def test_reviewer_targeted_fail_closed_contract(self):
        role = _role("reviewer")
        self.assertIn("worker's concrete claims", role)
        self.assertIn("every acceptance criterion and reviewer guideline", role)
        self.assertIn("broad workspace audit", role)
        self.assertIn("stop once every criterion", role)
        self.assertIn("do not repair", role)
        for verdict in ("pass", "fail", "blocked"):
            self.assertIn(verdict, role)

    def test_repair_preserves_work_and_never_weakens_criteria(self):
        role = _role("repair-worker")
        self.assertIn("preserve valid prior work", role)
        self.assertIn("materially different correction", role)
        self.assertIn("rerun only the checks relevant", role)
        self.assertIn("never weaken acceptance criteria", role)
        self.assertIn("stop when every actionable finding", role)

    def test_final_validation_is_bounded_and_gap_focused(self):
        role = _role("final-orchestrator")
        self.assertIn("original objective", role)
        self.assertIn("every final criterion", role)
        self.assertIn("general workspace audit", role)
        self.assertIn("stop when every final criterion", role)
        self.assertIn("delta tasks only for concrete remaining gaps", role)
        self.assertIn("generic rediscovery", role)


class StrictStructuredOutputTests(unittest.TestCase):
    def test_text_parser_and_direct_broker_bypass_are_absent(self):
        from hermes_dynamic_workflows.child import runner

        source = inspect.getsource(HermesChildAgentRunner._run_child_with_timeout)
        self.assertFalse(hasattr(runner, "_extract_json_from_text"))
        self.assertNotIn("_BROKER.submit", source)

    def test_single_expectation_does_not_guess_missing_identity(self):
        register_expectation("only", _SCHEMA)
        try:
            out = structured_output_handler({"ok": True})
            self.assertIn("missing structured-output task identity", json.loads(out)["error"])
            captured, _value, attempts = peek_result("only")
            self.assertFalse(captured)
            self.assertEqual(attempts, 0)
        finally:
            clear_expectation("only")
        self.assertEqual(_CURRENT_CHILD_TASK_ID.get(""), "")

    def test_concurrent_context_scopes_do_not_cross_capture(self):
        register_expectation("left", _SCHEMA)
        register_expectation("right", _SCHEMA)

        def submit(task_id: str, value: bool) -> str:
            with child_task_id_scope(task_id):
                return structured_output_handler({"ok": value})

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                left = executor.submit(submit, "left", True)
                right = executor.submit(submit, "right", False)
                self.assertEqual(left.result(), STRUCTURED_OUTPUT_SUCCESS)
                self.assertEqual(right.result(), STRUCTURED_OUTPUT_SUCCESS)
            self.assertEqual(peek_result("left")[1], {"ok": True})
            self.assertEqual(peek_result("right")[1], {"ok": False})
        finally:
            clear_expectation("left")
            clear_expectation("right")
        self.assertEqual(_CURRENT_CHILD_TASK_ID.get(""), "")

    def test_invalid_payload_feedback_is_actionable_bounded_and_cleaned(self):
        register_expectation("invalid", _SCHEMA)
        try:
            for _ in range(MAX_STRUCTURED_OUTPUT_RETRIES):
                out = structured_output_handler({}, task_id="invalid")
            error = json.loads(out)["error"]
            self.assertIn("must have required property 'ok'", error)
            self.assertIn("must have required property 'ok'", peek_error("invalid"))
            self.assertEqual(peek_result("invalid")[2], MAX_STRUCTURED_OUTPUT_RETRIES)
        finally:
            clear_expectation("invalid")
        self.assertEqual(peek_error("invalid"), "")

    def test_missing_or_mismatched_expectation_is_explicit(self):
        out = structured_output_handler({"ok": True}, task_id="unknown")
        self.assertIn("no structured-output expectation is registered for task 'unknown'", json.loads(out)["error"])

    def test_tool_definition_failure_has_distinct_runner_classification(self):
        self.assertIn(
            "structured output tool definition failed",
            inspect.getsource(HermesChildAgentRunner.run),
        )


if __name__ == "__main__":
    unittest.main()
