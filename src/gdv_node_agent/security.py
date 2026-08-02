"""T4 — Destructive-command block.

A denylist that refuses to execute obviously catastrophic commands through
``run_command``. This is **defense in depth**, not the primary control: the
primary controls are the Tailscale network gate and MCP-layer auth (ADR-002).
A denylist can never be complete, so we err toward blocking the well-known
foot-guns from BP-001 T4 (``rm -rf``, ``DROP``, ``mkfs``, ``dd of=/dev/*``,
shutdown/reboot, fork bombs, writes to raw block devices) and document the
limitation.

The checker splits a command line on shell operators (``;`` ``&&`` ``||`` ``|``
``&`` newlines) so that a destructive clause hidden after a benign one
(``ls && rm -rf /``) is still caught, then inspects each clause.
"""

from __future__ import annotations

import re
import shlex

# Clauses are separated by these shell control operators.
_SEGMENT_SPLIT = re.compile(r"\|\||&&|[;\n|&]")

# Leading tokens that wrap the *real* command and should be skipped.
_WRAPPERS = {"sudo", "env", "nice", "nohup", "time", "command", "exec", "builtin"}

# Raw-string patterns checked against the whole command line (case-insensitive).
_RAW_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # SQL: DROP TABLE / DATABASE / SCHEMA
    (re.compile(r"\bdrop\s+(table|database|schema)\b", re.I),
     "SQL DROP of a table/database/schema"),
    # Classic fork bomb  :(){ :|:& };:
    (re.compile(r":\s*\(\s*\)\s*\{"), "fork bomb"),
    # Redirecting output onto a raw block device
    (re.compile(r">\s*/dev/(sd|nvme|vd|xvd|mmcblk|disk|hd)\w*", re.I),
     "redirect onto a raw block device"),
    # mkfs against anything
    (re.compile(r"\bmkfs(\.\w+)?\b", re.I), "filesystem creation (mkfs)"),
    # wipefs / blkdiscard on devices
    (re.compile(r"\b(wipefs|blkdiscard)\b", re.I), "block-device wipe"),
]

# Block-device path prefix used by the dd / shred checks.
_BLOCK_DEV = re.compile(r"^/dev/(sd|nvme|vd|xvd|mmcblk|disk|hd)\w*", re.I)


def _strip_wrappers(argv: list[str]) -> list[str]:
    """Drop leading ``VAR=val`` assignments and wrapper commands (sudo, env...)."""
    i = 0
    while i < len(argv):
        tok = argv[i]
        if "=" in tok and not tok.startswith("-") and re.match(r"^\w+=", tok):
            i += 1
            continue
        base = tok.rsplit("/", 1)[-1]
        if base in _WRAPPERS:
            i += 1
            # `sudo -u foo cmd` — skip sudo's own options/args too
            while i < len(argv) and argv[i].startswith("-"):
                i += 1
            continue
        break
    return argv[i:]


def _short_flags(argv: list[str]) -> str:
    """Concatenate the letters of all combined short flags (``-rf`` -> ``rf``)."""
    letters = []
    for tok in argv:
        if tok.startswith("-") and not tok.startswith("--"):
            letters.append(tok[1:])
    return "".join(letters)


def _long_flags(argv: list[str]) -> set[str]:
    return {tok[2:] for tok in argv if tok.startswith("--")}


def _clause_is_destructive(clause: str) -> str | None:
    """Return a reason string if this single clause is destructive, else None."""
    clause = clause.strip()
    if not clause:
        return None

    try:
        argv = shlex.split(clause)
    except ValueError:
        # Unbalanced quotes etc. — fall back to a coarse split so we still inspect.
        argv = clause.split()

    argv = _strip_wrappers(argv)
    if not argv:
        return None

    cmd = argv[0].rsplit("/", 1)[-1]
    args = argv[1:]

    # rm with BOTH recursive and force
    if cmd == "rm":
        short = _short_flags(args)
        longs = _long_flags(args)
        recursive = "r" in short or "R" in short or "recursive" in longs
        force = "f" in short or "force" in longs
        if recursive and force:
            return "recursive+forced rm (rm -rf)"

    # mkfs.*
    if cmd.startswith("mkfs"):
        return "filesystem creation (mkfs)"

    # dd writing to a raw device
    if cmd == "dd":
        for a in args:
            if a.startswith("of=") and _BLOCK_DEV.match(a[3:]):
                return "dd writing to a raw block device"

    # shred / truncate against a raw device
    if cmd in {"shred", "truncate"}:
        for a in args:
            if _BLOCK_DEV.match(a):
                return f"{cmd} against a raw block device"

    # Power-state changes
    if cmd in {"shutdown", "reboot", "poweroff", "halt", "kexec"}:
        return f"power-state change ({cmd})"
    if cmd == "init" and any(a in {"0", "6"} for a in args):
        return "power-state change (init 0/6)"
    if cmd == "systemctl" and any(
        a in {"poweroff", "reboot", "halt", "kexec", "hibernate"} for a in args
    ):
        return "power-state change (systemctl)"

    # Disk partitioning tools operating on a device
    if cmd in {"fdisk", "sfdisk", "parted", "gdisk", "cfdisk"}:
        if any(_BLOCK_DEV.match(a) for a in args):
            return f"disk partitioning ({cmd})"

    return None


def is_destructive(cmd: str) -> tuple[bool, str | None]:
    """Return ``(blocked, reason)``. ``reason`` is None when the command is allowed."""
    if not cmd or not cmd.strip():
        return False, None

    # Whole-line raw patterns first.
    for pattern, reason in _RAW_PATTERNS:
        if pattern.search(cmd):
            return True, reason

    # Per-clause structured checks.
    for clause in _SEGMENT_SPLIT.split(cmd):
        reason = _clause_is_destructive(clause)
        if reason:
            return True, reason

    return False, None


def assert_safe_command(cmd: str) -> None:
    """Raise :class:`DestructiveCommandError` if ``cmd`` is destructive."""
    blocked, reason = is_destructive(cmd)
    if blocked:
        raise DestructiveCommandError(reason or "destructive command")


class DestructiveCommandError(RuntimeError):
    """Raised when a command matches the destructive-command denylist."""
