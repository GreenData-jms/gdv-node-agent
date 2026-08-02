"""T2 — the agent refuses to start unless bound to Tailscale/loopback."""

from __future__ import annotations

import pytest

from gdv_node_agent.bind_guard import (
    BindGuardError,
    assert_bind_allowed,
    is_bind_allowed,
)


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.0.0.53",
        "::1",
        "localhost",
        "100.126.235.73",  # the hermes-brain Tailscale IP
        "100.64.0.1",
        "100.127.255.254",
    ],
)
def test_allowed_addresses(host):
    allowed, _ = is_bind_allowed(host)
    assert allowed, host
    assert_bind_allowed(host)  # does not raise


@pytest.mark.parametrize(
    "host",
    [
        "0.0.0.0",          # all interfaces → public
        "::",               # all interfaces (v6)
        "137.184.105.121",  # the box's PUBLIC IP — must be refused
        "8.8.8.8",
        "10.116.0.2",       # private but not Tailscale
        "192.168.1.10",
        "100.128.0.1",      # just outside the CGNAT /10
        "99.255.255.255",
        "hermes-brain.tailab8826.ts.net",  # a hostname — we won't resolve it
        "",
    ],
)
def test_refused_addresses(host):
    allowed, reason = is_bind_allowed(host)
    assert not allowed, host
    assert reason
    with pytest.raises(BindGuardError):
        assert_bind_allowed(host)


def test_build_server_refuses_public_bind():
    from gdv_node_agent.config import Config
    from gdv_node_agent.server import build_server

    cfg = Config(host="0.0.0.0", token="x", plugin_allowlist=[])
    with pytest.raises(BindGuardError):
        build_server(cfg)
