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
    def __init__(self):
        self.commands = []
        self.services = []
        self.version_output = "hermes 0.19.1"
        self.installed = True

    def run_command(self, cmd, timeout_s=60):
        self.commands.append(cmd)
        if cmd == "hermes --version":
            if not self.installed:
                return {"error": "hermes: command not found"}
            return {"exit_code": 0, "stdout": self.version_output, "stderr": ""}
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    def service_control(self, unit, action):
        self.services.append((unit, action))
        return {"unit": unit, "action": action, "active": True}


def _register():
    mcp = FakeMCP()
    ctx = FakeCtx()
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


def test_install_idempotent_when_present():
    mcp, ctx = _register()
    ctx.installed = True
    out = mcp.tools["hermes.install"]()
    assert out == {"status": "already-installed", "version": "0.19.1"}
    # must NOT have run the installer
    assert hermes_plugin.HERMES_INSTALL_CMD not in ctx.commands


def test_install_runs_when_absent():
    mcp, ctx = _register()
    ctx.installed = False

    calls = {"n": 0}
    orig = ctx.run_command

    def run(cmd, timeout_s=60):
        calls["n"] += 1
        # first version probe: absent; after installer: present
        if cmd == "hermes --version" and calls["n"] > 1:
            ctx.installed = True
        return orig(cmd, timeout_s)

    ctx.run_command = run
    out = mcp.tools["hermes.install"]()
    assert out["status"] == "installed"
    assert hermes_plugin.HERMES_INSTALL_CMD in ctx.commands


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
