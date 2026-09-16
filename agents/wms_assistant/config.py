"""Settings read from the environment. Unknown values are rejected, never guessed.

    WMS_MODEL_BACKEND   gemini (default) | litellm
    WMS_MODEL           model id. Default for gemini: ADK's default Gemini model.
                        A "provider/model" id with the gemini backend is rejected
                        (only Vertex "projects/..." resource names may contain "/").
                        Required for litellm, with a provider prefix, e.g.
                        "anthropic/<model>" or "openai/<model>".
    WMS_WRITE_POLICY    off (default) | dry_run | on
    WMS_DB_PATH         SQLite file created by mcp-logistica's `wms-seed`
                        (default: data/wms.sqlite, resolved against the cwd)
    WMS_MCP_COMMAND     command that starts the mcp-logistica server on stdio
                        (default: this interpreter with `-m wms_mcp.server`)
    WMS_MCP_TIMEOUT_S   seconds to wait for an MCP request, connection included
                        (default: 30)

Model credentials (GOOGLE_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, ...) are
read by the model SDKs themselves. This module never reads them.
"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from google.adk.agents import LlmAgent


class ConfigError(ValueError):
    """A setting is missing or outside its closed vocabulary."""


class ModelBackend(StrEnum):
    GEMINI = "gemini"
    LITELLM = "litellm"


class WritePolicy(StrEnum):
    OFF = "off"
    DRY_RUN = "dry_run"
    ON = "on"


# The Gemini model ADK itself defaults to in the installed version. Pinning our
# own id here would go stale with every Gemini release.
DEFAULT_GEMINI_MODEL: str = LlmAgent.DEFAULT_MODEL
DEFAULT_DB_PATH = Path("data/wms.sqlite")
# Starting the Python server and importing the SDK takes about a second
# locally; leave room for a cold CI runner.
DEFAULT_MCP_TIMEOUT_S = 30.0

E = TypeVar("E", bound=StrEnum)


def _choice(enum: type[E], name: str, raw: str | None, default: E) -> E:
    if raw is None or raw == "":
        return default
    try:
        return enum(raw)
    except ValueError:
        valid = ", ".join(e.value for e in enum)
        raise ConfigError(f"{name}={raw!r} is not valid; expected one of: {valid}") from None


@dataclass(frozen=True)
class Settings:
    backend: ModelBackend
    model: str
    write_policy: WritePolicy
    db_path: Path
    server_command: tuple[str, ...]
    mcp_timeout_s: float = DEFAULT_MCP_TIMEOUT_S

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        backend = _choice(
            ModelBackend, "WMS_MODEL_BACKEND", env.get("WMS_MODEL_BACKEND"), ModelBackend.GEMINI
        )
        model = env.get("WMS_MODEL", "").strip()
        if backend is ModelBackend.GEMINI:
            model = model or DEFAULT_GEMINI_MODEL
            # "provider/model" is a LiteLLM id. Vertex resource names
            # ("projects/.../models/...") are the only Gemini ids with a slash.
            if "/" in model and not model.startswith("projects/"):
                raise ConfigError(
                    f"WMS_MODEL={model!r} looks like a LiteLLM id; set "
                    "WMS_MODEL_BACKEND=litellm to use it, or give a Gemini model id"
                )
        elif not model:
            raise ConfigError(
                "WMS_MODEL_BACKEND=litellm needs WMS_MODEL with a provider prefix, "
                "e.g. 'anthropic/<model>' or 'openai/<model>'"
            )
        elif "/" not in model:
            raise ConfigError(
                f"WMS_MODEL={model!r} has no provider prefix; LiteLLM model ids look "
                "like 'anthropic/<model>' or 'openai/<model>'"
            )

        policy = _choice(
            WritePolicy, "WMS_WRITE_POLICY", env.get("WMS_WRITE_POLICY"), WritePolicy.OFF
        )

        raw_db = env.get("WMS_DB_PATH", "").strip()
        db_path = (Path(raw_db) if raw_db else DEFAULT_DB_PATH).expanduser().resolve()

        raw_cmd = env.get("WMS_MCP_COMMAND", "").strip()
        command = (
            tuple(shlex.split(raw_cmd)) if raw_cmd else (sys.executable, "-m", "wms_mcp.server")
        )

        raw_timeout = env.get("WMS_MCP_TIMEOUT_S", "").strip()
        timeout = DEFAULT_MCP_TIMEOUT_S
        if raw_timeout:
            try:
                timeout = float(raw_timeout)
            except ValueError:
                timeout = -1.0
            if not 0 < timeout <= 600:
                raise ConfigError(
                    f"WMS_MCP_TIMEOUT_S={raw_timeout!r} is not valid; expected seconds in (0, 600]"
                )

        return cls(
            backend=backend,
            model=model,
            write_policy=policy,
            db_path=db_path,
            server_command=command,
            mcp_timeout_s=timeout,
        )
