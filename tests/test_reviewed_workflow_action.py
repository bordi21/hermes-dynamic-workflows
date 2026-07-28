from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any

from hermes_dynamic_workflows.actions.workflow import ReviewedWorkflowAction
from hermes_dynamic_workflows.core.errors import ReviewedStateError
from hermes_dynamic_workflows.core.types import WorkflowFrame, WorkflowState


OBJECTIVE = "Deliver one reviewed result."


def _task(
    task_id: str,
    *,
    plan_id: str = "plan-1",
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": plan_id,
        "task_id": task_id,
        "objective": f"Complete {task_id}.",
        "depends_on": list(depends_on or []),
        "paths": ["src"],
        "constraints": ["Stay scoped."],
        "allowed_mutations": ["src"],
        "acceptance_criteria": [f"{task_id} is verified."],
        "evidence_requirements": ["Focused test evidence."],
        "worker_instructions": f"Implement {task_id}.",
        "reviewer_guidelines": [f"Reject {task_id} without evidence."],
    }


def _plan(
    *tasks: dict[str, Any],
    plan_id: str = "plan-1",
    cycle: int = 0,
    max_replans: int = 1,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": plan_id,
        "cycle": cycle,
        "original_objective": OBJECTIVE,
        "tasks": list(tasks),
        "final_validation_criteria": ["The original objective is satisfied."],
        "max_repairs_per_task": 1,
        "max_replanning_cycles": max_replans,
    }


def _worker_result(plan_id: str, task_id: str, status: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": plan_id,
        "task_id": task_id,
        "attempt": 1,
        "status": status,
        "summary": f"Worker {status} for {task_id}.",
        "changed_paths": [f"src/{task_id}.py"],
        "evidence": [{"kind": "test", "reference": f"worker:{task_id}"}],
        "tests": [{"name": task_id, "status": "PASS" if status == "COMPLETED" else "FAIL"}],
        "blocker": "External dependency." if status == "BLOCKED" else None,
    }


def _review(plan_id: str, task_id: str, verdict: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": plan_id,
        "task_id": task_id,
        "attempt": 1,
        "verdict": verdict,
        "summary": f"Review {verdict} for {task_id}.",
        "criteria_results": [],
        "feedback": [] if verdict == "PASS" else [f"Resolve {task_id}."],
        "evidence": [{"kind": "test", "reference": f"review:{task_id}"}],
    }


def _terminalize(state: Any, task_id: str, outcome: str) -> None:
    snapshot = state.snapshot()
    task = next(item for item in snapshot["tasks"] if item["task_id"] == task_id)
    plan_id = task["plan_id"]
    state.start_task(task_id)
    if outcome == "INTEGRATED":
        state.submit_worker_result(task_id, _worker_result(plan_id, task_id, "COMPLETED"))
        state.submit_review_verdict(task_id, _review(plan_id, task_id, "PASS"))
        state.integrate_task(
            task_id,
            {
                "schema_version": "1.0",
                "plan_id": plan_id,
                "task_id": task_id,
                "status": "INTEGRATED",
                "summary": f"Integrated {task_id}.",
                "integrated_commit": f"commit-{task_id}",
                "evidence": [{"kind": "diff", "reference": f"commit:{task_id}"}],
            },
        )
    elif outcome == "FAILED":
        state.submit_worker_result(task_id, _worker_result(plan_id, task_id, "FAILED"))
        state.submit_review_verdict(task_id, _review(plan_id, task_id, "FAIL"))
        state.mark_task_failed(task_id)
    elif outcome == "BLOCKED":
        state.submit_worker_result(task_id, _worker_result(plan_id, task_id, "BLOCKED"))
        state.submit_review_verdict(task_id, _review(plan_id, task_id, "BLOCKED"))
    elif outcome == "PASS":
        state.submit_worker_result(task_id, _worker_result(plan_id, task_id, "COMPLETED"))
        state.submit_review_verdict(task_id, _review(plan_id, task_id, "PASS"))
    else:
        raise AssertionError(f"unknown test outcome: {outcome}")


