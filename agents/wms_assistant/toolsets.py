"""MCP toolsets that connect the agent to the mcp-logistica server over stdio.

Two toolsets, two server processes, on purpose:

* The read toolset always starts the server with ``WMS_WRITE_MODE=off`` and
  only exposes read tools. Even if the filter were wrong, that process rejects
  every write.
* The write toolset exists only when the write policy is ``dry_run`` or ``on``.
  It exposes the two write tools, and ADK asks the user to approve every call
  (``require_confirmation=True``) before the request reaches the server.

The server processes get only the variables they need (plus the MCP SDK's
default safe set: HOME, PATH, ...). Model API keys in this process's
environment are not passed to them. PYTHONPATH is forwarded when set, because
some hosts (ADK's Agent Engine packaging, for one) make staged packages
importable that way.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters

from wms_assistant.config import Settings, WritePolicy

READ_TOOLS: tuple[str, ...] = (
    "find_orders",
    "get_audit_log",
    "get_order",
    "get_stock",
    "list_stalled_orders",
)
WRITE_TOOLS: tuple[str, ...] = ("add_order_note", "set_order_status")


FORWARDED_ENV: tuple[str, ...] = ("PYTHONPATH",)


def server_params(
    settings: Settings, write_mode: WritePolicy, environ: Mapping[str, str] | None = None
) -> StdioServerParameters:
    source = os.environ if environ is None else environ
    env = {name: source[name] for name in FORWARDED_ENV if source.get(name)}
    env["WMS_DB_PATH"] = str(settings.db_path)
    env["WMS_WRITE_MODE"] = write_mode.value
    command, *args = settings.server_command
    return StdioServerParameters(command=command, args=list(args), env=env)


def _toolset(
    settings: Settings,
    write_mode: WritePolicy,
    tools: tuple[str, ...],
    *,
    require_confirmation: bool,
) -> McpToolset:
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=server_params(settings, write_mode),
            timeout=settings.mcp_timeout_s,
        ),
        tool_filter=list(tools),
        require_confirmation=require_confirmation,
    )


def build_toolsets(settings: Settings) -> list[McpToolset]:
    toolsets = [
        _toolset(settings, WritePolicy.OFF, READ_TOOLS, require_confirmation=False),
    ]
    if settings.write_policy is not WritePolicy.OFF:
        toolsets.append(
            _toolset(settings, settings.write_policy, WRITE_TOOLS, require_confirmation=True)
        )
    return toolsets
