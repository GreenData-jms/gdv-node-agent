"""T1 — unit tests for each base tool with mocked subprocess / filesystem."""

from __future__ import annotations

from pathlib import Path

from gdv_node_agent.tools import base as bt
from tests.conftest import FakeCompleted


# --- ping ------------------------------------------------------------------ #
def test_ping_shape(config):
    out = bt.ping(config, plugins=[{"name": "hermes", "version": "0.1.0", "verified": True}])
    assert out["name"] == "gdv-node-agent"
    assert out["tailscale_ip"] == config.host
    assert out["plugins"][0]["name"] == "hermes"
    assert isinstance(out["uptime_s"], float)


# --- run_command ----------------------------------------------------------- #
def test_run_command_returns_dict(config, audit, fake_subprocess):
    fake_subprocess.result = FakeCompleted(0, "hello\n", "")
    out = bt.run_command("echo hello", config=config, audit=audit)
    assert out == {"exit_code": 0, "stdout": "hello\n", "stderr": ""}


def test_run_command_timeout_returns_error(config, audit, fake_subprocess):
    import subprocess

    fake_subprocess.raises = subprocess.TimeoutExpired(cmd="sleep", timeout=1)
    out = bt.run_command("sleep 100", timeout_s=1, config=config, audit=audit)
    assert "error" in out and "timed out" in out["error"]


def test_run_command_allowlist(config, audit, fake_subprocess):
    config.command_allowlist = ["echo"]
    fake_subprocess.result = FakeCompleted(0, "", "")
    assert "error" not in bt.run_command("echo hi", config=config, audit=audit)
    out = bt.run_command("cat /etc/passwd", config=config, audit=audit)
    assert "error" in out and "allowlist" in out["error"]


def test_run_command_audits(config, audit, fake_subprocess):
    fake_subprocess.result = FakeCompleted(0, "", "")
    bt.run_command("echo hi", config=config, audit=audit)
    lines = Path(config.audit_log_path).read_text().strip().splitlines()
    assert any('"tool": "run_command"' in ln for ln in lines)
    # the raw command must NOT appear — only a digest
    assert all("echo hi" not in ln for ln in lines)


# --- read_file / write_file ------------------------------------------------ #
def test_read_file_within_root(config):
    p = Path(config.read_roots[0]) / "note.txt"
    p.write_text("data")
    out = bt.read_file(str(p), config=config)
    assert out == {"path": str(p), "content": "data"}


def test_read_file_outside_root(config):
    out = bt.read_file("/etc/shadow", config=config)
    assert "error" in out and "read roots" in out["error"]


def test_read_file_traversal_blocked(config):
    # ../ escape out of the allowed root must be rejected
    escape = str(Path(config.read_roots[0]) / ".." / ".." / "etc" / "passwd")
    out = bt.read_file(escape, config=config)
    assert "error" in out


def test_write_file_within_root(config, audit):
    p = Path(config.write_roots[0]) / "out.txt"
    out = bt.write_file(str(p), "hello", config=config, audit=audit)
    assert out["path"] == str(p)
    assert p.read_text() == "hello"


def test_write_file_outside_root(config, audit):
    out = bt.write_file("/etc/evil.conf", "x", config=config, audit=audit)
    assert "error" in out and "write roots" in out["error"]
    assert not Path("/etc/evil.conf").exists()


# --- service_control ------------------------------------------------------- #
def test_service_control_allowlist(config, audit, fake_subprocess):
    out = bt.service_control("nginx", "restart", config=config, audit=audit)
    assert "error" in out and "allowlist" in out["error"]


def test_service_control_bad_action(config, audit):
    out = bt.service_control("hermes", "nuke", config=config, audit=audit)
    assert "error" in out and "action" in out["error"]


def test_service_control_restart(config, audit, fake_subprocess):
    fake_subprocess.result = FakeCompleted(0, "active", "")
    out = bt.service_control("hermes", "restart", config=config, audit=audit)
    assert out == {"unit": "hermes", "action": "restart", "active": True}


def test_service_control_uses_sudo_prefix_when_configured(config, audit, fake_subprocess):
    config.use_sudo = True
    fake_subprocess.result = FakeCompleted(0, "active", "")
    bt.service_control("hermes", "restart", config=config, audit=audit)
    # every systemctl invocation must be prefixed with `sudo -n`
    for (args, _kwargs) in fake_subprocess.calls:
        argv = args[0]
        assert argv[:3] == ["sudo", "-n", "systemctl"], argv


# --- tail_logs ------------------------------------------------------------- #
def test_tail_logs_allowlist(config):
    out = bt.tail_logs("nginx", config=config)
    assert "error" in out and "allowlist" in out["error"]


def test_tail_logs_returns_lines(config, fake_subprocess):
    fake_subprocess.result = FakeCompleted(0, "line1\nline2\n", "")
    out = bt.tail_logs("hermes", lines=2, config=config)
    assert out == {"unit": "hermes", "lines": ["line1", "line2"]}
