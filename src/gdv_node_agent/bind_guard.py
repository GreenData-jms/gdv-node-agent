"""T2 — Bind guard.

The GDV Node Agent is a *remote* MCP server (D-24) but it must **never** be
reachable from the public internet. It is bound to the Tailscale interface only
(device identity + ACLs are the network-layer authN/Z) or to loopback for local
testing. This module is the hard gate that refuses to start on any other
address — in particular ``0.0.0.0`` / ``::`` (all interfaces) or a routable
public IP.

See ADR-002 "Security model — Network — two gates, never public" and BP-001 T2.
"""

from __future__ import annotations

import ipaddress

# Tailscale hands out addresses from the CGNAT range 100.64.0.0/10
# (100.64.0.0 – 100.127.255.255). That is the only non-loopback range we allow
# the agent to bind to.
TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")

# Literal hostnames we accept as loopback. We deliberately do NOT resolve
# arbitrary hostnames: a name that resolves to a public address (now or later,
# via DNS) would silently defeat the guard. Callers bind to the literal
# Tailscale 100.x IP or to loopback.
_LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


class BindGuardError(RuntimeError):
    """Raised when the configured bind address is not Tailscale/loopback."""


def is_bind_allowed(host: str) -> tuple[bool, str]:
    """Return ``(allowed, reason)`` for a proposed bind address.

    Allowed:
      * loopback literal names (``localhost``)
      * any loopback IP (``127.0.0.0/8``, ``::1``)
      * any IP inside the Tailscale CGNAT range ``100.64.0.0/10``

    Rejected (with a reason):
      * the unspecified address ``0.0.0.0`` / ``::`` (binds all interfaces → public)
      * any other routable/public IP
      * any non-loopback hostname (we will not resolve it)
    """
    if host is None:
        return False, "no bind host configured"

    candidate = host.strip()
    if not candidate:
        return False, "empty bind host"

    lowered = candidate.lower()
    if lowered in _LOOPBACK_NAMES:
        return True, "loopback hostname"

    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        return (
            False,
            f"{candidate!r} is not an IP address; bind to the Tailscale 100.x IP "
            "or a loopback address, not a resolvable hostname",
        )

    if ip.is_unspecified:
        return (
            False,
            f"refusing to bind to the unspecified address {candidate!r} "
            "(this exposes every interface, including public ones)",
        )

    if ip.is_loopback:
        return True, "loopback address"

    if ip.version == 4 and ip in TAILSCALE_CGNAT:
        return True, "Tailscale CGNAT address"

    return (
        False,
        f"refusing to bind to non-Tailscale address {candidate!r}; only "
        "loopback or the Tailscale interface (100.64.0.0/10) are permitted",
    )


def assert_bind_allowed(host: str) -> None:
    """Raise :class:`BindGuardError` if ``host`` is not an allowed bind address."""
    allowed, reason = is_bind_allowed(host)
    if not allowed:
        raise BindGuardError(reason)
