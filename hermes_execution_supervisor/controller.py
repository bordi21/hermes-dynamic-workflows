"""Deterministic policy for the global Hermes execution supervisor."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Intervention(str, Enum):
    NONE = "none"
    CORRECT = "correct"
    STOP = "stop"


@dataclass(frozen=True)
class Incident:
    number: int
    reason: str
    evidence: tuple[str, ...]
    intervention: Intervention


@dataclass
class AgentState:
    incidents: int = 0
    stopped: bool = False
    pending_feedback: str | None = None
    fingerprints: deque[str] = field(default_factory=lambda: deque(maxlen=12))
    evidence: deque[str] = field(default_factory=lambda: deque(maxlen=24))


class IncidentController:
    """Own fail-closed intervention policy; semantic judges only provide evidence."""

    def __init__(self, *, repeat_threshold: int = 3) -> None:
        if repeat_threshold < 2:
            raise ValueError("repeat_threshold must be at least 2")
        self.repeat_threshold = repeat_threshold
        self._states: dict[str, AgentState] = {}

    def state(self, agent_id: str) -> AgentState:
        return self._states.setdefault(agent_id or "unknown", AgentState())

    @staticmethod
    def fingerprint(tool_name: str, args: dict[str, Any]) -> str:
        payload = json.dumps(
            {"tool": tool_name, "args": args},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]

    def observe_tool(self, agent_id: str, tool_name: str, args: dict[str, Any]) -> Incident | None:
        state = self.state(agent_id)
        if state.stopped:
            return Incident(
                state.incidents,
                "agent already stopped after third confirmed incident",
                tuple(state.evidence),
                Intervention.STOP,
            )

        fp = self.fingerprint(tool_name, args)
        state.fingerprints.append(fp)
        repeated = sum(1 for item in state.fingerprints if item == fp)
        if repeated < self.repeat_threshold:
            return None
        return self.confirm(
            agent_id,
            reason=f"repeated identical tool call {tool_name!r} {repeated} times",
            evidence=(f"tool={tool_name}", f"fingerprint={fp}", f"count={repeated}"),
        )

    def confirm(self, agent_id: str, *, reason: str, evidence: tuple[str, ...]) -> Incident:
        state = self.state(agent_id)
        if state.stopped:
            return Incident(state.incidents, reason, tuple(state.evidence), Intervention.STOP)

        state.incidents += 1
        state.evidence.extend(evidence)
        if state.incidents >= 3:
            state.stopped = True
            state.pending_feedback = None
            intervention = Intervention.STOP
        else:
            state.pending_feedback = (
                f"Execution supervisor incident {state.incidents}/3: {reason}. "
                "Change approach materially, verify progress, and do not repeat the same action."
            )
            intervention = Intervention.CORRECT
        return Incident(state.incidents, reason, evidence, intervention)

    def consume_feedback(self, agent_id: str) -> str | None:
        state = self.state(agent_id)
        feedback = state.pending_feedback
        state.pending_feedback = None
        return feedback

    def reset(self, agent_id: str) -> None:
        self._states.pop(agent_id or "unknown", None)
