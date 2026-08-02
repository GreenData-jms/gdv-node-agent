# GDV Node Agent — build & deploy checklist (BP-001)

*Living tracker for the Node Agent effort. Cloud phase = built/tested/green in this
repo (Claude Code, unattended). Local phase = run by JMS from the Tailscale-connected
Mac (needs the mesh + `hermes-brain`). Source of truth: `BP-001` / `ADR-002` in the
`gdv-agentic-orchestrator` design repo.*

**Status:** cloud phase **complete & CI-green**; local deploy phase **pending**.
**PRs:** [#1 security core](https://github.com/GreenData-jms/gdv-node-agent/pull/1) · [#2 hermes + bootstrap + DEPLOY.md](https://github.com/GreenData-jms/gdv-node-agent/pull/2)

---

## ✅ Cloud phase — done (this repo)

### BP-001 §4 work breakdown (Steps 1–6, cloud portions)
- [x] **Step 1** — repo scaffolded; GitHub Actions CI (py3.11/3.12) green on `ping`
- [x] **Step 2** — base tools (`run_command`, `read_file`, `write_file`, `service_control`, `tail_logs`, `list_plugins`) + error-dict discipline + append-only audit log
- [x] **Step 3** — security core: Tailscale-bind guard, bearer auth, destructive-command block
- [x] **Step 4** — plugin loader (allowlist + per-plugin SHA-256 manifest) + `list_plugins`
- [x] **Step 5 (code)** — `hermes` plugin: `hermes.install`/`upgrade`/`restart`, `litellm.control`, `hermes.skills_pr_status` (+ signed manifest)
- [x] **Step 6 (authored)** — idempotent `bootstrap.sh`, `systemd` unit, least-priv `nodeagent` + scoped sudoers **written** (execution is local)

### Acceptance tests — the hard gate
- [x] **T1** unit — each tool, mocked subprocess/fs
- [x] **T2** bind guard — refuses `0.0.0.0`/public; Tailscale/loopback only
- [x] **T3** auth — rejects missing/bad token; refuses to start with no token
- [x] **T4** destructive block — `rm -rf`, `DROP`, `mkfs`, `dd of=/dev/*`, shutdown, fork bombs, raw-device writes
- [x] **T5** plugin integrity — altered/unsigned/unlisted ⇒ `verified:false`, never imported

### Deliverables
- [x] README + Claude Desktop registration snippet
- [x] `DEPLOY.md` local-phase runbook
- [x] `deploy/` — bootstrap, systemd unit, sudoers example
- [x] CI green on both PRs (99 tests; manifest-consistency guard)
- [x] Decisions applied: port **8765**, **per-plugin** manifests, dedicated repo
- [x] No secrets in repo; token generated on host at bootstrap

---

## ⛔ Local phase — to go (JMS, from the Tailscale Mac — see `DEPLOY.md`)

### BP-001 §4 work breakdown (Steps 6–8, execution)
- [ ] **Step 6 (run)** — execute `bootstrap.sh` on `hermes-brain`; confirm re-run prints only `skip`; agent runs as `nodeagent`
- [ ] **Step 7** — `systemctl enable --now gdv-node-agent`; confirm bound to the Tailscale `100.x` interface (not `0.0.0.0`)
- [ ] **Step 7** — register the agent's Tailscale URL + token in Mac Claude Desktop remote-MCP config; **restart the session**
- [ ] **Step 8** — install Hermes `0.19.1` + LiteLLM **through the agent**; one routed LLM call succeeds

### Acceptance tests — local
- [ ] **T6** — `hermes.install` on a scratch target; `hermes --version` → `0.19.1` via `run_command` (`pytest -m local`)
- [ ] **T7** — `ping` succeeds through Claude Desktop + bridge over Tailscale (`pytest -m local`)

### Close-out
- [ ] Tag a signed release once T6/T7 pass on the host
- [ ] Merge PR #1 → PR #2 → `main`
- [ ] Update design repo: `Build Plans/stage-a-setup/PROGRESS.md`, Decision Log Execution Log, BP-001 §6 completion report, runbook → v2.4 (agent-first)

---

## Deferred (out of v0 scope per BP-001 §2)
- [ ] Full plugin framework (discovery/negotiation/hot-reload/versioned capabilities)
- [ ] `nemoclaw` / `openclaw` plugins
- [ ] Central multi-box node registry / control plane
- [ ] mTLS / OAuth 2.1 (seam built; ship bearer v0)
- [ ] Golden-image/snapshot baking
- [ ] cosign-style plugin signing (v0 = allowlist + SHA-256 manifest)

---

*Tick the local-phase boxes as they complete. Cloud phase is frozen behind CI.*
