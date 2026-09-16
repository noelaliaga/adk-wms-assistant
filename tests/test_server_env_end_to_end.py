"""Model keys never reach the MCP server process: checked in the real child process.

test_agent_build.py checks the parameters handed to the MCP SDK. This test
starts the servers through ADK's McpToolset with a probe command that records
the environment it was actually given, so a change in how the SDK merges
environments would fail here.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

from conftest import REPO, SettingsFactory
from wms_assistant.toolsets import READ_TOOLS, WRITE_TOOLS, build_toolsets

PROBE = REPO / "tests" / "support" / "env_probe_server.py"
SECRETS = {
    "GOOGLE_API_KEY": "not-a-real-key",
    "GEMINI_API_KEY": "not-a-real-key",
    "ANTHROPIC_API_KEY": "not-a-real-key",
    "OPENAI_API_KEY": "not-a-real-key",
    "AWS_SECRET_ACCESS_KEY": "not-a-real-key",
    "GOOGLE_APPLICATION_CREDENTIALS": "/nonexistent/adc.json",
}


async def test_server_processes_get_no_model_keys(
    make_settings: SettingsFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    out = tmp_path / "server-env.txt"
    command = shlex.join([sys.executable, str(PROBE), str(out)])
    settings = make_settings(WMS_WRITE_POLICY="on", WMS_MCP_COMMAND=command)

    seen: list[set[str]] = []
    for toolset, expected in zip(build_toolsets(settings), (READ_TOOLS, WRITE_TOOLS), strict=True):
        out.unlink(missing_ok=True)
        try:
            tools = await toolset.get_tools()
        finally:
            await toolset.close()
        assert sorted(t.name for t in tools) == sorted(expected)
        seen.append(set(out.read_text(encoding="utf-8").split()))

    for names in seen:
        assert {"WMS_DB_PATH", "WMS_WRITE_MODE"} <= names
        assert not names & set(SECRETS), names & set(SECRETS)
        assert not {n for n in names if n.endswith(("_API_KEY", "_TOKEN", "_SECRET"))}
