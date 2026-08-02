"""Unit tests for the hermes plugin (no host contact — ctx primitives are faked)."""

from __future__ import annotations

import asyncio

import pytest

from gdv_node_agent.config import Config
from gdv_node_agent.plugins import hermes as hermes_pkg
from gdv_node_agent.plugins.hermes import plugin as hermes_plugin
from gdv_node_agent.plugins.loader import verify_plugin
from gdv_node_agent.server import build_server


class FakeMCP:
    """Captures tools registered by a plugin's register()."""

    def __init__(self):
        self.tools = {}

    def tool(self, *args, name=None, **kwargs):
        def deco(fn):
            self.tools[name or fn.__name__] = fn
            return fn

        # support both @mcp.tool and @mcp.tool(name=...)
        if args and callable(args[0]):
            fn = args[0]
            self.tools[name or fn.__name__] = fn
            return fn
        return deco


class FakeCtx:
    """Fakes the PluginContext primitives the plugin orchestrates through.

    The plugin never execs the workload; it drives the ``hermes-install`` unit via
    ``service_control`` and reads the version back from ``tail_logs`` (the journal).
    """

    def __init__(self, active=True, journal_version="0.19.1"):
        self.commands = []
        self.services = []
        self.active = active
        self.journal_version = journal_version

    def run_command(self, cmd, timeout_s=60):
        self.commands.append(cmd)
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    def service_control(self, unit, action):
        self.services.append((unit, action))
        return {"unit": unit, "action": action, "active": self.active}

    def tail_logs(self, unit, lines=200):
        if self.journal_version is None:
            return {"unit": unit, "lines": []}
        return {
            "unit": unit,
            "lines": [
                "[hermes-provision] provisioning hermes into /var/lib/hermes",
                f"[hermes-provision] hermes {self.journal_version} provisioned OK",
            ],
        }


def _register(**ctx_kwargs):
    mcp = FakeMCP()
    ctx = FakeCtx(**ctx_kwargs)
    hermes_plugin.register(mcp, ctx)
    return mcp, ctx


def test_registers_expected_tools():
    mcp, _ = _register()
    assert set(mcp.tools) == {
        "hermes.install",
        "hermes.upgrade",
        "hermes.restart",
        "litellm.control",
        "hermes.skills_pr_status",
    }


def test_install_orchestrates_provision_unit():
    mcp, ctx = _register()
    out = mcp.tools["hermes.install"]()
    # It triggers the provisioning oneshot — never curl|bash / exec in-sandbox.
    assert ("hermes-install", "start") in ctx.services
    assert ctx.commands == []
    assert out["status"] == "provisioned"
    assert out["active"] is True
    assert out["version"] == "0.19.1"
    assert out["version_ok"] is True


def test_install_reports_failure_when_unit_inactive():
    mcp, ctx = _register(active=False, journal_version=None)
    out = mcp.tools["hermes.install"]()
    assert ("hermes-install", "start") in ctx.services
    assert out["status"] == "failed"
    assert out["active"] is False
    assert out["version_ok"] is False


def test_upgrade_restarts_provision_unit():
    mcp, ctx = _register()
    out = mcp.tools["hermes.upgrade"]()
    assert ("hermes-install", "restart") in ctx.services
    assert out["status"] == "upgraded"
    assert out["to"] == "0.19.1"


def test_litellm_control_validates_action():
    mcp, _ = _register()
    assert "error" in mcp.tools["litellm.control"]("bogus")
    assert mcp.tools["litellm.control"]("restart") == {
        "unit": "litellm", "action": "restart", "active": True
    }


def test_hermes_restart_uses_service_control():
    mcp, ctx = _register()
    mcp.tools["hermes.restart"]()
    assert ("hermes", "restart") in ctx.services


def test_shipped_hermes_manifest_verifies():
    pdir = hermes_pkg.__path__[0]
    from pathlib import Path

    rec = verify_plugin(Path(pdir))
    assert rec.verified, rec.reason


def test_hermes_tools_load_into_server(tmp_path):
    """End-to-end: build_server discovers + loads the shipped hermes plugin."""
    from pathlib import Path

    plugins_dir = Path(hermes_pkg.__path__[0]).parent
    cfg = Config(
        host="127.0.0.1",
        token="abc",
        plugins_dir=str(plugins_dir),
        plugin_allowlist=["hermes"],
    )
    mcp = build_server(cfg)
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "hermes.install" in names
    assert "litellm.control" in names
