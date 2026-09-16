"""Show the person who approves a write exactly what they are approving.

The write toolset keeps ``require_confirmation=True``, but ADK's ``McpTool``
asks for approval with a generic text ("Please approve or reject the tool call
set_order_status() ...") and ``adk run`` shows only that text, not the
arguments. This ``before_tool_callback`` runs first and requests the
confirmation itself, with a hint that names the tool, every argument and what
approving does under the current policy.

Once the user has answered, the callback steps aside: ``McpTool`` still checks
the answer, so removing this callback falls back to ADK's generic prompt, never
to an unconfirmed write.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from wms_assistant.config import WritePolicy
from wms_assistant.toolsets import WRITE_TOOLS

APPROVAL_PENDING = "This tool call requires confirmation, please approve or reject."
_MAX_VALUE_CHARS = 200

_EFFECT = {
    WritePolicy.DRY_RUN: "dry run: the server checks the change and rolls it back",
    WritePolicy.ON: "the change is committed and audited as 'agent'",
}

BeforeToolCallback = Callable[[BaseTool, dict[str, Any], ToolContext], dict[str, Any] | None]


def _value(value: object) -> str:
    text = repr(value)
    if len(text) > _MAX_VALUE_CHARS:
        text = text[: _MAX_VALUE_CHARS - 3] + "..."
    return text


def describe_call(name: str, args: Mapping[str, Any]) -> str:
    """``set_order_status(order_ref='10432', status='stock_issue', ...)``, sorted by key."""
    rendered = ", ".join(f"{key}={_value(args[key])}" for key in sorted(args))
    return f"{name}({rendered})"


def approval_hint(name: str, args: Mapping[str, Any], policy: WritePolicy) -> str:
    return (
        f"Approve this write? {describe_call(name, args)}. Mode {policy.value}: {_EFFECT[policy]}."
    )


def make_approval_callback(policy: WritePolicy) -> BeforeToolCallback:
    """Return a ``before_tool_callback`` for the given write policy."""
    if policy is WritePolicy.OFF:
        raise ValueError("writes are off: there is nothing to approve")

    def request_approval(
        tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
    ) -> dict[str, Any] | None:
        if tool.name not in WRITE_TOOLS or tool_context.tool_confirmation is not None:
            # Reads need no approval. Answered writes go on to McpTool, which
            # runs the call if it was confirmed and rejects it otherwise.
            return None
        tool_context.request_confirmation(hint=approval_hint(tool.name, args, policy))
        # The pause is not a result for the model to summarize (same as McpTool).
        tool_context.actions.skip_summarization = True
        return {"error": APPROVAL_PENDING}

    return request_approval
