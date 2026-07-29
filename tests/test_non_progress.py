from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import patch

from hermes_dynamic_workflows.adapters.hooks import (
    pre_tool_call_handler,
    register_child_observer,
    unregister_child_observer,
)
from hermes_dynamic_workflows.child.non_progress import NonProgressCircuitBreaker
from hermes_dynamic_workflows.child.runner import HermesChildAgentRunner, build_child_system_prompt
from hermes_dynamic_workflows.child.worktree import WorkspaceLease
from hermes_dynamic_workflows.core.config import PluginConfig, load_config
from hermes_dynamic_workflows.core.errors import ChildAgentError
from hermes_dynamic_workflows.core.types import ChildAgentRequest


class NonProgressCircuitBreakerTests(unittest.TestCase):
    def test_repeated_equivalent_read_warns_then_stops(self):
        breaker = NonProgressCircuitBreaker(warning_repeats=2, stop_repeats=3)
        self.assertIsNone(breaker.observe_tool("read_file", {"path": "README.md"}))
        warning = breaker.observe_tool("read_file", {"path": "README.md"})
        stopped = breaker.observe_tool("read_file", {"path": "README.md"})

        self.assertEqual(warning.level, "warning")
        self.assertEqual(warning.repetitions, 2)
        self.assertEqual(stopped.level, "stop")
        self.assertEqual(stopped.repetitions, 3)
        self.assertEqual(warning.signature, stopped.signature)

    def test_distinct_multistep_reads_are_not_stopped(self):
        breaker = NonProgressCircuitBreaker(warning_repeats=2, stop_repeats=3)
        for path in ("README.md", "TECHNICAL.md", "WORKFLOW_CONTRACT.md", "README.md"):
            self.assertIsNone(breaker.observe_tool("read_file", {"path": path}))

    def test_mutating_or_materially_different_activity_resets_signature(self):
        breaker = NonProgressCircuitBreaker(warning_repeats=2, stop_repeats=3)
        breaker.observe_tool("search_files", {"query": "packet"})
        self.assertEqual(
            breaker.observe_tool("search_files", {"query": "packet"}).level,
            "warning",
        )
        self.assertIsNone(breaker.observe_tool("write_file", {"path": "x"}))
        self.assertIsNone(breaker.observe_tool("search_files", {"query": "packet"}))

    def test_repeated_invalid_structured_submissions_are_detected(self):
        breaker = NonProgressCircuitBreaker(warning_repeats=2, stop_repeats=3)
        self.assertIsNone(breaker.observe_invalid_submission("missing required field: ok"))
        self.assertEqual(
            breaker.observe_invalid_submission("missing required field: ok").level,
            "warning",
        )
        self.assertEqual(
            breaker.observe_invalid_submission("missing required field: ok").level,
            "stop",
        )


class HookAndRunnerIntegrationTests(unittest.TestCase):
    def test_pre_tool_hook_propagates_observer_block_directive(self):
        task_id = "workflow-non-progress-hook"
        register_child_observer(
            task_id,
            lambda _event: {"action": "block", "message": "complete now"},
        )
        try:
            directive = pre_tool_call_handler(
                tool_name="read_file",
                args={"path": "README.md"},
                task_id=task_id,
            )
        finally:
            unregister_child_observer(task_id)
        self.assertEqual(directive, {"action": "block", "message": "complete now"})

    def test_runner_warns_then_fails_closed_with_telemetry(self):
        updates = []

        class Child:
            session_prompt_tokens = 0
            session_completion_tokens = 0
            session_reasoning_tokens = 0
            session_cache_read_tokens = 0
            session_cache_write_tokens = 0
            model = "test"

            def __init__(self):
                self.interrupted = False
                self.directives = []

            def interrupt(self):
                self.interrupted = True

            def run_conversation(self, *, task_id=None, **_):
                for _index in range(3):
                    self.directives.append(
                        pre_tool_call_handler(
                            tool_name="read_file",
                            args={"path": "README.md"},
                            task_id=task_id,
                        )
                    )
                return {"final_response": "", "messages": [], "completed": True}

        child = Child()
        request = ChildAgentRequest(
            id=1,
            prompt="Read README.md.",
            label="loop-test",
            phase=None,
            toolsets=[],
            on_update=updates.append,
        )
        lease = WorkspaceLease(task_id="workflow-non-progress-runner", cwd="/tmp")
        config = PluginConfig(
            non_progress_warning_repeats=2,
            non_progress_stop_repeats=3,
        )
        runner = HermesChildAgentRunner(config)

        with self.assertRaisesRegex(ChildAgentError, "Non-progress circuit breaker"):
            runner._run_child_with_timeout(child, request, lease, None, [])

        self.assertTrue(child.interrupted)
        self.assertEqual(child.directives[0], None)
        self.assertEqual(child.directives[1]["action"], "block")
        self.assertEqual(child.directives[2]["action"], "block")
        levels = [
            item["non_progress"]["latest"]["level"]
            for item in updates
            if "non_progress" in item
        ]
        self.assertIn("warning", levels)
        self.assertIn("stop", levels)
        self.assertTrue(
            all(len(item["non_progress"]["latest"]["signature"]) == 20 for item in updates if "non_progress" in item)
        )

    def test_generic_child_prompt_contains_periodic_self_check(self):
        prompt = build_child_system_prompt().lower()
        self.assertIn("already have enough information", prompt)
        self.assertIn("do not repeat equivalent activity", prompt)


class NonProgressConfigTests(unittest.TestCase):
    def test_defaults_are_staged_and_not_a_global_tool_budget(self):
        config = PluginConfig()
        self.assertTrue(config.non_progress_detection_enabled)
        self.assertGreaterEqual(config.non_progress_warning_repeats, 2)
        self.assertGreater(config.non_progress_stop_repeats, config.non_progress_warning_repeats)

    def test_environment_overrides_are_loaded_and_stop_exceeds_warning(self):
        with patch.dict(
            os.environ,
            {
                "HERMES_DYNAMIC_WORKFLOWS_NON_PROGRESS_DETECTION_ENABLED": "0",
                "HERMES_DYNAMIC_WORKFLOWS_NON_PROGRESS_WARNING_REPEATS": "7",
                "HERMES_DYNAMIC_WORKFLOWS_NON_PROGRESS_STOP_REPEATS": "5",
            },
            clear=False,
        ):
            config = load_config()
        self.assertFalse(config.non_progress_detection_enabled)
        self.assertEqual(config.non_progress_warning_repeats, 7)
        self.assertEqual(config.non_progress_stop_repeats, 8)


if __name__ == "__main__":
    unittest.main()
