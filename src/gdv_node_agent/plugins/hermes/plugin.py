"""The ``hermes`` plugin — install and manage Hermes + LiteLLM through the agent.

This is the first per-workload capability module (ADR-002 §2 / BP-001 Step 5).
It brings the verbs the orchestrator needs to stand Hermes up on a node:

  * ``hermes.install``  — idempotent install of the pinned Hermes release
  * ``hermes.upgrade``  — re-run the installer to move to the current release
  * ``hermes.restart``  — restart the Hermes systemd unit
  * ``litellm.control`` — start/stop/restart/status the LiteLLM unit
  * ``hermes.skills_pr_status`` — surface the skills-as-git PR queue

Every tool drives the host through the :class:`PluginContext` primitives, so all
host commands go through the same **audited, destructive-blocked** path as the
base ``run_command`` — the plugin never touches ``subprocess`` directly.
"""

from __future__ import annotations

from typing import Any

# Pinned per EL-02 / the task ground truth. Upgrades bump this deliberately.
HERMES_VERSION = "0.19.1"
HERMES_INSTALL_CMD = (
    "curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash"
)
# Installer pulls uv/Python/Node/ripgrep/ffmpeg — allow a generous timeout.
INSTALL_TIMEOUT_S = 900

_LITELLM_ACTIONS = {"start", "stop", "restart", "status"}


def _installed_version(ctx) -> str | None:
    """Return the installed Hermes version string, or None if not installed."""
    res = ctx.run_command("hermes --version", timeout_s=30)
    if "error" in res or res.get("exit_code") != 0:
        return None
    # `hermes --version` prints e.g. "hermes 0.19.1" or "0.19.1"
    out = (res.get("stdout") or "").strip()
    return out.split()[-1] if out else None


def register(mcp, ctx) -> None:
    """Register the hermes/litellm tools on the FastMCP app."""

    @mcp.tool(name="hermes.install")
    def hermes_install() -> dict[str, Any]:
        """Install Hermes (pinned) if absent. Idempotent — skips if already present."""
        current = _installed_version(ctx)
        if current == HERMES_VERSION:
            return {"status": "already-installed", "version": current}

        res = ctx.run_command(HERMES_INSTALL_CMD, timeout_s=INSTALL_TIMEOUT_S)
        if "error" in res:
            return {"status": "error", "error": res["error"]}
        if res.get("exit_code") != 0:
            return {
                "status": "error",
                "exit_code": res.get("exit_code"),
                "stderr": res.get("stderr", ""),
            }

        installed = _installed_version(ctx)
        return {
            "status": "installed" if current is None else "reinstalled",
            "version": installed,
            "expected": HERMES_VERSION,
            "version_ok": installed == HERMES_VERSION,
        }

    @mcp.tool(name="hermes.upgrade")
    def hermes_upgrade() -> dict[str, Any]:
        """Re-run the Hermes installer to move to the current pinned release."""
        before = _installed_version(ctx)
        res = ctx.run_command(HERMES_INSTALL_CMD, timeout_s=INSTALL_TIMEOUT_S)
        if "error" in res:
            return {"status": "error", "error": res["error"]}
        if res.get("exit_code") != 0:
            return {
                "status": "error",
                "exit_code": res.get("exit_code"),
                "stderr": res.get("stderr", ""),
            }
        after = _installed_version(ctx)
        return {"status": "upgraded", "from": before, "to": after}

    @mcp.tool(name="hermes.restart")
    def hermes_restart() -> dict[str, Any]:
        """Restart the Hermes systemd unit."""
        return ctx.service_control("hermes", "restart")

    @mcp.tool(name="litellm.control")
    def litellm_control(action: str) -> dict[str, Any]:
        """start/stop/restart/status the LiteLLM systemd unit."""
        if action not in _LITELLM_ACTIONS:
            return {"error": f"action must be one of {sorted(_LITELLM_ACTIONS)}"}
        return ctx.service_control("litellm", action)

    @mcp.tool(name="hermes.skills_pr_status")
    def hermes_skills_pr_status() -> dict[str, Any]:
        """Surface the skills-as-git PR queue (Hermes learning-loop provenance)."""
        res = ctx.run_command("hermes skills status", timeout_s=60)
        if "error" in res:
            return {"status": "error", "error": res["error"]}
        return {
            "status": "ok",
            "exit_code": res.get("exit_code"),
            "output": res.get("stdout", ""),
        }