@dataclass
class _Context:
    state: WorkflowState = field(
        default_factory=lambda: WorkflowState(
            WorkflowFrame(id="root", meta={"name": "test"}, args=None, cwd="/repo")
        )
    )
    events: list[dict[str, Any]] = field(default_factory=list)
    notifications: int = 0
    runtime_checks: int = 0

    def journal(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def notify(self) -> None:
        self.notifications += 1

    def check_runtime(self) -> None:
        self.runtime_checks += 1


class _API:
    def __init__(self):
        self.context = _Context()
        self.phases: list[str] = []
        self.logs: list[str] = []

    def phase(self, name: str) -> None:
        self.phases.append(name)

    def log(self, message: str) -> None:
        self.logs.append(message)


class _Planner:
    def __init__(self, initial_plan: dict[str, Any]):
        self.initial_plan = initial_plan
        self.calls = 0

    async def run(self, api: _API, *, original_objective: str, cycle: int) -> dict[str, Any]:
        self.calls += 1
        self.assert_request(original_objective, cycle)
        api.context.state.reviewed.register_plan(self.initial_plan)
        return self.initial_plan

    @staticmethod
    def assert_request(original_objective: str, cycle: int) -> None:
        if original_objective != OBJECTIVE or cycle != 0:
            raise AssertionError("unexpected planner request")


class _Executor:
    def __init__(self, outcomes: dict[str, str]):
        self.outcomes = outcomes
        self.calls = 0

    async def run_ready(self, api: _API) -> list[dict[str, Any]]:
        self.calls += 1
        results: list[dict[str, Any]] = []
        while True:
            ready = api.context.state.reviewed.ready_task_ids()
            if not ready:
                return results
            for task_id in ready:
                outcome = self.outcomes.get(task_id)
                if outcome is None:
                    return results
                _terminalize(api.context.state.reviewed, task_id, outcome)
                results.append({"task_id": task_id, "status": outcome})


class _Validator:
    def __init__(self, responses: list[dict[str, Any]]):
        self.responses = list(responses)
        self.calls: list[str] = []

    async def run(self, api: _API, *, plan_id: str) -> dict[str, Any]:
        self.calls.append(plan_id)
        response = self.responses.pop(0)
        cycle = next(
            item
            for item in api.context.state.reviewed.snapshot()["planning_cycles"]
            if item["plan_id"] == plan_id
        )
        validation = {
            "schema_version": "1.0",
            "plan_id": plan_id,
            "cycle": cycle["cycle"],
            "verdict": response["verdict"],
            "summary": response["verdict"],
            "requirement_results": [],
            "delta_tasks": [],
            "evidence": [{"kind": "state", "reference": f"validation:{plan_id}"}],
        }
        api.context.state.reviewed.record_final_validation(validation)
        next_plan = response.get("next_plan")
        if next_plan is not None:
            api.context.state.reviewed.register_plan(next_plan)
        return {
            "plan_id": plan_id,
            "cycle": cycle["cycle"],
            "status": response["status"],
            "validation": validation,
            "remaining_replanning_cycles": 0,
            "next_plan": next_plan,
        }


class _Reporter:
    def __init__(self):
        self.calls = 0

    def run(self, api: _API) -> dict[str, Any]:
        self.calls += 1
        snapshot = api.context.state.reviewed.snapshot()
        validation = snapshot["planning_cycles"][-1]["final_validation"]
        verdict = validation["verdict"]
        outcome = "FAILED" if verdict == "NOT_APPROVED" else verdict
        report = {
            "original_objective": OBJECTIVE,
            "outcome": outcome,
            "planning_cycles": len(snapshot["planning_cycles"]),
        }
        api.context.state.reviewed.set_terminal_report(report)
        return report


class ReviewedWorkflowActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_plan_executes_validates_and_reports(self):
        api = _API()
        planner = _Planner(_plan(_task("A")))
        executor = _Executor({"A": "INTEGRATED"})
        validator = _Validator([{"verdict": "APPROVED", "status": "APPROVED"}])
        reporter = _Reporter()
        action = ReviewedWorkflowAction(
            planner=planner,
            executor=executor,
            validator=validator,
            reporter=reporter,
        )

        report = await action.run(api, original_objective=OBJECTIVE)

        self.assertEqual(report["outcome"], "APPROVED")
        self.assertEqual(planner.calls, 1)
        self.assertEqual(executor.calls, 1)
        self.assertEqual(validator.calls, ["plan-1"])
        self.assertEqual(reporter.calls, 1)
        self.assertEqual(api.phases, ["Planning", "Execution", "Final Validation", "Reporting"])
        self.assertGreaterEqual(api.context.runtime_checks, 1)

    async def test_replanned_cycle_uses_same_execution_path(self):
        api = _API()
        initial = _plan(_task("A"), max_replans=1)
        delta = _plan(
            _task("B", plan_id="plan-2", depends_on=["A"]),
            plan_id="plan-2",
            cycle=1,
            max_replans=1,
        )
        planner = _Planner(initial)
        executor = _Executor({"A": "INTEGRATED", "B": "INTEGRATED"})
        validator = _Validator(
            [
                {"verdict": "NOT_APPROVED", "status": "REPLANNED", "next_plan": delta},
                {"verdict": "APPROVED", "status": "APPROVED"},
            ]
        )
        reporter = _Reporter()
        action = ReviewedWorkflowAction(
            planner=planner,
            executor=executor,
            validator=validator,
            reporter=reporter,
        )

        report = await action.run(api, original_objective=OBJECTIVE)

        self.assertEqual(report["outcome"], "APPROVED")
        self.assertEqual(report["planning_cycles"], 2)
        self.assertEqual(executor.calls, 2)
        self.assertEqual(validator.calls, ["plan-1", "plan-2"])
        self.assertEqual(
            [item["status"] for item in api.context.state.reviewed.snapshot()["tasks"]],
            ["INTEGRATED", "INTEGRATED"],
        )

    async def test_failed_dependency_skips_downstream_tasks_transitively(self):
        api = _API()
        initial = _plan(
            _task("A"),
            _task("B", depends_on=["A"]),
            _task("C", depends_on=["B"]),
            max_replans=0,
        )
        planner = _Planner(initial)
        executor = _Executor({"A": "FAILED"})
        validator = _Validator([{"verdict": "NOT_APPROVED", "status": "EXHAUSTED"}])
        reporter = _Reporter()
        action = ReviewedWorkflowAction(
            planner=planner,
            executor=executor,
            validator=validator,
            reporter=reporter,
        )

        report = await action.run(api, original_objective=OBJECTIVE)

        self.assertEqual(report["outcome"], "FAILED")
        tasks = {item["task_id"]: item for item in api.context.state.reviewed.snapshot()["tasks"]}
        self.assertEqual(tasks["A"]["status"], "FAILED")
        self.assertEqual(tasks["B"]["status"], "SKIPPED")
        self.assertEqual(tasks["C"]["status"], "SKIPPED")
        self.assertIn("A=FAILED", tasks["B"]["skip_reason"])
        self.assertIn("B=SKIPPED", tasks["C"]["skip_reason"])
        skip_events = [item for item in api.context.events if item["type"] == "reviewed_task_skipped"]
        self.assertEqual([item["taskId"] for item in skip_events], ["B", "C"])

    async def test_nonterminal_pass_from_integration_conflict_stops_fail_closed(self):
        api = _API()
        planner = _Planner(_plan(_task("A")))
        executor = _Executor({"A": "PASS"})
        validator = _Validator([{"verdict": "APPROVED", "status": "APPROVED"}])
        reporter = _Reporter()
        action = ReviewedWorkflowAction(
            planner=planner,
            executor=executor,
            validator=validator,
            reporter=reporter,
        )

        with self.assertRaisesRegex(ReviewedStateError, "A=PASS"):
            await action.run(api, original_objective=OBJECTIVE)

        self.assertEqual(validator.calls, [])
        self.assertEqual(reporter.calls, 0)

    async def test_existing_terminal_report_is_idempotent_and_objective_bound(self):
        api = _API()
        api.context.state.reviewed.register_plan(_plan(_task("A"), max_replans=0))
        _terminalize(api.context.state.reviewed, "A", "INTEGRATED")
        api.context.state.reviewed.record_final_validation(
            {
                "plan_id": "plan-1",
                "cycle": 0,
                "verdict": "APPROVED",
            }
        )
        existing = {"original_objective": OBJECTIVE, "outcome": "APPROVED"}
        api.context.state.reviewed.set_terminal_report(existing)
        action = ReviewedWorkflowAction(
            planner=_Planner(_plan(_task("unused"))),
            executor=_Executor({}),
            validator=_Validator([]),
            reporter=_Reporter(),
        )

        result = await action.run(api, original_objective=OBJECTIVE)
        self.assertEqual(result, existing)
        result["outcome"] = "FAILED"
        self.assertEqual(
            api.context.state.reviewed.snapshot()["terminal_report"]["outcome"],
            "APPROVED",
        )

        with self.assertRaisesRegex(ReviewedStateError, "different original objective"):
            await action.run(api, original_objective="A different objective.")


if __name__ == "__main__":
    unittest.main()
