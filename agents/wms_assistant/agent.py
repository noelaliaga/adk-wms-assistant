"""Entry point for the ADK CLI (`adk web`, `adk run`, `adk eval`).

ADK imports this module and looks for ``root_agent``. Configuration comes from
the environment (see config.py). A missing database stops the import with a
clear message instead of starting an agent whose tools all fail.
"""

from __future__ import annotations

import os

from wms_assistant.config import ConfigError, Settings
from wms_assistant.factory import build_agent

settings = Settings.from_env(os.environ)
if not settings.db_path.is_file():
    raise ConfigError(
        f"WMS database not found at {settings.db_path}. Run `make seed` "
        "or set WMS_DB_PATH to a database created with mcp-logistica's wms-seed."
    )

root_agent = build_agent(settings)
