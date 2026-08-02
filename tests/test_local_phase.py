"""T6 / T7 — LOCAL-PHASE tests. Written now, RUN during the local deploy phase.

These require the Tailscale mesh and the target host (hermes-brain) and therefore
CANNOT run in CI or the cloud session. They are marked ``local`` and skipped by
default (see pyproject ``addopts = -m 'not local'``). Run them from the
Tailscale-connected Mac during the local phase:

    GDV_AGENT_URL=http://hermes-brain.tailab8826.ts.net:8765/mcp/ \
    GDV_AGENT_TOKEN=<token-from-host> \
    pytest -m local

See DEPLOY.md steps 6–7.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.local


def _client():
    from fastmcp import Client

    url = os.environ["GDV_AGENT_URL"]
    token = os.environ["GDV_AGENT_TOKEN"]
    return Client(url, auth=token)


@pytest.mark.asyncio
async def test_t6_hermes_install_present():
    """T6 — hermes.install provisions Hermes 0.19.1 under its own workload unit.

    The agent orchestrates the hardened ``hermes-install`` oneshot (it cannot exec
    the workload binary — separate identity + 0750 state), so we assert on the
    tool's return, whose version provenance comes from the unit's journal.
    """
    client = _client()
    async with client:
        res = await client.call_tool("hermes.install", {})
        data = res.data if hasattr(res, "data") else res
        assert data.get("active") is True, data
        assert data.get("version") == "0.19.1", data
        assert data.get("version_ok") is True, data


@pytest.mark.asyncio
async def test_t7_bridge_reachability_ping():
    """T7 — ping succeeds through the remote MCP connection over Tailscale."""
    client = _client()
    async with client:
        res = await client.call_tool("ping", {})
        data = res.data if hasattr(res, "data") else res
        assert str(data).find("gdv-node-agent") != -1
