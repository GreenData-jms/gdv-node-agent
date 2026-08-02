#!/usr/bin/env bash
#
# GDV Node Agent — bootstrap (idempotent)
# =======================================
# Runs ONCE as root (via cloud-init or a single SSH hop) to place the agent on a
# fresh box. It installs packages, creates the least-privilege `nodeagent` user,
# writes a SCOPED sudoers entry, generates the bearer token, installs the agent
# into a venv, and enables the systemd unit. After this, the agent — running as
# `nodeagent`, NOT root — is the control surface for the box.
#
# IDEMPOTENT: re-running only prints "skip" for work already done; it never
# regenerates the token or clobbers an existing install.
#
#   sudo GDV_AGENT_HOST=100.126.235.73 ./bootstrap.sh
#
# Do NOT run this from the cloud session — it belongs to the local deploy phase
# (see DEPLOY.md). It needs the target host.

set -euo pipefail

# --------------------------------------------------------------------------- #
# tunables (override via env)
# --------------------------------------------------------------------------- #
AGENT_USER="${AGENT_USER:-nodeagent}"
AGENT_HOME="${AGENT_HOME:-/opt/gdv-node-agent}"
AGENT_PORT="${GDV_AGENT_PORT:-8765}"
AGENT_PATH="${GDV_AGENT_MCP_PATH:-/mcp/}"
# Bind host: the box's Tailscale 100.x IP. REQUIRED — the agent refuses to bind
# to anything but Tailscale/loopback (T2). Pass GDV_AGENT_HOST explicitly.
AGENT_HOST="${GDV_AGENT_HOST:-}"
REPO_URL="${REPO_URL:-https://github.com/GreenData-jms/gdv-node-agent.git}"
REPO_REF="${REPO_REF:-main}"
CONFIG_DIR="/etc/gdv-node-agent"
TOKEN_FILE="${CONFIG_DIR}/token"
AUDIT_DIR="/var/log/gdv-node-agent"
UNITS="${GDV_AGENT_SERVICE_UNITS:-hermes:litellm:gdv-node-agent}"

