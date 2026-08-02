"""Server assembly smoke test — tools register, no network is touched."""

from __future__ import annotations

import asyncio

from gdv_node_agent.config import Config
from gdv_node_agent.server import build_server


def _tool_names(mcp):
    tools = asyncio.run(mcp.list_tools())
    return {t.name for t in tools}


def test_base_tools_registered(tmp_path):
    cfg = Config(
        host="127.0.0.1",
        token="abc",
        plugins_dir=str(tmp_path / "plugins"),
        plugin_allowlist=[],
    )
    mcp = build_server(cfg)
    names = _tool_names(mcp)
    for expected in [
        "ping",
        "run_command",
        "read_file",
        "write_file",
        "service_control",
        "tail_logs",
        "list_plugins",
    ]:
        assert expected in names, f"missing tool {expected}"
