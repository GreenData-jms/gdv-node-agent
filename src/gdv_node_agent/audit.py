"""Append-only audit log.

Every ``run_command`` (and every other state-changing tool call) is recorded to
an append-only JSONL file (BP-001 §3b). We record the *digest* of the arguments,
never the raw arguments, so the log itself never becomes a place secrets leak to.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

# Set by the server's auth layer once a caller is authenticated; read by the
# audit log so each record is attributed without threading the caller through
# every tool signature.
current_caller: ContextVar[str] = ContextVar("current_caller", default="unknown")


def args_digest(args: dict[str, Any]) -> str:
    """Stable SHA-256 digest of a tool's arguments (order-independent)."""
    canonical = json.dumps(args, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditLog:
    """Append-only JSONL audit sink."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def _ensure_dir(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        tool: str,
        args: dict[str, Any] | None = None,
        outcome: str,
        caller: str | None = None,
        **extra: Any,
    ) -> None:
        """Append one audit record. Never raises into the caller."""
        entry = {
            "ts": time.time(),
            "caller": caller if caller is not None else current_caller.get(),
            "tool": tool,
            "args_digest": args_digest(args or {}),
            "outcome": outcome,
        }
        entry.update(extra)
        try:
            self._ensure_dir()
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except OSError:
            # Auditing must never take the agent down. A failure to write is
            # itself surfaced on stderr but does not propagate.
            import sys

            print(
                f"[gdv-node-agent] WARNING: failed to write audit record to {self.path}",
                file=sys.stderr,
            )
