"""Runtime configuration, loaded from environment variables.

Secrets are never read from the repo. The auth token comes from
``GDV_AGENT_TOKEN`` or, preferably, ``GDV_AGENT_TOKEN_FILE`` (a ``0600``
root-owned file written by the bootstrap). Provider keys (Anthropic/NVIDIA/
Google) are never handled here — they belong to LiteLLM's environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"
DEFAULT_MCP_PATH = "/mcp/"
DEFAULT_AUDIT_LOG = "/var/log/gdv-node-agent/audit.jsonl"

# Conservative default scopes for file/service tools. Overridable via env.
DEFAULT_READ_ROOTS = ["/etc", "/var/log", "/opt", "/home", "/tmp"]
DEFAULT_WRITE_ROOTS = ["/opt", "/tmp"]
DEFAULT_SERVICE_UNITS = ["hermes", "litellm", "gdv-node-agent"]


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(os.pathsep) if item.strip()]


@dataclass
class Config:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    mcp_path: str = DEFAULT_MCP_PATH
    token: str = ""
    audit_log_path: str = DEFAULT_AUDIT_LOG
    read_roots: list[str] = field(default_factory=lambda: list(DEFAULT_READ_ROOTS))
    write_roots: list[str] = field(default_factory=lambda: list(DEFAULT_WRITE_ROOTS))
    service_units: list[str] = field(default_factory=lambda: list(DEFAULT_SERVICE_UNITS))
    # Optional positive allowlist for run_command's first token. Empty = denylist-only.
    command_allowlist: list[str] = field(default_factory=list)
    plugins_dir: str = ""
    plugin_allowlist: list[str] = field(default_factory=list)
    # When the agent runs as the non-root `nodeagent` user (production), systemd
    # unit control and journalctl need scoped sudo. The bootstrap writes a
    # NOPASSWD sudoers entry for exactly these commands and sets GDV_AGENT_USE_SUDO=1.
    use_sudo: bool = False

    @property
    def sudo_prefix(self) -> list[str]:
        return ["sudo", "-n"] if self.use_sudo else []

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        env = dict(os.environ if env is None else env)

        token = env.get("GDV_AGENT_TOKEN", "")
        token_file = env.get("GDV_AGENT_TOKEN_FILE")
        if not token and token_file:
            token = _read_token_file(token_file)

        default_plugins_dir = str(Path(__file__).resolve().parent / "plugins")

        return cls(
            host=env.get("GDV_AGENT_HOST", DEFAULT_HOST),
            port=int(env.get("GDV_AGENT_PORT", DEFAULT_PORT)),
            mcp_path=env.get("GDV_AGENT_MCP_PATH", DEFAULT_MCP_PATH),
            token=token,
            audit_log_path=env.get("GDV_AGENT_AUDIT_LOG", DEFAULT_AUDIT_LOG),
            read_roots=_split(env.get("GDV_AGENT_READ_ROOTS")) or list(DEFAULT_READ_ROOTS),
            write_roots=_split(env.get("GDV_AGENT_WRITE_ROOTS")) or list(DEFAULT_WRITE_ROOTS),
            service_units=_split(env.get("GDV_AGENT_SERVICE_UNITS")) or list(DEFAULT_SERVICE_UNITS),
            command_allowlist=_split(env.get("GDV_AGENT_COMMAND_ALLOWLIST")),
            plugins_dir=env.get("GDV_AGENT_PLUGINS_DIR", default_plugins_dir),
            plugin_allowlist=_split(env.get("GDV_AGENT_PLUGIN_ALLOWLIST")) or ["hermes"],
            use_sudo=env.get("GDV_AGENT_USE_SUDO", "").lower() in {"1", "true", "yes"},
        )


def _read_token_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
