"""Optional fail-open NVIDIA Step 3.7 Flash semantic judge."""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SemanticJudgment:
    incident: bool
    reason: str
    evidence: tuple[str, ...]


class NvidiaSemanticJudge:
    """Small OpenAI-compatible client. Network/provider failures return no judgment."""

    def __init__(self) -> None:
        self.api_key = os.getenv("NVIDIA_API_KEY", "")
        self.base_url = os.getenv(
            "HERMES_EXECUTION_SUPERVISOR_NVIDIA_URL",
            "https://integrate.api.nvidia.com/v1/chat/completions",
        )
        self.model = os.getenv(
            "HERMES_EXECUTION_SUPERVISOR_MODEL",
            "nvidia/step-3.7-flash",
        )
        self.timeout = float(os.getenv("HERMES_EXECUTION_SUPERVISOR_JUDGE_TIMEOUT", "8"))

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def judge(self, snapshot: dict[str, Any]) -> SemanticJudgment | None:
        if not self.available:
            return None
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "incident": {"type": "boolean"},
                "reason": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["incident", "reason", "evidence"],
        }
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Judge only visible execution evidence for looping, semantic drift, "
                        "or lack of material progress. Return strict JSON. Do not infer hidden reasoning."
                    ),
                },
                {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_schema", "json_schema": {"name": "judgment", "schema": schema}},
        }
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return SemanticJudgment(
                incident=parsed["incident"] is True,
                reason=str(parsed["reason"]),
                evidence=tuple(str(item) for item in parsed["evidence"]),
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None
