# GDV Node Agent

> The security-critical, MCP-native **management-plane daemon** for Green Data
> Ventures' agentic orchestrator. It is the **first** thing installed on any GDV
> box and becomes the SSH-free, out-of-band control surface for that host.
> Reference: `BP-001` / `ADR-002` in the `gdv-agentic-orchestrator` design repo.

**Production infrastructure — not a prototype.** It holds the exec primitive,
terminates auth, and loads plugins on every node, so it earns the most rigor:
security tests are written first and gate everything else.

---

## What it is

A small, always-on [FastMCP](https://github.com/jlowin/fastmcp) server (Python
3.11) speaking **remote streamable-HTTP/SSE** (D-24), **bound to the Tailscale
interface only** (never public). It exposes generic host-management primitives
plus a **signed-plugin** seam; the first plugin (`hermes`) installs and manages
Hermes + LiteLLM.

### Base tools

| Tool | Returns | Notes |
|---|---|---|
| `ping` | `{name, version, tailscale_ip, plugins, uptime_s}` | health; called first |
| `run_command` | `{exit_code, stdout, stderr}` or `{error}` | audited; destructive-pattern block; optional allowlist |
| `read_file` | `{path, content}` or `{error}` | scoped to allowed roots |
| `write_file` | `{path, bytes}` or `{error}` | scoped to allowed roots; audited |
| `service_control` | `{unit, action, active}` or `{error}` | `start/stop/restart/status`; unit allowlist |
| `tail_logs` | `{unit, lines}` or `{error}` | journalctl-backed; unit allowlist |
| `list_plugins` | `[{name, version, verified}]` | `verified` = manifest hash matched |

Every tool follows the folio discipline: docstring required, JSON-serializable
returns, and **it never raises — it returns `{"error": "..."}`**.

---

## Security model (the hard gate)

Four security properties are enforced and tested before any other work
(`BP-001` T2–T5):

- **T2 — Bind guard.** Refuses to start unless bound to the Tailscale CGNAT
  range (`100.64.0.0/10`) or loopback. `0.0.0.0`, `::`, and public IPs are
  rejected *before any listener is created* (`bind_guard.py`).
- **T3 — Auth.** Every call is authenticated with a bearer token (constant-time
  compare) on top of the Tailscale network gate; missing/bad tokens get `401`.
  mTLS/OAuth-ready seam (`auth.py`). The agent refuses to start with no token.
- **T4 — Destructive-command block.** `rm -rf`, `DROP`, `mkfs`, `dd of=/dev/*`,
  shutdown/reboot, fork bombs, raw block-device writes, … are blocked — even
  when hidden after a benign clause (`ls && rm -rf /`) (`security.py`).
- **T5 — Plugin integrity.** Allowlist + **per-plugin SHA-256 manifest**.
  Altered, unsigned, or unlisted plugin code is `verified: false` and is
  **never imported** (`plugins/loader.py`).

These are defense in depth layered on the two network gates (Tailscale device
identity + ACLs, then bind-to-100.x). See `ADR-002` for the full model.

---

## Repository layout

```
src/gdv_node_agent/
  bind_guard.py     # T2 — refuse non-Tailscale/loopback bind
  auth.py           # T3 — bearer token verifier (FastMCP TokenVerifier)
  security.py       # T4 — destructive-command denylist
  audit.py          # append-only JSONL audit log (args digested, never raw)
  config.py         # env-driven config (token from file, scoped roots, allowlists)
  server.py         # FastMCP assembly; enforces T2/T3 gates before listening
  tools/base.py     # the base tools (testable, injectable deps)
  plugins/loader.py # T5 — allowlist + SHA-256 manifest verification
  plugins/runtime.py# loads VERIFIED plugins only; PluginContext seam
deploy/             # bootstrap.sh, systemd unit, scoped sudoers (local phase)
scripts/            # manifest gen + CI consistency guard
tests/              # T1 unit + T2–T5 security (CI) · T6/T7 local-phase (marked)
DEPLOY.md           # local-phase runbook (run from the Tailscale-connected Mac)
```

---

## Configuration (environment variables)

| Var | Default | Purpose |
|---|---|---|
| `GDV_AGENT_HOST` | `127.0.0.1` | bind address (Tailscale 100.x in production) |
| `GDV_AGENT_PORT` | `8765` | MCP port |
| `GDV_AGENT_MCP_PATH` | `/mcp/` | HTTP path |
| `GDV_AGENT_TOKEN` / `GDV_AGENT_TOKEN_FILE` | — | bearer token (prefer the `0600` file) |
| `GDV_AGENT_AUDIT_LOG` | `/var/log/gdv-node-agent/audit.jsonl` | audit sink |
| `GDV_AGENT_READ_ROOTS` | `/etc:/var/log:/opt:/home:/tmp` | `read_file` scope |
| `GDV_AGENT_WRITE_ROOTS` | `/opt:/tmp` | `write_file` scope |
| `GDV_AGENT_SERVICE_UNITS` | `hermes:litellm:gdv-node-agent` | `service_control`/`tail_logs` allowlist |
| `GDV_AGENT_COMMAND_ALLOWLIST` | *(empty)* | optional positive allowlist for `run_command` |
| `GDV_AGENT_PLUGIN_ALLOWLIST` | `hermes` | plugins permitted to load |

Secrets never live in the repo. The bootstrap generates the auth token **on the
host** (`0600`, root-only) and surfaces it for the Claude Desktop config.
Provider keys (Anthropic/NVIDIA/Google) are the user's and belong to LiteLLM's
environment — the agent never handles them.

---

## Develop

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q            # T1 + T2–T5 (T6/T7 skipped: they need the mesh)
```

## Run (local only)

Deployment and running happen in the **local phase** from the Tailscale
mesh — see **[DEPLOY.md](DEPLOY.md)**. The cloud CI build never contacts the
target host.

---

## Claude Desktop registration (remote MCP)

After the agent is running on `hermes-brain` (local phase), add it to Claude
Desktop's config as a remote MCP server. Exact snippet and token handling are in
**[DEPLOY.md](DEPLOY.md)**; shape:

```json
{
  "mcpServers": {
    "gdv-node-agent": {
      "transport": "http",
      "url": "http://hermes-brain.tailab8826.ts.net:8765/mcp/",
      "headers": { "Authorization": "Bearer <token-from-host>" }
    }
  }
}
```

---

*GDV Agentic Orchestrator · Node Agent · implements BP-001, architecture per ADR-002.*
