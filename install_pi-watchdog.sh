#!/usr/bin/env bash
# [install_pi-watchdog.sh] - [PiWatchdog] System
# Copyright (c) 2026 James Eddy (James McFaddin)
# This software is licensed under the MIT License.
# See the LICENSE file or https://opensource.org/licenses/MIT for details.
# [install_pi-watchdog.sh] Install or refresh the PiWatchdog systemd timer/service.

set -u

# -----------------------------------------------------------------------------
# Resolve paths SAME as PiWatchdog.py
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR="$(dirname "${SCRIPT_DIR}")"
FLAGS_DIR="${HOME_DIR}/Flags"

SCRIPT_NAME="PiWatchdog.py"
SERVICE_NAME="pi-watchdog.service"
TIMER_NAME="pi-watchdog.timer"

SCRIPT_PATH="${SCRIPT_DIR}/${SCRIPT_NAME}"
SERVICE_TEMPLATE="${SCRIPT_DIR}/systemd/${SERVICE_NAME}"
TIMER_SRC="${SCRIPT_DIR}/systemd/${TIMER_NAME}"

SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}"
TIMER_DST="/etc/systemd/system/${TIMER_NAME}"

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

log() {
    echo "[install_pi-watchdog] $1"
}

fail() {
    echo "[install_pi-watchdog] ERROR: $1" >&2
    exit 1
}

# -----------------------------------------------------------------------------
# Checks
# -----------------------------------------------------------------------------

if [[ "${EUID}" -ne 0 ]]; then
    fail "Please run this script with sudo."
fi

[[ -f "${SCRIPT_PATH}" ]] || fail "Missing ${SCRIPT_PATH}"
[[ -f "${SERVICE_TEMPLATE}" ]] || fail "Missing ${SERVICE_TEMPLATE}"
[[ -f "${TIMER_SRC}" ]] || fail "Missing ${TIMER_SRC}"

log "SCRIPT_DIR=${SCRIPT_DIR}"
log "HOME_DIR=${HOME_DIR}"
log "FLAGS_DIR=${FLAGS_DIR}"

# -----------------------------------------------------------------------------
# Determine overall mode
# -----------------------------------------------------------------------------

if [[ -f "${SERVICE_DST}" || -f "${TIMER_DST}" ]]; then
    MODE="UPDATE"
    log "Mode: UPDATE (existing installation detected)"
else
    MODE="INSTALL"
    log "Mode: INSTALL (fresh setup)"
fi

# -----------------------------------------------------------------------------
# Ensure flags directory exists
# -----------------------------------------------------------------------------

if [[ -d "${FLAGS_DIR}" ]]; then
    log "Flags: exists (${FLAGS_DIR})"
else
    log "Flags: creating ${FLAGS_DIR}"
fi

install -d "${FLAGS_DIR}" || fail "Failed to create ${FLAGS_DIR}"

# -----------------------------------------------------------------------------
# Stop active units before replacing files
# -----------------------------------------------------------------------------

log "Stopping existing watchdog units (if running)..."
systemctl stop "${TIMER_NAME}" 2>/dev/null || true
systemctl stop "${SERVICE_NAME}" 2>/dev/null || true

# -----------------------------------------------------------------------------
# Install systemd service (replace placeholder)
# -----------------------------------------------------------------------------

if [[ -f "${SERVICE_DST}" ]]; then
    log "Service: updating existing ${SERVICE_NAME}"
else
    log "Service: installing new ${SERVICE_NAME}"
fi

tmp_service="$(mktemp)" || fail "Failed to create temp file"

sed "s|__PIWATCHDOG_SCRIPT__|${SCRIPT_PATH}|g" "${SERVICE_TEMPLATE}" > "${tmp_service}" \
    || fail "Failed to generate service file"

install -m 644 "${tmp_service}" "${SERVICE_DST}" \
    || fail "Failed to install ${SERVICE_DST}"

rm -f "${tmp_service}"

# -----------------------------------------------------------------------------
# Install timer
# -----------------------------------------------------------------------------

if [[ -f "${TIMER_DST}" ]]; then
    log "Timer: updating existing ${TIMER_NAME}"
else
    log "Timer: installing new ${TIMER_NAME}"
fi

install -m 644 "${TIMER_SRC}" "${TIMER_DST}" \
    || fail "Failed to install ${TIMER_DST}"

# -----------------------------------------------------------------------------
# Reload systemd
# -----------------------------------------------------------------------------

log "Systemd: daemon-reload"
systemctl daemon-reload || fail "daemon-reload failed"

# -----------------------------------------------------------------------------
# Enable timer
# -----------------------------------------------------------------------------

if systemctl is-enabled "${TIMER_NAME}" >/dev/null 2>&1; then
    log "Timer: already enabled"
else
    log "Timer: enabling"
fi

systemctl enable "${TIMER_NAME}" >/dev/null || fail "enable failed"

# -----------------------------------------------------------------------------
# Restart timer
# -----------------------------------------------------------------------------

log "Timer: restarting ${TIMER_NAME}"
systemctl restart "${TIMER_NAME}" || fail "restart failed"

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------

log "Install complete."
log "Script path: ${SCRIPT_PATH}"
log "Flags dir: ${FLAGS_DIR}"
