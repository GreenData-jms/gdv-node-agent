#!/usr/bin/env python3
"""Generate/refresh a plugin's manifest.json (name, version, entrypoint, file hashes).

Usage:
    python scripts/gen_manifest.py src/gdv_node_agent/plugins/hermes [--version 0.1.0]

Hashes every file in the plugin directory except manifest.json / __init__.py /
__pycache__, and writes a manifest the loader (T5) will accept. Review the diff
before committing — the manifest is the signed provenance of the plugin.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gdv_node_agent.plugins.loader import MANIFEST_NAME, sha256_file  # noqa: E402

_IGNORED = {MANIFEST_NAME, "__init__.py", "__pycache__"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plugin_dir")
    ap.add_argument("--version", default=None)
    ap.add_argument("--entrypoint", default="plugin.py")
    args = ap.parse_args()

    pdir = Path(args.plugin_dir).resolve()
    if not pdir.is_dir():
        print(f"not a directory: {pdir}", file=sys.stderr)
        return 1

    existing = {}
    manifest_path = pdir / MANIFEST_NAME
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text())

    files = {}
    for child in sorted(pdir.iterdir()):
        if child.name in _IGNORED or child.is_dir():
            continue
        files[child.name] = sha256_file(child)

    manifest = {
        "name": pdir.name,
        "version": args.version or existing.get("version", "0.1.0"),
        "entrypoint": args.entrypoint,
        "files": files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {manifest_path} ({len(files)} file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
