"""Structured logs for every tool call and model response.

One JSON object per line on the ``wms_assistant.telemetry`` logger:

* ``tool_call``: tool, duration, outcome (``ok``, the server's own outcome such
  as ``needs_clarification`` or ``dry_run``, ``server_error``,
  ``approval_requested``, ``rejected`` or ``error``) and the argument *names*.
* ``model_response``: input and output tokens as reported by the model, and how
  many tool calls it asked for.

Both carry the instruction version, so a log line says which instruction
produced it. Argument values and message text are not logged: they can contain
customer names.

Nothing is sent anywhere. Attach a handler (or ``adk web --log_level``) to see
the lines; a deployment would ship them to its log backend.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from wms_assistant.approval import APPROVAL_PENDING
from wms_assistant.prompts import INSTRUCTION_VERSION

LOGGER_NAME = "wms_assistant.telemetry"
_REJECTED = "This tool call is rejected."


def tool_outcome(result: object) -> str:
    """Classify a tool result as ADK hands it back (an MCP result dumped to a dict)."""
    if not isinstance(result, dict):
        return "ok"
    error = result.get("error")
    if error == APPROVAL_PENDING or (isinstance(error, str) and "requires confirmation" in error):
        return "approval_requested"
    if error == _REJECTED:
        return "rejected"
    if error is not None:
        return "error"
    if result.get("isError") is True:
        return "server_error"
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and isinstance(structured.get("outcome"), str):
        return str(structured["outcome"])
    return "ok"


class Telemetry:
    """Callbacks for ``LlmAgent``. One instance per agent."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(LOGGER_NAME)
        self._started: dict[str, float] = {}

    def _emit(self, record: dict[str, Any]) -> None:
        record = {"instruction_version": INSTRUCTION_VERSION, **record}
        self.logger.info(json.dumps(record, sort_keys=True, ensure_ascii=False))

    def before_tool(
        self, tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
    ) -> dict[str, Any] | None:
        if tool_context.function_call_id:
            self._started[tool_context.function_call_id] = time.perf_counter()
        return None

    def after_tool(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
        tool_response: dict[str, Any],
    ) -> dict[str, Any] | None:
        call_id = tool_context.function_call_id or ""
        started = self._started.pop(call_id, None)
        duration_ms = None if started is None else round((time.perf_counter() - started) * 1000, 1)
        self._emit(
            {
                "event": "tool_call",
                "invocation_id": tool_context.invocation_id,
                "function_call_id": call_id,
                "tool": tool.name,
                "arg_names": sorted(args),
                "duration_ms": duration_ms,
                "outcome": tool_outcome(tool_response),
            }
        )
        return None

    def after_model(
        self, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        usage = llm_response.usage_metadata
        parts = llm_response.content.parts if llm_response.content else None
        self._emit(
            {
                "event": "model_response",
                "invocation_id": callback_context.invocation_id,
                "model_version": llm_response.model_version,
                "input_tokens": usage.prompt_token_count if usage else None,
                "output_tokens": usage.candidates_token_count if usage else None,
                "tool_calls": sum(1 for p in parts or [] if p.function_call),
                "error_code": llm_response.error_code,
            }
        )
        return None
