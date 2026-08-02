"""T3 — every call is authenticated; bad/missing tokens are rejected."""

from __future__ import annotations

import pytest

from gdv_node_agent.auth import StaticTokenVerifier
from gdv_node_agent.config import Config
from gdv_node_agent.server import MissingTokenError, build_server


async def test_valid_token_accepted():
    v = StaticTokenVerifier("s3cret")
    tok = await v.verify_token("s3cret")
    assert tok is not None
    assert tok.client_id == "gdv-node-agent-client"
    assert "node-agent" in tok.scopes


@pytest.mark.parametrize("presented", ["wrong", "", "s3cre", "s3crett", "S3CRET"])
async def test_bad_token_rejected(presented):
    v = StaticTokenVerifier("s3cret")
    assert await v.verify_token(presented) is None


async def test_empty_server_token_rejects_everything():
    v = StaticTokenVerifier("")
    assert await v.verify_token("") is None
    assert await v.verify_token("anything") is None


def test_build_server_requires_token():
    cfg = Config(host="127.0.0.1", token="", plugin_allowlist=[])
    with pytest.raises(MissingTokenError):
        build_server(cfg)


def test_build_server_with_token_installs_verifier():
    cfg = Config(host="127.0.0.1", token="abc", plugin_allowlist=[])
    mcp = build_server(cfg)
    # FastMCP stores the auth provider; it must be our verifier.
    assert isinstance(mcp.auth, StaticTokenVerifier)
