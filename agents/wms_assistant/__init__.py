"""Warehouse assistant built with Google ADK on top of the mcp-logistica MCP server.

`adk web` / `adk run` expect the package to expose an ``agent`` submodule, so it
is imported lazily: importing ``wms_assistant.config`` or ``wms_assistant.factory``
does not build the agent or require a database.
"""

from __future__ import annotations

import importlib
from types import ModuleType


def __getattr__(name: str) -> ModuleType:
    if name == "agent":
        return importlib.import_module("wms_assistant.agent")
    raise AttributeError(name)
