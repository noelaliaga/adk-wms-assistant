"""The agent is assembled with the right model, instruction and safety settings.

Nothing here starts a server or calls a model.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams

from conftest import SettingsFactory
from wms_assistant.config import DEFAULT_GEMINI_MODEL, ConfigError, WritePolicy
from wms_assistant.factory import AGENT_NAME, build_agent
from wms_assistant.prompts import build_instruction
from wms_assistant.toolsets import READ_TOOLS, WRITE_TOOLS, server_params

AGENT_DIR = Path(__file__).resolve().parents[1] / "agents" / "wms_assistant"


def _toolsets(agent: LlmAgent) -> list[McpToolset]:
    toolsets = [t for t in agent.tools if isinstance(t, McpToolset)]
    assert len(toolsets) == len(agent.tools)
    return toolsets


def _env(toolset: McpToolset) -> dict[str, str]:
    params = toolset.connection_params
    assert isinstance(params, StdioConnectionParams)
    assert params.server_params.env is not None
    return params.server_params.env


def _filter(toolset: McpToolset) -> list[str]:
    assert isinstance(toolset.tool_filter, list)
    return toolset.tool_filter


def test_default_agent_uses_gemini_and_is_read_only(make_settings: SettingsFactory) -> None:
    agent = build_agent(make_settings())
    assert agent.name == AGENT_NAME
    assert agent.model == DEFAULT_GEMINI_MODEL
    assert agent.generate_content_config is not None
    assert agent.generate_content_config.temperature == 0.0

    [read] = _toolsets(agent)
    assert sorted(_filter(read)) == sorted(READ_TOOLS)
    assert read.require_confirmation is False
    assert _env(read)["WMS_WRITE_MODE"] == "off"


@pytest.mark.parametrize("policy", ["dry_run", "on"])
def test_write_tools_need_confirmation_and_run_in_their_own_server(
    make_settings: SettingsFactory, policy: str
) -> None:
    agent = build_agent(make_settings(WMS_WRITE_POLICY=policy))
    read, write = _toolsets(agent)
    # Reads keep a server that refuses every write, whatever the policy.
    assert _env(read)["WMS_WRITE_MODE"] == "off"
    assert read.require_confirmation is False
    assert sorted(_filter(write)) == sorted(WRITE_TOOLS)
    assert write.require_confirmation is True
    assert _env(write)["WMS_WRITE_MODE"] == policy


def test_server_processes_do_not_receive_model_keys(
    make_settings: SettingsFactory, monkeypatch: pytest.MonkeyPatch, db_path: Path
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "not-a-real-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    agent = build_agent(make_settings(WMS_WRITE_POLICY="on"))
    for toolset in _toolsets(agent):
        env = _env(toolset)
        assert set(env) == {"WMS_DB_PATH", "WMS_WRITE_MODE"}
        assert env["WMS_DB_PATH"] == str(db_path)


def test_pythonpath_is_forwarded_when_set(make_settings: SettingsFactory) -> None:
    params = server_params(make_settings(), WritePolicy.OFF, {"PYTHONPATH": "/app", "X": "y"})
    assert params.env == {
        "PYTHONPATH": "/app",
        "WMS_DB_PATH": str(make_settings().db_path),
        "WMS_WRITE_MODE": "off",
    }


def test_instruction_asks_before_assuming_and_matches_the_policy(
    make_settings: SettingsFactory,
) -> None:
    off = build_agent(make_settings())
    assert off.instruction == build_instruction(WritePolicy.OFF)
    assert isinstance(off.instruction, str)
    assert "Ask before assuming" in off.instruction
    assert "<untrusted-data>" in off.instruction
    assert "read-only tools" in off.instruction
    assert "explicit approval" not in off.instruction

    dry = build_agent(make_settings(WMS_WRITE_POLICY="dry_run"))
    assert isinstance(dry.instruction, str)
    assert "explicit approval" in dry.instruction
    assert "dry-run mode" in dry.instruction
    assert "shipped, delivered or cancelled" in dry.instruction

    on = build_agent(make_settings(WMS_WRITE_POLICY="on"))
    assert isinstance(on.instruction, str)
    assert "dry-run mode" not in on.instruction


def test_litellm_backend_builds_a_litellm_model(make_settings: SettingsFactory) -> None:
    agent = build_agent(
        make_settings(WMS_MODEL_BACKEND="litellm", WMS_MODEL="anthropic/some-claude-model")
    )
    assert isinstance(agent.model, LiteLlm)
    assert agent.model.model == "anthropic/some-claude-model"


def _fresh_import_agent_module() -> object:
    sys.modules.pop("wms_assistant.agent", None)
    return importlib.import_module("wms_assistant.agent")


def test_adk_entry_point_exposes_root_agent(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    monkeypatch.setenv("WMS_DB_PATH", str(db_path))
    module = _fresh_import_agent_module()
    root_agent = getattr(module, "root_agent", None)
    assert isinstance(root_agent, LlmAgent)
    assert root_agent.name == AGENT_NAME
    # The package resolves `.agent` lazily, which is how the ADK CLI loads it.
    package = importlib.import_module("wms_assistant")
    assert package.agent is module


def test_adk_entry_point_refuses_a_missing_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WMS_DB_PATH", str(tmp_path / "missing.sqlite"))
    with pytest.raises(ConfigError, match="make seed"):
        _fresh_import_agent_module()
    assert not (tmp_path / "missing.sqlite").exists()


def test_adk_cli_loader_finds_the_agent(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    """The same loader `adk web agents` and `adk run agents/wms_assistant` use."""
    from google.adk.cli.utils.agent_loader import AgentLoader

    monkeypatch.setenv("WMS_DB_PATH", str(db_path))
    sys.modules.pop("wms_assistant.agent", None)
    agents_dir = Path(__file__).resolve().parents[1] / "agents"
    loaded = AgentLoader(str(agents_dir)).load_agent("wms_assistant")
    assert isinstance(loaded, LlmAgent)
    assert loaded.name == AGENT_NAME


async def test_adk_eval_loader_finds_the_agent(
    monkeypatch: pytest.MonkeyPatch, db_path: Path
) -> None:
    """`adk eval agents/wms_assistant ...` imports the package's __init__.py by path."""
    from google.adk.cli.cli_eval import get_app_or_root_agent

    monkeypatch.setenv("WMS_DB_PATH", str(db_path))
    sys.modules.pop("wms_assistant.agent", None)
    app, root_agent = await get_app_or_root_agent(str(AGENT_DIR))
    assert app is None
    assert isinstance(root_agent, LlmAgent)
    assert root_agent.name == AGENT_NAME
