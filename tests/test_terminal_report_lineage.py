from __future__ import annotations

import unittest

from hermes_dynamic_workflows.actions.reporting import build_terminal_report
from hermes_dynamic_workflows.core.errors import ReviewedStateError


class TerminalReportLineageTests(unittest.TestCase):
    def test_noncontiguous_planning_cycles_are_rejected(self):
        snapshot = {
            "planning_cycles": [
                {
                    "plan_id": "plan-1",
                    "cycle": 1,
                    "original_objective": "Objective.",
                    "plan": {"max_replanning_cycles": 1},
                    "final_validation": {"verdict": "APPROVED"},
                }
            ],
            "tasks": [],
            "final_validations": [],
            "terminal_report": None,
        }

        with self.assertRaisesRegex(ReviewedStateError, "contiguous from 0"):
            build_terminal_report(snapshot)


if __name__ == "__main__":
    unittest.main()
