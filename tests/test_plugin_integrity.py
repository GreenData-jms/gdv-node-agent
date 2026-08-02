"""T5 — altered/unsigned/unlisted plugins are verified:false and never loaded."""

from __future__ import annotations

import json

from gdv_node_agent.plugins.loader import (
    PluginRegistry,
    sha256_file,
    verify_plugin,
)


def _write_plugin(root, name="hermes", version="0.1.0", body="def register(mcp, ctx):\n    pass\n"):
    """Create a valid signed plugin dir under ``root`` and return its path."""
    pdir = root / name
    pdir.mkdir(parents=True)
    entry = pdir / "plugin.py"
    entry.write_text(body)
    manifest = {
        "name": name,
        "version": version,
        "entrypoint": "plugin.py",
        "files": {"plugin.py": sha256_file(entry)},
    }
    (pdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return pdir


def test_valid_plugin_verifies(tmp_path):
    pdir = _write_plugin(tmp_path)
    rec = verify_plugin(pdir)
    assert rec.verified is True
    assert rec.name == "hermes"
    assert rec.version == "0.1.0"


def test_altered_plugin_fails(tmp_path):
    pdir = _write_plugin(tmp_path)
    # Tamper AFTER the manifest was written.
    (pdir / "plugin.py").write_text("def register(mcp, ctx):\n    __import__('os').system('id')\n")
    rec = verify_plugin(pdir)
    assert rec.verified is False
    assert "hash mismatch" in rec.reason


def test_missing_manifest_fails(tmp_path):
    pdir = tmp_path / "hermes"
    pdir.mkdir()
    (pdir / "plugin.py").write_text("def register(mcp, ctx):\n    pass\n")
    rec = verify_plugin(pdir)
    assert rec.verified is False
    assert "manifest" in rec.reason


def test_missing_listed_file_fails(tmp_path):
    pdir = _write_plugin(tmp_path)
    (pdir / "plugin.py").unlink()
    rec = verify_plugin(pdir)
    assert rec.verified is False
    assert "missing" in rec.reason


def test_unlisted_extra_file_fails_strict(tmp_path):
    pdir = _write_plugin(tmp_path)
    # Smuggle an extra, unlisted module alongside the signed ones.
    (pdir / "evil.py").write_text("print('pwn')")
    rec = verify_plugin(pdir, strict=True)
    assert rec.verified is False
    assert "unlisted" in rec.reason


def test_name_mismatch_fails(tmp_path):
    pdir = _write_plugin(tmp_path, name="hermes")
    manifest = json.loads((pdir / "manifest.json").read_text())
    manifest["name"] = "somethingelse"
    (pdir / "manifest.json").write_text(json.dumps(manifest))
    rec = verify_plugin(pdir)
    assert rec.verified is False
    assert "name" in rec.reason


def test_registry_only_returns_verified(tmp_path):
    _write_plugin(tmp_path, name="hermes")
    # a second, tampered plugin that is allowlisted but altered
    bad = _write_plugin(tmp_path, name="nemoclaw")
    (bad / "plugin.py").write_text("tampered")

    reg = PluginRegistry(tmp_path, allowlist=["hermes", "nemoclaw"])
    reg.discover()
    verified = {r.name for r in reg.verified_records()}
    assert verified == {"hermes"}


def test_registry_ignores_non_allowlisted(tmp_path):
    _write_plugin(tmp_path, name="rogue")
    reg = PluginRegistry(tmp_path, allowlist=["hermes"])
    reg.discover()
    # rogue is present but not allowlisted → recorded unverified, never loaded
    recs = {r.name: r for r in reg.records}
    assert recs["rogue"].verified is False
    assert "allowlist" in recs["rogue"].reason
    assert reg.verified_records() == []
