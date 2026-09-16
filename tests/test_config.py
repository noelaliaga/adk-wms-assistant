from __future__ import annotations

import sys
from pathlib import Path

import pytest

from wms_assistant.config import (
    DEFAULT_GEMINI_MODEL,
    ConfigError,
    ModelBackend,
    Settings,
    WritePolicy,
)


def test_defaults_are_gemini_and_writes_off() -> None:
    settings = Settings.from_env({})
    assert settings.backend is ModelBackend.GEMINI
    assert settings.model == DEFAULT_GEMINI_MODEL
    assert settings.write_policy is WritePolicy.OFF
    assert settings.db_path == (Path.cwd() / "data" / "wms.sqlite").resolve()
    assert settings.server_command == (sys.executable, "-m", "wms_mcp.server")
    assert settings.mcp_timeout_s == 30.0


def test_gemini_model_can_be_overridden() -> None:
    settings = Settings.from_env({"WMS_MODEL": "gemini-some-other-model"})
    assert settings.model == "gemini-some-other-model"


def test_gemini_accepts_a_vertex_resource_name() -> None:
    name = "projects/example-project/locations/europe-west1/publishers/google/models/some-model"
    assert Settings.from_env({"WMS_MODEL": name}).model == name


@pytest.mark.parametrize("model", ["anthropic/some-claude-model", "openai/some-gpt-model"])
def test_litellm_backend_takes_a_prefixed_model(model: str) -> None:
    settings = Settings.from_env({"WMS_MODEL_BACKEND": "litellm", "WMS_MODEL": model})
    assert (settings.backend, settings.model) == (ModelBackend.LITELLM, model)


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"WMS_MODEL_BACKEND": "litellm"}, "needs WMS_MODEL"),
        ({"WMS_MODEL_BACKEND": "litellm", "WMS_MODEL": "claude"}, "no provider prefix"),
        ({"WMS_MODEL_BACKEND": "vertex"}, "WMS_MODEL_BACKEND='vertex' is not valid"),
        ({"WMS_MODEL_BACKEND": "Gemini"}, "is not valid"),
        ({"WMS_WRITE_POLICY": "ON"}, "WMS_WRITE_POLICY='ON' is not valid"),
        ({"WMS_WRITE_POLICY": "true"}, "expected one of: off, dry_run, on"),
        ({"WMS_MCP_TIMEOUT_S": "0"}, "WMS_MCP_TIMEOUT_S='0' is not valid"),
        ({"WMS_MCP_TIMEOUT_S": "soon"}, "expected seconds"),
        ({"WMS_MODEL": "anthropic/some-claude-model"}, "set WMS_MODEL_BACKEND=litellm"),
    ],
)
def test_unknown_values_are_rejected_not_guessed(env: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        Settings.from_env(env)


def test_server_command_is_split_like_a_shell(tmp_path: Path) -> None:
    exe = tmp_path / "dir with space" / "wms-mcp"
    settings = Settings.from_env({"WMS_MCP_COMMAND": f"'{exe}' --flag"})
    assert settings.server_command == (str(exe), "--flag")


def test_relative_db_path_is_resolved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings.from_env({"WMS_DB_PATH": "sub/wms.sqlite"})
    assert settings.db_path == (tmp_path / "sub" / "wms.sqlite").resolve()


def test_the_suite_cannot_open_network_connections() -> None:
    import socket

    from conftest import NetworkBlockedError

    with socket.socket() as sock, pytest.raises(NetworkBlockedError):
        sock.connect(("192.0.2.1", 443))  # TEST-NET-1, never routed
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.com", 443)
