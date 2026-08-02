"""Base host-management tools.

Every tool follows the Local-MCP-Servers folio discipline (BP-001 §3a):

  * a docstring (surfaced to the MCP client),
  * JSON-serializable returns,
  * **never raise — return ``{"error": "..."}``** on any failure,
  * ``ping`` is defined first and called first by the test artifact.

The functions here take their dependencies explicitly (a :class:`Config`, an
:class:`AuditLog`, a plugin registry) so they can be unit-tested with a mocked
subprocess / filesystem (T1). ``server.py`` binds them into FastMCP tools.

``subprocess`` is referenced at module level (``subprocess.run``) so tests can
monkeypatch it.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from ..audit import AuditLog
from ..config import Config
from ..security import is_destructive

_START_MONOTONIC = time.monotonic()

# Actions permitted by service_control.
_SERVICE_ACTIONS = {"start", "stop", "restart", "status"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _within_roots(path: str, roots: list[str]) -> bool:
    """True if ``path`` resolves to a location inside one of ``roots``."""
    try:
        resolved = Path(path).resolve()
    except (OSError, RuntimeError):
        return False
    for root in roots:
        try:
            root_resolved = Path(root).resolve()
        except (OSError, RuntimeError):
            continue
        if resolved == root_resolved or root_resolved in resolved.parents:
            return True
    return False


# --------------------------------------------------------------------------- #
# ping — defined first, called first
# --------------------------------------------------------------------------- #
def ping(config: Config, plugins: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Health check. Returns agent identity, bound Tailscale IP, plugins, uptime."""
    from .. import __version__

    return {
        "name": "gdv-node-agent",
        "version": __version__,
        "tailscale_ip": config.host,
        "plugins": plugins or [],
        "uptime_s": round(time.monotonic() - _START_MONOTONIC, 3),
    }


# --------------------------------------------------------------------------- #
# run_command — audited, destructive-blocked, optional allowlist
# --------------------------------------------------------------------------- #
def run_command(
    cmd: str,
    timeout_s: int = 60,
    *,
    config: Config,
    audit: AuditLog,
) -> dict[str, Any]:
    """Run a shell command on the host. Audited; destructive patterns are blocked.

    Returns ``{"exit_code", "stdout", "stderr"}`` on completion, or
    ``{"error": ...}`` if blocked, timed out, or failed to launch.
    """
    blocked, reason = is_destructive(cmd)
    if blocked:
        audit.record(tool="run_command", args={"cmd": cmd}, outcome="blocked", reason=reason)
        return {"error": f"blocked destructive command: {reason}"}

    if config.command_allowlist:
        first = (cmd.strip().split() or [""])[0].rsplit("/", 1)[-1]
        if first not in config.command_allowlist:
            audit.record(tool="run_command", args={"cmd": cmd}, outcome="not-allowlisted")
            return {"error": f"command {first!r} is not in the allowlist"}

    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        audit.record(tool="run_command", args={"cmd": cmd}, outcome="timeout")
        return {"error": f"command timed out after {timeout_s}s"}
    except (OSError, ValueError) as exc:
        audit.record(tool="run_command", args={"cmd": cmd}, outcome="error")
        return {"error": str(exc)}

    audit.record(
        tool="run_command", args={"cmd": cmd}, outcome="ran", exit_code=proc.returncode
    )
    return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


# --------------------------------------------------------------------------- #
# read_file / write_file — scoped to allowed roots
# --------------------------------------------------------------------------- #
def read_file(path: str, *, config: Config) -> dict[str, Any]:
    """Read a UTF-8 text file, scoped to the configured read roots."""
    if not _within_roots(path, config.read_roots):
        return {"error": f"path {path!r} is outside the allowed read roots"}
    try:
        content = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"error": str(exc)}
    return {"path": path, "content": content}


def write_file(
    path: str, content: str, *, config: Config, audit: AuditLog
) -> dict[str, Any]:
    """Write a UTF-8 text file, scoped to the configured write roots. Audited."""
    if not _within_roots(path, config.write_roots):
        audit.record(
            tool="write_file", args={"path": path}, outcome="denied-scope"
        )
        return {"error": f"path {path!r} is outside the allowed write roots"}
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        written = target.write_text(content, encoding="utf-8")
    except OSError as exc:
        audit.record(tool="write_file", args={"path": path}, outcome="error")
        return {"error": str(exc)}
    audit.record(tool="write_file", args={"path": path}, outcome="wrote", bytes=written)
    return {"path": path, "bytes": written}


# --------------------------------------------------------------------------- #
# service_control / tail_logs — unit allowlist, journalctl-backed
# --------------------------------------------------------------------------- #
def service_control(
    unit: str, action: str, *, config: Config, audit: AuditLog
) -> dict[str, Any]:
    """start/stop/restart/status a systemd unit from the configured allowlist."""
    if action not in _SERVICE_ACTIONS:
        return {"error": f"action must be one of {sorted(_SERVICE_ACTIONS)}"}
    if unit not in config.service_units:
        audit.record(
            tool="service_control", args={"unit": unit, "action": action},
            outcome="denied-unit",
        )
        return {"error": f"unit {unit!r} is not in the service allowlist"}

    if action != "status":
        try:
            subprocess.run(
                [*config.sudo_prefix, "systemctl", action, unit],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            audit.record(
                tool="service_control", args={"unit": unit, "action": action},
                outcome="error",
            )
            return {"error": str(exc)}

    active = _is_active(unit, config)
    audit.record(
        tool="service_control", args={"unit": unit, "action": action},
        outcome="ok", active=active,
    )
    return {"unit": unit, "action": action, "active": active}


def _is_active(unit: str, config: Config) -> bool:
    try:
        proc = subprocess.run(
            [*config.sudo_prefix, "systemctl", "is-active", unit],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.stdout.strip() == "active"


def tail_logs(unit: str, lines: int = 200, *, config: Config) -> dict[str, Any]:
    """Return the last ``lines`` journal lines for an allowlisted unit."""
    if unit not in config.service_units:
        return {"error": f"unit {unit!r} is not in the service allowlist"}
    try:
        lines = max(1, min(int(lines), 5000))
    except (TypeError, ValueError):
        lines = 200
    try:
        proc = subprocess.run(
            [*config.sudo_prefix, "journalctl", "-u", unit, "-n", str(lines), "--no-pager"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": str(exc)}
    if proc.returncode != 0:
        return {"error": proc.stderr.strip() or "journalctl failed"}
    out_lines = proc.stdout.splitlines()
    return {"unit": unit, "lines": out_lines}
