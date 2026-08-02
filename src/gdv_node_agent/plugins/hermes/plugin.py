"""The ``hermes`` plugin — provision and manage Hermes + LiteLLM through the agent.

Design (ADR-002): the control plane (this agent, running as ``nodeagent``) does
NOT host the workload. Hermes is provisioned and run under its OWN identity
(user ``hermes``, state ``/var/lib/hermes``) by the hardened ``hermes-install``
systemd oneshot (see ``deploy/hermes-install.service`` + ``deploy/hermes-provision.sh``).
The agent only ORCHESTRATES that unit through the same scoped, audited
``service_control`` primitive it uses for every other unit — it never runs an
unauthenticated ``curl | bash`` inside its own sandbox, and by design cannot even
read the workload's files. Version provenance therefore comes from the unit's own
journal, not from exec'ing the workload binary.

Verbs:
  * ``hermes.install``  — ensure Hermes is provisioned (start the oneshot; idempotent)
  * ``hermes.upgrade``  — re-run the provisioner to move to a newly-pinned release
  * ``hermes.restart``  — restart the Hermes gateway unit (after ``hermes gateway install``)
  * ``litellm.control`` — start/stop/restart/status the LiteLLM unit
  * ``hermes.skills_pr_status`` — surface the skills-as-git PR queue

Every tool drives the host through the :class:`PluginContext` primitives, so all
host actions go through the same **audited, scoped** path as the base tools — the
plugin never touches ``subprocess`` directly.
"""

from __future__ import annotations

import re
from typing import Any

# Pinned per EL-02 / the task ground truth. MUST match hermes-install.service's
# HERMES_EXPECTED_VERSION. Upgrades bump this (and the unit's pin) deliberately.
HERMES_VERSION = "0.19.1"
# The hardened oneshot that provisions Hermes under the `hermes` workload user.
PROVISION_UNIT = "hermes-install"

_LITELLM_ACTIONS = {"start", "stop", "restart", "status"}
_VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+)\b")


def _provisioned_version(ctx) -> str | None:
    """Parse the provisioner's journal for the version it last reported.

    The agent cannot exec the workload binary (separate identity + 0750 state),
    so version provenance comes from the unit's audited logs, not ``hermes --version``.
    """
    res = ctx.tail_logs(PROVISION_UNIT, lines=200)
    if not isinstance(res, dict) or "error" in res:
        return None
    for line in reversed(res.get("lines", []) or []):
        if "provisioned OK" in line or "already present" in line:
            m = _VERSION_RE.search(line)
            if m:
                return m.group(1)
    return None


def register(mcp, ctx) -> None:
    """Register the hermes/litellm tools on the FastMCP app."""

    @mcp.tool(name="hermes.install")
    def hermes_install() -> dict[str, Any]:
        """Ensure Hermes is provisioned (pinned) under its workload identity.

        Triggers the hardened ``hermes-install`` oneshot via scoped systemctl and
        reports whether it is active. Idempotent — the oneshot skips if the pinned
        version is already present.
        """
        res = ctx.service_control(PROVISION_UNIT, "start")
        if "error" in res:
            return {"status": "error", "error": res["error"]}
        active = bool(res.get("active"))
        version = _provisioned_version(ctx)
        return {
            "status": "provisioned" if active else "failed",
            "unit": PROVISION_UNIT,
            "active": active,
            "version": version,
            "expected": HERMES_VERSION,
            "version_ok": version == HERMES_VERSION,
        }

    @mcp.tool(name="hermes.upgrade")
    def hermes_upgrade() -> dict[str, Any]:
        """Re-run the provisioner (restart the oneshot) to move to the pinned release.

        Bump the pin in ``hermes-install.service`` first; this reinstalls to match.
        """
        before = _provisioned_version(ctx)
        res = ctx.service_control(PROVISION_UNIT, "restart")
        if "error" in res:
            return {"status": "error", "error": res["error"]}
        active = bool(res.get("active"))
        after = _provisioned_version(ctx)
        return {
            "status": "upgraded" if active else "failed",
            "unit": PROVISION_UNIT,
            "active": active,
            "from": before,
            "to": after,
            "expected": HERMES_VERSION,
        }

    @mcp.tool(name="hermes.restart")
    def hermes_restart() -> dict[str, Any]:
        """Restart the Hermes gateway systemd unit (after ``hermes gateway install``)."""
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
