"""Hermes hook adapter for global execution supervision."""

from __future__ import annotations

import logging
from typing import Any

from .controller import IncidentController, Intervention

logger = logging.getLogger(__name__)


class ExecutionSupervisor:
    def __init__(self, controller: IncidentController | None = None) -> None:
        self.controller = controller or IncidentController()

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
        """Bounded visible-output observation; never accesses hidden reasoning."""
        if not chunk:
            return
        # Stream evidence is intentionally advisory until a deterministic rule or
        # structured semantic judge confirms an incident.
        agent_id = self._agent_id(kwargs)
        state = self.controller.state(agent_id)
        text = str(chunk).strip()
        if text:
            state.evidence.append(f"stream:{text[:240]}")

    def on_session_end(self, **kwargs: Any) -> None:
        self.controller.reset(self._agent_id(kwargs))
