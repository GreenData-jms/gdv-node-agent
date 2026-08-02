#!/usr/bin/env python3
"""CI guard: every shipped plugin's manifest.json must match its files on disk.

This is the developer-side of the T5 integrity check: it fails the build if a
plugin's code was changed without regenerating its manifest, so an out-of-date
manifest can never be merged. It scans ``src/gdv_node_agent/plugins/*/`` for any
directory containing a ``manifest.json`` and verifies each with the same code the
agent uses at load time. Exit 0 if all consistent (including zero plugins).

Regenerate a manifest after intentional changes with:
    python scripts/gen_manifest.py <plugin-dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from gdv_node_agent.plugins.loader import MANIFEST_NAME, verify_plugin  # noqa: E402

PLUGINS_DIR = SRC / "gdv_node_agent" / "plugins"


def main() -> int:
    failures = []
    checked = 0
    for child in sorted(PLUGINS_DIR.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if not (child / MANIFEST_NAME).is_file():
            continue
        checked += 1
        rec = verify_plugin(child)
        status = "OK" if rec.verified else f"FAIL ({rec.reason})"
        print(f"  {child.name}: {status}")
        if not rec.verified:
            failures.append(child.name)

    if checked == 0:
        print("No plugin manifests to verify.")
    if failures:
        print(f"\nManifest verification FAILED for: {', '.join(failures)}")
        return 1
    print(f"\nAll {checked} plugin manifest(s) consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
