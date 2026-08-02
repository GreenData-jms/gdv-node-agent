"""T5 — Signed plugin loader (v0: allowlist + per-plugin SHA-256 manifest).

A module-loading agent is a supply-chain surface by construction (ADR-002). v0
governance is intentionally simple and reviewable in a PR diff:

  1. **Allowlist.** Only plugins named in ``config.plugin_allowlist`` are ever
     considered. An unlisted directory is ignored entirely.
  2. **Per-plugin manifest.** Each plugin ships a ``manifest.json``:

        {
          "name": "hermes",
          "version": "0.1.0",
          "entrypoint": "plugin.py",
          "files": { "plugin.py": "<sha256>", "manifest.json is NOT self-listed": ... }
        }

     Every file listed is re-hashed at load time and compared. If any listed
     file is missing or altered, or the plugin ships a file that is present but
     unlisted (see ``strict``), the plugin is marked ``verified: false`` and is
     **not loaded**.

This is not cosign — a later ADR item swaps this for real signatures. The
contract the rest of the agent depends on is: *altered or unlisted plugin code
never executes.*
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"

# Files that are allowed to exist in a plugin dir without being hashed.
_IGNORED_FILES = {MANIFEST_NAME, "__init__.py", "__pycache__"}


@dataclass
class PluginRecord:
    name: str
    version: str
    verified: bool
    path: Path
    entrypoint: str | None = None
    reason: str = ""  # why verification failed, when verified is False
    files: dict[str, str] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        """The public shape returned by ``list_plugins``."""
        return {"name": self.name, "version": self.version, "verified": self.verified}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest(plugin_dir: Path) -> dict[str, Any] | None:
    manifest_path = plugin_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def verify_plugin(plugin_dir: Path, *, strict: bool = True) -> PluginRecord:
    """Verify a single plugin directory against its manifest.

    ``strict`` (default) also fails verification when the directory contains a
    non-ignored file that the manifest does not list — closing the "smuggle an
    extra module alongside the signed ones" gap.
    """
    name = plugin_dir.name
    manifest = _load_manifest(plugin_dir)
    if manifest is None:
        return PluginRecord(
            name=name, version="unknown", verified=False, path=plugin_dir,
            reason="missing or unreadable manifest.json",
        )

    declared_name = manifest.get("name", name)
    version = str(manifest.get("version", "unknown"))
    entrypoint = manifest.get("entrypoint")
    files = manifest.get("files") or {}

    record = PluginRecord(
        name=declared_name, version=version, verified=False, path=plugin_dir,
        entrypoint=entrypoint, files=dict(files),
    )

    if declared_name != name:
        record.reason = f"manifest name {declared_name!r} != directory name {name!r}"
        return record

    if not files:
        record.reason = "manifest lists no files"
        return record

    # Every listed file must exist and match.
    for rel, expected in files.items():
        target = plugin_dir / rel
        if not target.is_file():
            record.reason = f"listed file missing: {rel}"
            return record
        actual = sha256_file(target)
        if actual != expected:
            record.reason = f"hash mismatch for {rel}"
            return record

    # No unlisted code files (strict).
    if strict:
        for child in plugin_dir.iterdir():
            if child.name in _IGNORED_FILES:
                continue
            if child.is_dir():
                continue
            rel = child.name
            if rel not in files:
                record.reason = f"unlisted file present: {rel}"
                return record

    record.verified = True
    return record


class PluginRegistry:
    """Discovers, verifies and (later) loads plugins under a plugins dir."""

    def __init__(
        self,
        plugins_dir: str | Path,
        allowlist: list[str],
        *,
        strict: bool = True,
    ) -> None:
        self.plugins_dir = Path(plugins_dir)
        self.allowlist = set(allowlist)
        self.strict = strict
        self.records: list[PluginRecord] = []

    def discover(self) -> list[PluginRecord]:
        """Verify every allowlisted plugin directory. Does not import code."""
        self.records = []
        if not self.plugins_dir.is_dir():
            return self.records
        for child in sorted(self.plugins_dir.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith("_") or child.name.startswith("."):
                continue
            if child.name not in self.allowlist:
                # Not allowlisted → ignored entirely (recorded as unverified).
                self.records.append(
                    PluginRecord(
                        name=child.name, version="unknown", verified=False,
                        path=child, reason="not in plugin allowlist",
                    )
                )
                continue
            self.records.append(verify_plugin(child, strict=self.strict))
        return self.records

    def verified_records(self) -> list[PluginRecord]:
        return [r for r in self.records if r.verified]

    def summaries(self) -> list[dict[str, Any]]:
        return [r.summary() for r in self.records]
