"""Observable non-progress detection for workflow child agents."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from typing import Any

_READ_ACTIVITY_TOKENS = frozenset(
    {
        "analyze",
        "check",
        "describe",
        "diff",
        "extract",
        "fetch",
        "find",
        "get",
        "inspect",
        "list",
        "lookup",
        "query",
        "read",
        "search",
        "show",
        "snapshot",
        "status",
        "view",
    }
)


@dataclass(frozen=True)
class NonProgressIntervention:
    """One staged response to repeated equivalent observable activity."""

    level: str
    reason: str
    signature: str
    repetitions: int
    message: str

    def metadata(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "reason": self.reason,
            "signature": self.signature,
            "repetitions": self.repetitions,
            "message": self.message,
        }


class NonProgressCircuitBreaker:
    """Warn, then stop, when a child repeats equivalent non-progress activity.

    This class observes tool activity only. It does not classify objectives, decide
    task granularity, or impose a universal tool-call budget. Distinct justified
    activity resets the repeated-signature counter.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        warning_repeats: int = 3,
        stop_repeats: int = 5,
    ) -> None:
        if warning_repeats < 2:
            raise ValueError("warning_repeats must be at least 2")
        if stop_repeats <= warning_repeats:
            raise ValueError("stop_repeats must be greater than warning_repeats")
        self.enabled = bool(enabled)
        self.warning_repeats = int(warning_repeats)
        self.stop_repeats = int(stop_repeats)
        self._signature = ""
        self._description = ""
        self._repetitions = 0
        self._warned = False
        self._lock = threading.RLock()

    def observe_tool(self, tool_name: str, args: Any) -> NonProgressIntervention | None:
        clean_name = str(tool_name or "tool").strip().lower()
        if not self.enabled or not _is_read_activity(clean_name):
            self.reset()
            return None
        signature = _signature("tool", clean_name, args)
        return self._observe(
            signature,
            f"repeated equivalent {clean_name} activity",
        )

    def observe_invalid_submission(self, validation_error: str) -> NonProgressIntervention | None:
        if not self.enabled:
            return None
        clean_error = _normalize_text(validation_error)
        if not clean_error:
            return None
        return self._observe(
            _signature("invalid-structured-output", clean_error, None),
            "repeated invalid structured submissions with no material correction",
        )

    def reset(self) -> None:
        with self._lock:
            self._signature = ""
            self._description = ""
            self._repetitions = 0
            self._warned = False

    def _observe(
        self,
        signature: str,
        description: str,
    ) -> NonProgressIntervention | None:
        with self._lock:
            if signature != self._signature:
                self._signature = signature
                self._description = description
                self._repetitions = 1
                self._warned = False
                return None

            self._repetitions += 1
            if self._repetitions >= self.stop_repeats:
                return NonProgressIntervention(
                    level="stop",
                    reason=self._description,
                    signature=signature,
                    repetitions=self._repetitions,
                    message=(
                        "Non-progress circuit breaker stopped this child after "
                        f"{self._repetitions} repetitions of {self._description}."
                    ),
                )
            if self._repetitions >= self.warning_repeats and not self._warned:
                self._warned = True
                return NonProgressIntervention(
                    level="warning",
                    reason=self._description,
                    signature=signature,
                    repetitions=self._repetitions,
                    message=(
                        "Non-progress warning: stop repeating equivalent activity. "
                        "Decide whether the available evidence is sufficient to execute or "
                        "submit the required package. Otherwise make one materially different, "
                        "justified tool call."
                    ),
                )
            return None


def _is_read_activity(tool_name: str) -> bool:
    if tool_name == "structured_output":
        return False
    tokens = {token for token in re.split(r"[^a-z0-9]+", tool_name) if token}
    return bool(tokens & _READ_ACTIVITY_TOKENS)


def _signature(kind: str, name: str, args: Any) -> str:
    payload = {
        "kind": kind,
        "name": _normalize_text(name),
        "args": _normalize_value(args),
    }
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:20]


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    if isinstance(value, str):
        return _normalize_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _normalize_text(str(value))


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())
