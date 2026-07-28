from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "hermes_dynamic_workflows" / "contracts" / "packages.py"
TESTS = ROOT / "tests" / "test_workflow_contracts.py"
REPORT = ROOT / "FOUNDATION_BASELINE.md"

old_evidence = '{"type": "array", "items": EVIDENCE_ITEM_SCHEMA}'
new_evidence = '{"type": "array", "minItems": 1, "items": EVIDENCE_ITEM_SCHEMA}'

packages = PACKAGES.read_text(encoding="utf-8")
count = packages.count(old_evidence)
if count != 7:
    raise RuntimeError(f"expected 7 evidence array schemas, found {count}")
PACKAGES.write_text(packages.replace(old_evidence, new_evidence), encoding="utf-8")

marker = '''    def test_repair_packet_carries_original_task_previous_result_and_feedback(self):
'''
addition = '''    def test_evidence_backed_verdict_rejects_empty_evidence(self):
        verdict = valid_review_verdict()
        verdict["evidence"] = []
        with self.assertRaises(StructuredOutputError):
            validate_schema(verdict, REVIEW_VERDICT_PACKAGE_SCHEMA)

        verdict = valid_review_verdict()
        verdict["criteria_results"][0]["evidence"] = []
        with self.assertRaises(StructuredOutputError):
            validate_schema(verdict, REVIEW_VERDICT_PACKAGE_SCHEMA)

'''
tests = TESTS.read_text(encoding="utf-8")
if addition not in tests:
    if tests.count(marker) != 1:
        raise RuntimeError("could not locate workflow contract test insertion point")
    TESTS.write_text(tests.replace(marker, addition + marker, 1), encoding="utf-8")

report = REPORT.read_text(encoding="utf-8")
report = report.replace("Post-change suite: `PASS` — 247 tests", "Post-change suite: `PASS` — 248 tests")
needle = "The schemas use the plugin's existing structured-output validation path. Tests require planner-authored reviewer guidelines, strict `PASS`/`FAIL`/`BLOCKED` verdicts, and repair lineage containing the original task, previous result, and reviewer feedback."
replacement = needle + " Evidence-backed results and verdicts require at least one concrete evidence item; empty evidence arrays are rejected."
if replacement not in report:
    if needle not in report:
        raise RuntimeError("could not locate foundation report schema paragraph")
    report = report.replace(needle, replacement, 1)
REPORT.write_text(report, encoding="utf-8")
