"""T3 — MCP-layer authentication.

Every call to the agent must be authenticated on top of the Tailscale network
gate (defense in depth, ADR-002). v0 is a **static bearer token**; the seam is
built so mTLS / OAuth 2.1 can replace it later (D-24 open item #3) without
touching the tools.

``StaticTokenVerifier`` plugs into FastMCP's ``auth=`` parameter: FastMCP calls
``verify_token`` for every request and returns HTTP 401 when it returns None.
The comparison is constant-time (``hmac.compare_digest``) to avoid leaking the
token through timing.
"""

from __future__ import annotations

import hmac

from fastmcp.server.auth import AccessToken, TokenVerifier

# Identity we attach to a successfully-authenticated caller. v0 has a single
# shared token (the Mac Claude Desktop client), so a single logical client id.
DEFAULT_CLIENT_ID = "gdv-node-agent-client"
DEFAULT_SCOPES = ["node-agent"]


class StaticTokenVerifier(TokenVerifier):
    """Verify a single shared bearer token in constant time.

    Args:
        token: the expected bearer token. Must be non-empty; an empty/None token
            is a misconfiguration and makes the verifier reject everything.
        client_id: logical identity recorded for the caller (used in the audit log).
    """

    def __init__(
        self,
        token: str,
        *,
        client_id: str = DEFAULT_CLIENT_ID,
        required_scopes: list[str] | None = None,
    ) -> None:
        super().__init__(required_scopes=required_scopes)
        self._token = token or ""
        self._client_id = client_id

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return an :class:`AccessToken` for a valid token, else None (→ 401)."""
        # An unset server token can never match a presented token: reject.
        if not self._token or not token:
            return None
        if not hmac.compare_digest(token, self._token):
            return None
        return AccessToken(
            token=token,
            client_id=self._client_id,
            scopes=list(DEFAULT_SCOPES),
            subject=self._client_id,
        )
