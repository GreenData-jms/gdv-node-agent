"""Load VERIFIED plugins and register their tools.

Only called for records that already passed :func:`loader.verify_plugin` — the
T5 contract is that unverified plugin code is never imported. A plugin is a
directory with a ``manifest.json`` whose ``entrypoint`` module defines::

    def register(mcp, ctx):
        @mcp.tool
        def hermes_install(...): ...

``ctx`` is a :class:`PluginContext` giving the plugin the shared config, audit
log, and the base tools (so plugins drive the host through the same audited,
destructive-blocked primitives rather than importing subprocess directly).
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..audit import AuditLog
from ..config import Config
from ..tools import base as base_tools

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from .loader import PluginRecord


@dataclass
class PluginContext:
    """Handed to each plugin's ``register`` function."""

    config: Config
    audit: AuditLog

    def run_command(self, cmd: str, timeout_s: int = 60) -> dict[str, Any]:
        """Run a host command through the audited, destructive-blocked primitive."""
        return base_tools.run_command(
            cmd, timeout_s, config=self.config, audit=self.audit
        )

    def service_control(self, unit: str, action: str) -> dict[str, Any]:
        return base_tools.service_control(
            unit, action, config=self.config, audit=self.audit
        )

    def tail_logs(self, unit: str, lines: int = 200) -> dict[str, Any]:
        return base_tools.tail_logs(unit, lines, config=self.config)


def load_plugin(
    record: "PluginRecord",
    mcp: "FastMCP",
    *,
    config: Config,
    audit: AuditLog,
) -> bool:
    """Import a verified plugin's entrypoint and call ``register``. Never raises."""
    if not record.verified:
        return False
    entrypoint = record.entrypoint or "plugin.py"
    module_path = record.path / entrypoint
    if not module_path.is_file():
        return False

    mod_name = f"gdv_node_agent.plugins._loaded.{record.name}"
    try:
        spec = importlib.util.spec_from_file_location(mod_name, module_path)
        if spec is None or spec.loader is None:
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        register = getattr(module, "register", None)
        if register is None:
            return False
        register(mcp, PluginContext(config=config, audit=audit))
        return True
    except Exception as exc:  # a bad plugin must not take the agent down
        import sys

        print(
            f"[gdv-node-agent] WARNING: failed to load plugin {record.name!r}: {exc}",
            file=sys.stderr,
        )
        return False
