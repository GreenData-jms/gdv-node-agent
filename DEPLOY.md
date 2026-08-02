# DEPLOY.md — GDV Node Agent local-phase runbook

> **Who runs this:** JMS, from the **Tailscale-connected Mac** (`mia-ml`).
> **Why not the cloud session:** the cloud build has **no Tailscale mesh** and
> cannot reach `hermes-brain`. Everything below needs the mesh or the host, so it
> is deferred to this local phase (BP-001 Step 6–8; ADR-002 control path).
>
> **Target host:** `hermes-brain.tailab8826.ts.net` (fallback `100.126.235.73`),
> Ubuntu 24.04, `tag:brain-host`, Tailscale SSH on.
> **Agent port:** `8765` · **MCP path:** `/mcp/` · **Runs as:** `nodeagent` (not root).

The security core (T2–T5) is already green in CI. This runbook stands the agent
up, proves it's bound to Tailscale, wires the Mac to it, and then installs
Hermes + LiteLLM **through** the agent.

---

## 0. Preflight (from the Mac)

```bash
# You are on the tailnet and can reach the box:
tailscale status | grep hermes-brain
tailscale ssh root@hermes-brain 'echo reachable && lsb_release -ds'
```

If that lands on the box, continue. (This is the one bootstrap SSH hop; after
the agent is up, SSH drops to break-glass.)

---

## 1. Run the bootstrap on `hermes-brain` (root, once)

The bootstrap is **idempotent** — safe to re-run; it only prints `skip` for work
already done and never regenerates the token.

```bash
# From the Mac, over Tailscale SSH. Pass the box's Tailscale 100.x IP so the
# agent binds to the mesh interface (it REFUSES any non-Tailscale/loopback bind).
tailscale ssh root@hermes-brain '
  set -e
  git clone --depth 1 https://github.com/GreenData-jms/gdv-node-agent.git /opt/gdv-node-agent 2>/dev/null || true
  cd /opt/gdv-node-agent
  sudo GDV_AGENT_HOST=$(tailscale ip -4 | head -n1) bash deploy/bootstrap.sh
'
```

What it does (see `deploy/bootstrap.sh`): installs packages → creates the
least-privilege **`nodeagent`** user → clones + venv-installs the agent →
generates the bearer **token** (`/etc/gdv-node-agent/token`, `root:nodeagent`,
`0640`) → writes the **scoped sudoers** (`/etc/sudoers.d/gdv-node-agent`, only
the systemctl/journalctl verbs the agent needs) → installs the **systemd unit**.

---

## 2. Start & enable the systemd unit

```bash
tailscale ssh root@hermes-brain '
  sudo systemctl enable --now gdv-node-agent
  sudo systemctl status gdv-node-agent --no-pager
'
```

Expect `active (running)` and, in the log, no bind-guard/token refusal.

---

## 3. Confirm the agent is bound to the Tailscale interface (T2 in the real world)

```bash
tailscale ssh root@hermes-brain '
  ss -tlnp | grep 8765
'
```

You should see it listening on the **`100.x`** address (or loopback), **not**
`0.0.0.0`. If the unit exited with a bind refusal, `GDV_AGENT_HOST` was not a
Tailscale/loopback address — fix it and re-run the bootstrap. From the Mac:

```bash
curl -s -H "Authorization: Bearer $(tailscale ssh root@hermes-brain sudo cat /etc/gdv-node-agent/token)" \
  http://hermes-brain.tailab8826.ts.net:8765/mcp/ -i | head -n 5
# 401 WITHOUT the header; a valid MCP response WITH it → auth (T3) is live.
```

---

## 4. Register the agent in Claude Desktop (remote MCP)

Grab the token (root-only on the host):

```bash
tailscale ssh root@hermes-brain 'sudo cat /etc/gdv-node-agent/token'
```

Add to the Mac's Claude Desktop MCP config
(`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "gdv-node-agent": {
      "transport": "http",
      "url": "http://hermes-brain.tailab8826.ts.net:8765/mcp/",
      "headers": { "Authorization": "Bearer PASTE_TOKEN_HERE" }
    }
  }
}
```

The token lives **only** here and on the host — never in the repo. Provider keys
(Anthropic/NVIDIA/Google) are **not** entered here; they go on the host for
LiteLLM in Step 7.

---

## 5. Restart the session

Quit and reopen Claude Desktop (and, if you drive from a Cowork session via the
bridge, restart that session). The new MCP server surfaces after restart — safe,
because all state is in GitHub + the token file. The agent's tools appear as
`gdv-node-agent__*` (or `mcp__remote-devices__nodeagent__*` where the desktop
bridge proxies them into Cowork).

---

## 6. Run T6 + T7 (the local-phase acceptance tests)

From a checkout on the Mac (these are marked `local` and skipped in CI):

```bash
cd gdv-node-agent
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"

export GDV_AGENT_URL="http://hermes-brain.tailab8826.ts.net:8765/mcp/"
export GDV_AGENT_TOKEN="$(tailscale ssh root@hermes-brain sudo cat /etc/gdv-node-agent/token)"
pytest -m local -v
```

- **T7** (`ping` through the remote MCP over Tailscale) should pass immediately.
- **T6** calls `hermes.install` then checks `hermes --version` reports `0.19.1`.
  You can also do T6 conversationally in Claude Desktop (Step 7).

---

## 7. Install Hermes + LiteLLM THROUGH the agent

Now the payoff — no more SSH paste. In Claude Desktop, drive the agent's tools:

1. **Hermes** — call `hermes.install` (idempotent; runs
   `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`, pinned
   `0.19.1`). Verify with `run_command("hermes --version")`.
2. **LiteLLM** — put the provider keys on the host (never through chat), drop the
   `litellm.config.yaml` from the Stage A starter, create a `litellm` systemd
   unit, then manage it with `litellm.control("start")` / `("status")`.
3. **Point Hermes at LiteLLM** (`base_url: http://localhost:4000`) and run one
   routed LLM call to confirm the path end-to-end.
4. `hermes.restart` / `litellm.control("restart")` as needed; `tail_logs("hermes")`
   to watch.

At this point the box is managed entirely through the agent, and interactive SSH
is break-glass only. Update `Build Plans/stage-a-setup/PROGRESS.md` and the
Decision Log's Execution Log, and fill in BP-001 §6.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| unit exits: `refusing to bind …` | `GDV_AGENT_HOST` not Tailscale/loopback (T2) | set it to the `100.x` IP; re-run bootstrap |
| unit exits: `no auth token configured` | token file empty/unreadable by `nodeagent` | check `/etc/gdv-node-agent/token` is `0640 root:nodeagent` |
| `401` from every call | wrong/missing bearer in Claude Desktop config | re-paste the token; restart the session |
| `service_control` returns `active:false` after restart | scoped sudo not applied | confirm `/etc/sudoers.d/gdv-node-agent` present + `visudo -c` clean |
| `sudo: a password is required` in logs | sudoers NOPASSWD entry missing the exact command | it must match the unit allowlist; re-run bootstrap |

---

*GDV Agentic Orchestrator · Node Agent · local deploy phase (BP-001 Steps 6–8).*
