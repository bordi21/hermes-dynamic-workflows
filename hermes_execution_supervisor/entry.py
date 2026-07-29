"""Separately installable Hermes execution-supervisor plugin entrypoint."""

from __future__ import annotations

import logging

from .supervisor import ExecutionSupervisor

logger = logging.getLogger(__name__)
_supervisor = ExecutionSupervisor()


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _supervisor.pre_tool_call)
    ctx.register_hook("post_tool_call", _supervisor.post_tool_call)
    ctx.register_hook("pre_llm_call", _supervisor.pre_llm_call)
    ctx.register_hook("on_session_end", _supervisor.on_session_end)

    # DEC-010 permits a narrow future core hook. Older Hermes releases reject
    # unknown hooks, so registration is capability-detected and remains optional.
    try:
        ctx.register_hook("on_llm_stream_chunk", _supervisor.on_llm_stream_chunk)
    except (KeyError, ValueError):
        logger.info("on_llm_stream_chunk is unavailable; tool-boundary supervision remains active")
