from __future__ import annotations

import unittest

from hermes_execution_supervisor.controller import IncidentController, Intervention
from hermes_execution_supervisor.supervisor import ExecutionSupervisor


class _UnavailableJudge:
    available = False


class ExecutionSupervisorTests(unittest.TestCase):
    def test_third_confirmed_incident_stops_without_restart(self) -> None:
        controller = IncidentController()
        first = controller.confirm("agent-1", reason="loop", evidence=("one",))
        second = controller.confirm("agent-1", reason="drift", evidence=("two",))
        third = controller.confirm("agent-1", reason="no progress", evidence=("three",))

        self.assertEqual(first.intervention, Intervention.CORRECT)
        self.assertEqual(second.intervention, Intervention.CORRECT)
        self.assertEqual(third.intervention, Intervention.STOP)
        self.assertTrue(controller.state("agent-1").stopped)
        self.assertIsNone(controller.state("agent-1").pending_feedback)

    def test_repeated_tool_calls_are_confirmed_deterministically(self) -> None:
        controller = IncidentController(repeat_threshold=3)
        args = {"path": "README.md"}
        self.assertIsNone(controller.observe_tool("agent-1", "read_file", args))
        self.assertIsNone(controller.observe_tool("agent-1", "read_file", args))
        incident = controller.observe_tool("agent-1", "read_file", args)
        self.assertIsNotNone(incident)
        self.assertEqual(incident.intervention, Intervention.CORRECT)

    def test_stopped_agent_blocks_every_next_tool_boundary(self) -> None:
        controller = IncidentController()
        supervisor = ExecutionSupervisor(controller=controller, judge=_UnavailableJudge())
        for reason in ("one", "two", "three"):
            controller.confirm("task-1", reason=reason, evidence=(reason,))

        result = supervisor.pre_tool_call("terminal", {"command": "echo retry"}, task_id="task-1")
        self.assertEqual(result["action"], "block")
        self.assertIn("Do not restart or replace", result["message"])


if __name__ == "__main__":
    unittest.main()
