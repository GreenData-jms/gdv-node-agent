"""Shared pytest fixtures."""

from __future__ import annotations

import types
from dataclasses import replace

import pytest

from gdv_node_agent.audit import AuditLog
from gdv_node_agent.config import Config


@pytest.fixture
def audit(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


@pytest.fixture
def config(tmp_path):
    """A Config scoped to tmp dirs, with a token set (so it passes the T3 gate)."""
    read = tmp_path / "read"
    write = tmp_path / "write"
    read.mkdir()
    write.mkdir()
    return Config(
        host="127.0.0.1",
        port=8765,
        token="test-token-123",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        read_roots=[str(read)],
        write_roots=[str(write)],
        service_units=["hermes", "litellm"],
        command_allowlist=[],
        plugins_dir=str(tmp_path / "plugins"),
        plugin_allowlist=["hermes"],
    )


class FakeCompleted:
    """Stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def fake_subprocess(monkeypatch):
    """Monkeypatch tools.base.subprocess.run to record calls and return canned output.

    Usage:
        fake_subprocess.result = FakeCompleted(0, "ok", "")
        ... call tool ...
        assert fake_subprocess.calls  # list of (args, kwargs)
    """
    from gdv_node_agent.tools import base

    state = types.SimpleNamespace(calls=[], result=FakeCompleted(0, "", ""), raises=None)

    def fake_run(*args, **kwargs):
        state.calls.append((args, kwargs))
        if state.raises is not None:
            raise state.raises
        # is-active probe returns "active" by default when result not customized
        return state.result

    monkeypatch.setattr(base.subprocess, "run", fake_run)
    return state


def make_config(base_config: Config, **overrides) -> Config:
    return replace(base_config, **overrides)
