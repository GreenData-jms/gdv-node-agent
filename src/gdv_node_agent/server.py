"""FastMCP server assembly.

Wires the security core (bind guard, bearer auth, destructive block, plugin
loader) into a FastMCP remote HTTP/SSE app (D-24) and registers the base tools
plus any verified plugin tools.

The *hard gate* runs in :func:`build_server` / :func:`serve` before the listener
is ever created:

  * ``assert_bind_allowed`` — refuse to start unless bound to Tailscale/loopback (T2)
  * a non-empty auth token is required — refuse to start otherwise (T3)

Nothing here reaches the network at import time; ``build_server`` constructs the
object graph and ``serve`` starts the listener.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from . import __version__
from .audit import AuditLog, current_caller
from .auth import StaticTokenVerifier
from .bind_guard import assert_bind_allowed
from .config import Config
from .plugins.loader import PluginRegistry
from .tools import base as base_tools


class MissingTokenError(RuntimeError):
    """Raised when the agent is started without an auth token (T3 hard gate)."""


def build_registry(config: Config) -> PluginRegistry:
    registry = PluginRegistry(config.plugins_dir, config.plugin_allowlist)
    registry.discover()
    return registry


def build_server(config: Config, *, registry: PluginRegistry | None = None) -> FastMCP:
    """Construct the FastMCP app with auth + tools. Enforces the T2/T3 hard gates.

    Raises :class:`bind_guard.BindGuardError` for a bad bind address and
    :class:`MissingTokenError` when no token is configured — both *before* any
    listener exists.
    """
    # --- HARD GATES (must pass before we build anything network-facing) ---
    assert_bind_allowed(config.host)  # T2
    if not config.token:
        raise MissingTokenError(
            "no auth token configured; set GDV_AGENT_TOKEN or GDV_AGENT_TOKEN_FILE "
            "(the bootstrap generates one on the host)"
        )

    registry = registry if registry is not None else build_registry(config)
    audit = AuditLog(config.audit_log_path)
    verifier = StaticTokenVerifier(config.token)

    mcp = FastMCP(name="gdv-node-agent", version=__version__, auth=verifier)

    _register_base_tools(mcp, config, audit, registry)
    _register_plugin_tools(mcp, config, audit, registry)
    return mcp


def _register_base_tools(
    mcp: FastMCP, config: Config, audit: AuditLog, registry: PluginRegistry
) -> None:
    @mcp.tool
    def ping() -> dict[str, Any]:
        """Health check: agent identity, Tailscale IP, loaded plugins, uptime."""
        return base_tools.ping(config, registry.summaries())

    @mcp.tool
    def run_command(cmd: str, timeout_s: int = 60) -> dict[str, Any]:
        """Run a shell command on the host (audited; destructive patterns blocked)."""
        return base_tools.run_command(cmd, timeout_s, config=config, audit=audit)

    @mcp.tool
    def read_file(path: str) -> dict[str, Any]:
        """Read a UTF-8 text file, scoped to the configured read roots."""
        return base_tools.read_file(path, config=config)

    @mcp.tool
    def write_file(path: str, content: str) -> dict[str, Any]:
        """Write a UTF-8 text file, scoped to the configured write roots (audited)."""
        return base_tools.write_file(path, content, config=config, audit=audit)

    @mcp.tool
    def service_control(unit: str, action: str) -> dict[str, Any]:
        """start/stop/restart/status an allowlisted systemd unit."""
        return base_tools.service_control(unit, action, config=config, audit=audit)

    @mcp.tool
    def tail_logs(unit: str, lines: int = 200) -> dict[str, Any]:
        """Return the last N journal lines for an allowlisted unit."""
        return base_tools.tail_logs(unit, lines, config=config)

    @mcp.tool
    def list_plugins() -> list[dict[str, Any]]:
        """List discovered plugins with their verification status."""
        registry.discover()
        return registry.summaries()


def _register_plugin_tools(
    mcp: FastMCP, config: Config, audit: AuditLog, registry: PluginRegistry
) -> None:
    """Import and register tools from every VERIFIED plugin.

    Unverified plugins (altered/unsigned/unlisted) are never imported — the T5
    contract. Each verified plugin exposes ``register(mcp, ctx)``.
    """
    from .plugins import runtime

    for record in registry.verified_records():
        runtime.load_plugin(record, mcp, config=config, audit=audit)


def serve(config: Config | None = None) -> None:  # pragma: no cover - network entry
    """Build and run the agent over remote HTTP/SSE, bound to Tailscale/loopback."""
    config = config or Config.from_env()
    mcp = build_server(config)
    mcp.run(
        transport="http",
        host=config.host,
        port=config.port,
        path=config.mcp_path,
    )
