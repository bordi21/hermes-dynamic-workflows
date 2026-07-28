from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_dynamic_workflows.child.presets import list_agent_types, resolve_agent_type
from hermes_dynamic_workflows.core.config import PluginConfig, load_config
from hermes_dynamic_workflows.engine.api import _resolve_agent_spec


class RoleConfigTests(unittest.TestCase):
    def test_role_defaults_are_provider_neutral_and_inherited(self):
        config = PluginConfig()

        self.assertEqual(config.initial_orchestrator_model, "inherit")
        self.assertEqual(config.worker_model, "inherit")
        self.assertEqual(config.reviewer_model, "inherit")
        self.assertEqual(config.repair_worker_model, "inherit")
        self.assertEqual(config.final_orchestrator_model, "inherit")
        self.assertEqual(config.initial_orchestrator_agent_type, "initial-orchestrator")
        self.assertEqual(config.worker_agent_type, "worker")
        self.assertEqual(config.reviewer_agent_type, "reviewer")
        self.assertEqual(config.repair_worker_agent_type, "repair-worker")
        self.assertEqual(config.final_orchestrator_agent_type, "final-orchestrator")

    def test_role_settings_load_from_environment(self):
        values = {
            "HERMES_DYNAMIC_WORKFLOWS_INITIAL_ORCHESTRATOR_MODEL": "planner-model",
            "HERMES_DYNAMIC_WORKFLOWS_WORKER_MODEL": "worker-model",
            "HERMES_DYNAMIC_WORKFLOWS_REVIEWER_MODEL": "reviewer-model",
            "HERMES_DYNAMIC_WORKFLOWS_REPAIR_WORKER_MODEL": "repair-model",
            "HERMES_DYNAMIC_WORKFLOWS_FINAL_ORCHESTRATOR_MODEL": "final-model",
            "HERMES_DYNAMIC_WORKFLOWS_REVIEWER_AGENT_TYPE": "strict-reviewer",
        }
        with patch.dict(os.environ, values, clear=False):
            config = load_config()

        self.assertEqual(config.initial_orchestrator_model, "planner-model")
        self.assertEqual(config.worker_model, "worker-model")
        self.assertEqual(config.reviewer_model, "reviewer-model")
        self.assertEqual(config.repair_worker_model, "repair-model")
        self.assertEqual(config.final_orchestrator_model, "final-model")
        self.assertEqual(config.reviewer_agent_type, "strict-reviewer")


class RolePresetTests(unittest.TestCase):
    def test_bundled_reviewed_workflow_roles_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"HERMES_DYNAMIC_WORKFLOWS_HOME": str(Path(tmp) / "store")},
            ):
                specs = {
                    name: resolve_agent_type(name, cwd=tmp)
                    for name in (
                        "initial-orchestrator",
                        "worker",
                        "reviewer",
                        "repair-worker",
                        "final-orchestrator",
                    )
                }
                listed = {spec.name for spec in list_agent_types(cwd=tmp)}

        self.assertTrue(all(spec is not None for spec in specs.values()))
        self.assertTrue(set(specs).issubset(listed))
        for spec in specs.values():
            assert spec is not None
            self.assertEqual(spec.model, "inherit")

        reviewer = specs["reviewer"]
        final_orchestrator = specs["final-orchestrator"]
        assert reviewer is not None
        assert final_orchestrator is not None
        self.assertNotIn("write_file", reviewer.allowed_tools)
        self.assertNotIn("patch", reviewer.allowed_tools)
        self.assertNotIn("write_file", final_orchestrator.allowed_tools)
        self.assertNotIn("patch", final_orchestrator.allowed_tools)
        self.assertIn("PASS, FAIL, or BLOCKED", reviewer.instructions)
        self.assertIn("APPROVED, NOT_APPROVED, or BLOCKED", final_orchestrator.instructions)

    def test_role_config_selects_custom_agent_type_and_overrides_its_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_dir = root / ".hermes" / "dynamic-workflows" / "agents"
            agent_dir.mkdir(parents=True)
            (agent_dir / "strict-reviewer.md").write_text(
                """---
name: strict-reviewer
model: agent-type-model
toolsets: [file]
allowed_tools: [read_file, search_files]
---

Review every criterion and reject missing evidence.
""",
                encoding="utf-8",
            )
            config = PluginConfig(
                reviewer_agent_type="strict-reviewer",
                reviewer_model="role-model",
            )
            with patch(
                "hermes_dynamic_workflows.core.config.load_config",
                return_value=config,
            ):
                spec = resolve_agent_type("reviewer", cwd=tmp)

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.name, "strict-reviewer")
        self.assertEqual(spec.model, "role-model")
        self.assertIn("reject missing evidence", spec.instructions)

    def test_inherit_role_model_falls_through_to_agent_type_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_dir = root / ".hermes" / "dynamic-workflows" / "agents"
            agent_dir.mkdir(parents=True)
            (agent_dir / "custom-worker.md").write_text(
                """---
name: custom-worker
model: agent-type-model
---

Execute the scoped packet.
""",
                encoding="utf-8",
            )
            config = PluginConfig(
                worker_agent_type="custom-worker",
                worker_model="inherit",
            )
            with patch(
                "hermes_dynamic_workflows.core.config.load_config",
                return_value=config,
            ):
                spec = resolve_agent_type("worker", cwd=tmp)

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.model, "agent-type-model")

    def test_underscore_role_aliases_resolve_to_canonical_roles(self):
        config = PluginConfig()
        with patch(
            "hermes_dynamic_workflows.core.config.load_config",
            return_value=config,
        ):
            repair = resolve_agent_type("repair_worker")
            final = resolve_agent_type("final_orchestrator")

        self.assertIsNotNone(repair)
        self.assertIsNotNone(final)
        assert repair is not None
        assert final is not None
        self.assertEqual(repair.name, "repair-worker")
        self.assertEqual(final.name, "final-orchestrator")

    def test_explicit_agent_model_overrides_role_and_agent_type_models(self):
        config = PluginConfig(reviewer_model="role-model")
        with patch(
            "hermes_dynamic_workflows.core.config.load_config",
            return_value=config,
        ):
            resolved = _resolve_agent_spec(
                {"agentType": "reviewer", "model": "explicit-model"},
                cwd=os.getcwd(),
                config=config,
                structured_output=False,
            )

        self.assertEqual(resolved.model, "explicit-model")
        self.assertEqual(resolved.agent_type_name, "reviewer")


if __name__ == "__main__":
    unittest.main()
