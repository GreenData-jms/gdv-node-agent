#!/usr/bin/env bash
#
# GDV Node Agent — Hermes provisioner (idempotent, verify-then-exec)
# ==================================================================
# Runs as the UNPRIVILEGED `hermes` workload user, invoked by the
# `hermes-install.service` oneshot unit — NOT by the agent's own sandbox and
# NOT as root. It installs the pinned Hermes release into the workload's state
# directory (/var/lib/hermes), keeping the control plane (gdv-node-agent) and
# the workload (Hermes) on separate identities and separate filesystems.
#
# Supply chain (ADR-002): the installer is pinned by SHA-256 and VERIFIED before
# it is executed — no unauthenticated `curl | bash`. The expected Hermes version
# is asserted after install; a mismatch fails the unit.
#
# Idempotent: if the pinned version is already present it prints `skip` and
# exits 0 without touching the network.
#
# Configuration comes from the unit's Environment= (all overridable there):
#   HOME                     workload state root (StateDirectory)  e.g. /var/lib/hermes
#   HERMES_HOME              Hermes data dir                       default $HOME/.hermes
#   HERMES_INSTALL_DIR       Hermes code dir                       default $HOME/hermes-agent
#   HERMES_INSTALLER_URL     installer URL
#   HERMES_INSTALLER_SHA256  pinned sha256 of the installer        (verified before exec)
#   HERMES_EXPECTED_VERSION  version `hermes --version` must report (e.g. 0.19.1)
#   HERMES_SKIP_BROWSER      "1" (default) to skip Playwright/Chromium (needs root libs)

set -euo pipefail

: "${HOME:?HOME must be set by the unit (workload state root)}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_INSTALL_DIR="${HERMES_INSTALL_DIR:-$HOME/hermes-agent}"
HERMES_INSTALLER_URL="${HERMES_INSTALLER_URL:-https://hermes-agent.nousresearch.com/install.sh}"
HERMES_INSTALLER_SHA256="${HERMES_INSTALLER_SHA256:?pin the installer sha256 in the unit}"
HERMES_EXPECTED_VERSION="${HERMES_EXPECTED_VERSION:?set the expected Hermes version in the unit}"
HERMES_SKIP_BROWSER="${HERMES_SKIP_BROWSER:-1}"

BIN="$HOME/.local/bin/hermes"

log()  { printf '\033[1;32m[hermes-provision]\033[0m %s\n' "$*"; }
skip() { printf '\033[1;33m[hermes-provision] skip:\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[hermes-provision] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

installed_version() {
  [[ -x "$BIN" ]] || return 1
  # `hermes --version` prints e.g. "Hermes Agent v0.19.1 (2026.7.30)"
  "$BIN" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1
}

current="$(installed_version || true)"
if [[ "$current" == "$HERMES_EXPECTED_VERSION" ]]; then
  skip "hermes ${HERMES_EXPECTED_VERSION} already present at ${BIN}"
  exit 0
fi

log "provisioning hermes ${HERMES_EXPECTED_VERSION} into ${HOME} (current: ${current:-none})"

tmp="$(mktemp "${TMPDIR:-/tmp}/hermes-install.XXXXXX.sh")"
trap 'rm -f "$tmp"' EXIT

log "downloading installer: ${HERMES_INSTALLER_URL}"
curl -fsSL --max-time 60 -o "$tmp" "$HERMES_INSTALLER_URL" \
  || die "failed to download installer"

log "verifying installer sha256 (pinned)"
echo "${HERMES_INSTALLER_SHA256}  ${tmp}" | sha256sum -c - \
  || die "installer checksum mismatch — refusing to execute (supply-chain gate)"

extra=()
[[ "$HERMES_SKIP_BROWSER" == "1" ]] && extra+=(--skip-browser)

log "running verified installer (non-interactive) ${extra[*]:-}"
HERMES_HOME="$HERMES_HOME" \
HERMES_INSTALL_DIR="$HERMES_INSTALL_DIR" \
  bash "$tmp" --non-interactive "${extra[@]}"

got="$(installed_version || true)"
[[ "$got" == "$HERMES_EXPECTED_VERSION" ]] \
  || die "post-install version mismatch: got '${got:-none}', expected ${HERMES_EXPECTED_VERSION}"

log "hermes ${got} provisioned OK at ${BIN}"