log()  { printf '\033[1;32m[bootstrap]\033[0m %s\n' "$*"; }
skip() { printf '\033[1;33m[bootstrap] skip:\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[bootstrap] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "must run as root (cloud-init / sudo)"

if [[ -z "$AGENT_HOST" ]]; then
  # Best-effort auto-detect the Tailscale IP; still overridable.
  if command -v tailscale >/dev/null 2>&1; then
    AGENT_HOST="$(tailscale ip -4 2>/dev/null | head -n1 || true)"
  fi
fi
[[ -n "$AGENT_HOST" ]] || die "set GDV_AGENT_HOST to the box's Tailscale 100.x IP (agent refuses non-Tailscale bind)"

# --------------------------------------------------------------------------- #
# 1. packages
# --------------------------------------------------------------------------- #
if ! command -v python3.11 >/dev/null 2>&1; then
  log "installing packages (python3.11, venv, git, curl)"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3.11 python3.11-venv python3-pip git curl ca-certificates sudo
else
  skip "python3.11 present"
fi

# --------------------------------------------------------------------------- #
# 2. least-privilege user
# --------------------------------------------------------------------------- #
if ! id "$AGENT_USER" >/dev/null 2>&1; then
  log "creating system user ${AGENT_USER}"
  useradd --system --create-home --home-dir "/home/${AGENT_USER}" \
          --shell /usr/sbin/nologin "$AGENT_USER"
else
  skip "user ${AGENT_USER} exists"
fi

# --------------------------------------------------------------------------- #
# 3. code — clone/update into ${AGENT_HOME}
# --------------------------------------------------------------------------- #
if [[ ! -d "${AGENT_HOME}/.git" ]]; then
  log "cloning ${REPO_URL} -> ${AGENT_HOME}"
  git clone --branch "$REPO_REF" --depth 1 "$REPO_URL" "$AGENT_HOME"
else
  skip "repo present; fetching ${REPO_REF}"
  git -C "$AGENT_HOME" fetch --depth 1 origin "$REPO_REF"
  git -C "$AGENT_HOME" checkout -q "$REPO_REF"
  git -C "$AGENT_HOME" reset -q --hard "origin/${REPO_REF}"
fi

# --------------------------------------------------------------------------- #
# 4. venv + install
# --------------------------------------------------------------------------- #
if [[ ! -x "${AGENT_HOME}/.venv/bin/gdv-node-agent" ]]; then
  log "creating venv + installing agent"
  python3.11 -m venv "${AGENT_HOME}/.venv"
  "${AGENT_HOME}/.venv/bin/pip" install --quiet --upgrade pip
  "${AGENT_HOME}/.venv/bin/pip" install --quiet "${AGENT_HOME}"
else
  skip "venv + agent installed (re-running pip install to pick up updates)"
  "${AGENT_HOME}/.venv/bin/pip" install --quiet "${AGENT_HOME}"
fi

# --------------------------------------------------------------------------- #
# 5. auth token — generated ON THE HOST, root-owned, group-readable by the agent
# --------------------------------------------------------------------------- #
install -d -m 0750 -o root -g "$AGENT_USER" "$CONFIG_DIR"
if [[ ! -s "$TOKEN_FILE" ]]; then
  log "generating bearer token -> ${TOKEN_FILE}"
  umask 077
  openssl rand -hex 32 > "$TOKEN_FILE"
  chown root:"$AGENT_USER" "$TOKEN_FILE"
  chmod 0640 "$TOKEN_FILE"   # root writes; nodeagent reads via group; not world-readable
else
  skip "token already exists (not regenerating)"
fi

# audit dir owned by the agent
install -d -m 0750 -o "$AGENT_USER" -g "$AGENT_USER" "$AUDIT_DIR"
chown -R "$AGENT_USER":"$AGENT_USER" "$AGENT_HOME" 2>/dev/null || true

# --------------------------------------------------------------------------- #
# 6. scoped sudoers — ONLY the systemctl/journalctl the agent needs
# --------------------------------------------------------------------------- #
log "installing scoped sudoers for ${AGENT_USER}"
render_sudoers() {
  local units="${UNITS//:/ }"
  echo "# Managed by gdv-node-agent bootstrap. Scoped: only these commands, NOPASSWD."
  echo "Cmnd_Alias GDV_SYSTEMCTL = \\"
  local first=1
  for u in $units; do
    for a in start stop restart status is-active; do
      [[ $first -eq 1 ]] && first=0 || echo ", \\"
      printf '    /usr/bin/systemctl %s %s' "$a" "$u"
    done
  done
  echo ""
  echo "Cmnd_Alias GDV_JOURNAL = \\"
  first=1
  for u in $units; do
    [[ $first -eq 1 ]] && first=0 || echo ", \\"
    printf '    /usr/bin/journalctl -u %s *' "$u"
  done
  echo ""
  echo "${AGENT_USER} ALL=(root) NOPASSWD: GDV_SYSTEMCTL, GDV_JOURNAL"
}
render_sudoers > /etc/sudoers.d/gdv-node-agent
chmod 0440 /etc/sudoers.d/gdv-node-agent
visudo -cf /etc/sudoers.d/gdv-node-agent || die "sudoers validation failed"

# --------------------------------------------------------------------------- #
# 7. systemd unit
# --------------------------------------------------------------------------- #
log "installing systemd unit"
sed -e "s|@AGENT_USER@|${AGENT_USER}|g" \
    -e "s|@AGENT_HOME@|${AGENT_HOME}|g" \
    -e "s|@AGENT_HOST@|${AGENT_HOST}|g" \
    -e "s|@AGENT_PORT@|${AGENT_PORT}|g" \
    -e "s|@AGENT_PATH@|${AGENT_PATH}|g" \
    -e "s|@TOKEN_FILE@|${TOKEN_FILE}|g" \
    -e "s|@AUDIT_DIR@|${AUDIT_DIR}|g" \
    -e "s|@UNITS@|${UNITS}|g" \
    "${AGENT_HOME}/deploy/gdv-node-agent.service" > /etc/systemd/system/gdv-node-agent.service

systemctl daemon-reload
systemctl enable gdv-node-agent >/dev/null 2>&1 || true
log "bootstrap complete."
echo
echo "  Agent URL : http://${AGENT_HOST}:${AGENT_PORT}${AGENT_PATH}"
echo "  Token     : sudo cat ${TOKEN_FILE}   # paste into Claude Desktop config"
echo "  Start now : sudo systemctl start gdv-node-agent"
echo "  Logs      : journalctl -u gdv-node-agent -f"
echo
echo "Next: see DEPLOY.md (start the unit, confirm the Tailscale bind, register in"
echo "Claude Desktop, restart the session, run T6/T7, then install Hermes+LiteLLM"
echo "THROUGH the agent)."
