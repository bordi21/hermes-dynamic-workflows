"""Hermes hook adapter for global execution supervision."""

from __future__ import annotations

import logging
import threading
from typing import Any

from .controller import IncidentController, Intervention
from .judge import NvidiaSemanticJudge

logger = logging.getLogger(__name__)


class ExecutionSupervisor:
    def __init__(
        self,
        controller: IncidentController | None = None,
        judge: NvidiaSemanticJudge | None = None,
        *,
        semantic_interval: int = 6,
    ) -> None:
        self.controller = controller or IncidentController()
        self.judge = judge or NvidiaSemanticJudge()
        self.semantic_interval = max(1, semantic_interval)
        self._tool_counts: dict[str, int] = {}
        self._judge_running: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _agent_id(kwargs: dict[str, Any]) -> str:
        return str(
            kwargs.get("agent_id")
            or kwargs.get("session_id")
            or kwargs.get("task_id")
            or "unknown"
        )

    def pre_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any):
        agent_id = self._agent_id(kwargs)
        incident = self.controller.observe_tool(agent_id, tool_name, args or {})
        if incident is None:
            return None
        return self._intervention(agent_id, incident)

    def post_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: str,
        **kwargs: Any,
    ) -> None:
        agent_id = self._agent_id(kwargs)
        state = self.controller.state(agent_id)
        state.evidence.append(f"tool:{tool_name}:{str(result)[:300]}")
        count = self._tool_counts.get(agent_id, 0) + 1
        self._tool_counts[agent_id] = count
        if count % self.semantic_interval == 0:
            self._schedule_semantic_check(agent_id)

    def _schedule_semantic_check(self, agent_id: str) -> None:
        if not self.judge.available or self.controller.state(agent_id).stopped:
            return
        with self._lock:
            if agent_id in self._judge_running:
                return
            self._judge_running.add(agent_id)
        threading.Thread(
            target=self._run_semantic_check,
            args=(agent_id,),
            name=f"hermes-supervisor-{agent_id[:24]}",
            daemon=True,
        ).start()

    def _run_semantic_check(self, agent_id: str) -> None:
        try:
            state = self.controller.state(agent_id)
            judgment = self.judge.judge(
                {
                    "agent_id": agent_id,
                    "incident_count": state.incidents,
                    "recent_evidence": list(state.evidence),
                }
            )
            if judgment and judgment.incident:
                self.controller.confirm(
                    agent_id,
                    reason=judgment.reason,
                    evidence=judgment.evidence,
                )
        finally:
            with self._lock:
                self._judge_running.discard(agent_id)

    def _intervention(self, agent_id: str, incident: Any):
        if incident.intervention is Intervention.STOP:
            message = (
                "Execution supervisor stopped this agent after the third confirmed incident. "
                f"Reason: {incident.reason}. Evidence: {', '.join(incident.evidence)}. "
                "Do not restart or replace this agent automatically; report this stop to the user."
            )
            logger.error("supervisor_stop agent=%s reason=%s", agent_id, incident.reason)
            return {"action": "block", "message": message}

        message = self.controller.state(agent_id).pending_feedback or incident.reason
        logger.warning("supervisor_correct agent=%s incident=%s", agent_id, incident.number)
        return {"action": "block", "message": message}

    def pre_llm_call(self, **kwargs: Any):
        agent_id = self._agent_id(kwargs)
        state = self.controller.state(agent_id)
        if state.stopped:
            return {
                "context": (
                    "The execution supervisor has stopped this agent after three confirmed incidents. "
                    "Do not continue, restart, or spawn a replacement. Report the reason and evidence."
                )
            }
        feedback = self.controller.consume_feedback(agent_id)
        return {"context": feedback} if feedback else None

    def on_llm_stream_chunk(self, chunk: str = "", **kwargs: Any) -> None:
        """Observe bounded visible output only; hidden chain-of-thought is never read."""
        if not chunk:
            return
        agent_id = self._agent_id(kwargs)
        text = str(chunk).strip()
        if text:
            self.controller.state(agent_id).evidence.append(f"stream:{text[:240]}")

    def on_session_end(self, **kwargs: Any) -> None:
        agent_id = self._agent_id(kwargs)
        self.controller.reset(agent_id)
        self._tool_counts.pop(agent_id, None)
