"""Record the environment an MCP server process really gets, then become the server.

Usage (as WMS_MCP_COMMAND): python env_probe_server.py <output-file>
Writes the sorted variable names (not values) to <output-file>, then replaces
itself with ``python -m wms_mcp.server`` so the MCP handshake still works.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if __name__ == "__main__":
    Path(sys.argv[1]).write_text("\n".join(sorted(os.environ)) + "\n", encoding="utf-8")
    os.execv(sys.executable, [sys.executable, "-m", "wms_mcp.server"])  # noqa: S606
