from __future__ import annotations

import socket
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from wms_mcp.db import create_database
from wms_mcp.seed import seed

from wms_assistant.config import Settings

REPO = Path(__file__).resolve().parents[1]
SettingsFactory = Callable[..., Settings]


class NetworkBlockedError(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any TCP/UDP connection or DNS lookup made by the test process.

    Unix sockets stay allowed (asyncio uses them internally). The MCP servers
    are child processes that talk over pipes; this guard does not reach into
    them (they never get model keys, see test_server_env_end_to_end.py).
    """
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def refuse_inet(sock: socket.socket, address: object) -> None:
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise NetworkBlockedError(f"network access attempted in a test: {address!r}")

    def guarded(self: socket.socket, address: Any) -> None:
        refuse_inet(self, address)
        original_connect(self, address)

    def guarded_ex(self: socket.socket, address: Any) -> int:
        refuse_inet(self, address)
        return original_connect_ex(self, address)

    def no_dns(host: object, *args: Any, **kwargs: Any) -> Any:
        raise NetworkBlockedError(f"DNS lookup attempted in a test: {host!r}")

    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
    monkeypatch.setattr(socket.socket, "connect", guarded)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_ex)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never see the developer's WMS_* settings or model keys."""
    for name in (
        "WMS_MODEL_BACKEND",
        "WMS_MODEL",
        "WMS_WRITE_POLICY",
        "WMS_DB_PATH",
        "WMS_MCP_COMMAND",
        "WMS_MCP_TIMEOUT_S",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A fresh synthetic WMS database created by mcp-logistica's own seed."""
    path = tmp_path / "wms.sqlite"
    with closing(create_database(path)) as conn:
        seed(conn, datetime.now(UTC))
    return path


@pytest.fixture
def make_settings(db_path: Path) -> SettingsFactory:
    def factory(**env: str) -> Settings:
        return Settings.from_env({"WMS_DB_PATH": str(db_path), **env})

    return factory
