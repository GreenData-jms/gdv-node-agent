"""T4 — destructive commands are blocked; ordinary commands pass."""

from __future__ import annotations

import pytest

from gdv_node_agent.security import assert_safe_command, is_destructive
from gdv_node_agent.security import DestructiveCommandError
from gdv_node_agent.tools import base as bt


DESTRUCTIVE = [
    "rm -rf /",
    "rm -rf /var/lib/hermes",
    "rm -fr ~/",
    "rm --recursive --force /opt",
    "sudo rm -rf /etc",
    "ls /tmp && rm -rf /",          # hidden after a benign clause
    "true; rm -rf /home",
    "dd if=/dev/zero of=/dev/sda",
    "dd of=/dev/nvme0n1 if=/dev/zero bs=1M",
    "mkfs.ext4 /dev/sdb1",
    "mkfs -t xfs /dev/sdb",
    "shutdown -h now",
    "reboot",
    "poweroff",
    "halt",
    "init 0",
    "init 6",
    "systemctl poweroff",
    "wipefs -a /dev/sda",
    "blkdiscard /dev/nvme0n1",
    ":(){ :|:& };:",
    "echo boom > /dev/sda",
    "DROP TABLE users;",
    "psql -c 'drop database production'",
    "shred /dev/sda",
    "parted /dev/sda mklabel gpt",
]

SAFE = [
    "echo hello",
    "ls -la /var/log",
    "systemctl status hermes",
    "systemctl restart hermes",
    "journalctl -u hermes -n 100",
    "rm /tmp/onefile.txt",          # rm without -rf on a single file
    "rm -f /tmp/onefile.txt",       # force but not recursive
    "rm -r /tmp/emptydir",          # recursive but not forced
    "cat /etc/hostname",
    "curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash",
    "grep -r drop /var/log",        # the word 'drop', not a SQL DROP TABLE
    "pip install 'litellm[proxy]'",
    "dd if=/dev/zero of=/tmp/testfile bs=1M count=10",  # dd NOT to a device
]


@pytest.mark.parametrize("cmd", DESTRUCTIVE)
def test_destructive_blocked(cmd):
    blocked, reason = is_destructive(cmd)
    assert blocked, f"should block: {cmd}"
    assert reason
    with pytest.raises(DestructiveCommandError):
        assert_safe_command(cmd)


@pytest.mark.parametrize("cmd", SAFE)
def test_safe_allowed(cmd):
    blocked, _ = is_destructive(cmd)
    assert not blocked, f"should allow: {cmd}"
    assert_safe_command(cmd)  # does not raise


def test_run_command_blocks_and_does_not_exec(config, audit, monkeypatch):
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("subprocess must not run for a blocked command")

    monkeypatch.setattr(bt.subprocess, "run", boom)
    out = bt.run_command("rm -rf /", config=config, audit=audit)
    assert "error" in out and "destructive" in out["error"]
    assert called["n"] == 0
