from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from hermes_dynamic_workflows.core.config import PluginConfig
from hermes_dynamic_workflows.core.errors import WorkflowRuntimeError
from hermes_dynamic_workflows.core.types import ChildAgentRequest, ChildAgentRunner
from hermes_dynamic_workflows.engine.runtime import WorkflowOptions, run_workflow
from hermes_dynamic_workflows.storage.store import WorkflowStore, resolve_workflow_source


OBJECTIVE = "Deliver the feature through the canonical reviewed lifecycle."


class _NoChildRunner(ChildAgentRunner):
    def __init__(self):
        self.requests: list[ChildAgentRequest] = []

    def run(self, request: ChildAgentRequest):
        self.requests.append(request)
        raise AssertionError("entrypoint test must not launch a child agent")


class ReviewedWorkflowEntrypointTests(unittest.TestCase):
    def test_store_resolves_packaged_reviewed_workflow_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp))
            source = resolve_workflow_source(
                {"name": "reviewed-workflow"},
                store=store,
                cwd=tmp,
            )

        self.assertEqual(source.source_type, "name")
        self.assertEqual(source.source_ref, "reviewed-workflow")
        self.assertIn('"name": "reviewed-workflow"', source.script)
        self.assertIn("return await reviewed_workflow(args)", source.script)
        self.assertTrue(source.saved_script_path.endswith("workflows/reviewed-workflow.py"))

    def test_packaged_script_runs_through_runtime_primitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp))
            source = resolve_workflow_source(
                {"name": "reviewed-workflow"},
                store=store,
                cwd=tmp,
            )
            runner = _NoChildRunner()
            expected = {
                "schema_version": "1.0",
                "original_objective": OBJECTIVE,
                "outcome": "APPROVED",
            }
            run_mock = AsyncMock(return_value=expected)
            with patch(
                "hermes_dynamic_workflows.actions.workflow.ReviewedWorkflowAction"
            ) as action_class:
                action_class.return_value.run = run_mock
                result = run_workflow(
                    source.script,
                    WorkflowOptions(
                        args={"objective": OBJECTIVE},
                        cwd=tmp,
                        config=PluginConfig(),
                        child_runner=runner,
                        source_ref=source.source_ref,
                        store=store,
                    ),
                )

        self.assertEqual(result.value, expected)
        self.assertEqual(runner.requests, [])
        run_mock.assert_awaited_once()
        self.assertEqual(run_mock.await_args.kwargs["original_objective"], OBJECTIVE)
        snapshot = result.state.snapshot()
        self.assertEqual(snapshot["meta"]["name"], "reviewed-workflow")
        self.assertEqual(
            [item["title"] for item in snapshot["phases"]],
            ["Planning", "Execution", "Review", "Repair", "Final Validation", "Reporting"],
        )

    def test_runtime_primitive_accepts_one_objective_shape_only(self):
        script = (
            'meta = {"name": "entry", "description": "entry"}\n'
            "return await reviewed_workflow(args)"
        )
        runner = _NoChildRunner()
        run_mock = AsyncMock(return_value={"original_objective": OBJECTIVE, "outcome": "APPROVED"})
        with patch(
            "hermes_dynamic_workflows.actions.workflow.ReviewedWorkflowAction"
        ) as action_class:
            action_class.return_value.run = run_mock
            result = run_workflow(
                script,
                WorkflowOptions(
                    args={"original_objective": OBJECTIVE},
                    config=PluginConfig(),
                    child_runner=runner,
                ),
            )
        self.assertEqual(result.value["outcome"], "APPROVED")
        self.assertEqual(run_mock.await_args.kwargs["original_objective"], OBJECTIVE)

        for invalid in (
            None,
            "   ",
            {},
            {"objective": OBJECTIVE, "extra": True},
            {"objective": OBJECTIVE, "original_objective": OBJECTIVE},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(WorkflowRuntimeError):
                    run_workflow(
                        script,
                        WorkflowOptions(
                            args=invalid,
                            config=PluginConfig(),
                            child_runner=_NoChildRunner(),
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
