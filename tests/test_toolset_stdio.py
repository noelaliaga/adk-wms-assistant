"""MCPToolset really starts mcp-logistica over stdio and exposes the expected tools."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
from google.adk.tools.mcp_tool import McpTool, McpToolset

from conftest import SettingsFactory
from wms_assistant.toolsets import READ_TOOLS, WRITE_TOOLS, build_toolsets

ToolsetFactory = Callable[..., list[McpToolset]]


@pytest.fixture
async def open_toolsets(make_settings: SettingsFactory) -> AsyncIterator[ToolsetFactory]:
    opened: list[McpToolset] = []

    def factory(**env: str) -> list[McpToolset]:
        toolsets = build_toolsets(make_settings(**env))
        opened.extend(toolsets)
        return toolsets

    yield factory
    for toolset in opened:
        await toolset.close()


async def _names(toolset: McpToolset) -> list[str]:
    return [tool.name for tool in await toolset.get_tools()]


async def test_writes_off_exposes_only_read_tools(open_toolsets: ToolsetFactory) -> None:
    [read] = open_toolsets()
    assert await _names(read) == sorted(READ_TOOLS)


async def test_write_policy_adds_exactly_the_two_write_tools(
    open_toolsets: ToolsetFactory,
) -> None:
    read, write = open_toolsets(WMS_WRITE_POLICY="dry_run")
    assert await _names(read) == sorted(READ_TOOLS)
    tools = await write.get_tools()
    assert [t.name for t in tools] == sorted(WRITE_TOOLS)
    for tool in tools:
        assert isinstance(tool, McpTool)
        assert tool._require_confirmation is True


async def test_every_tool_the_server_offers_is_accounted_for(
    open_toolsets: ToolsetFactory,
) -> None:
    """If mcp-logistica adds a tool, this fails until the filters are updated on purpose."""
    [read] = open_toolsets()
    # An unfiltered toolset on the same server shows everything it offers.
    everything = McpToolset(connection_params=read.connection_params)
    try:
        assert await _names(everything) == sorted(READ_TOOLS + WRITE_TOOLS)
    finally:
        await everything.close()


async def test_tool_schemas_come_from_the_server(open_toolsets: ToolsetFactory) -> None:
    _, write = open_toolsets(WMS_WRITE_POLICY="on")
    [tool] = [t for t in await write.get_tools() if t.name == "set_order_status"]
    assert isinstance(tool, McpTool)
    schema = tool.raw_mcp_tool.inputSchema
    assert set(schema["properties"]) == {"order_ref", "status", "reason"}
    assert schema["additionalProperties"] is False
    assert "lost_in_transit" not in schema["properties"]["status"]["enum"]
