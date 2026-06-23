#!/usr/bin/env bash
# [install_pi-watchdog.sh] - [PiWatchdog] System
# Copyright (c) 2026 James Eddy (James McFaddin)
# This software is licensed under the MIT License.
# See the LICENSE file or https://opensource.org/licenses/MIT for details.
# [install_pi-watchdog.sh] Install the PiWatchdog systemd timer/service.

set -u

# -----------------------------------------------------------------------------
# Resolve paths SAME as PiWatchdog.py
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR="$(dirname "${SCRIPT_DIR}")"
PFLAGS_DIR="${HOME_DIR}/PFlags"

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
log "PFLAGS_DIR=${PFLAGS_DIR}"

# -----------------------------------------------------------------------------
# Ensure persistent flags directory exists
# -----------------------------------------------------------------------------

mkdir -p "${PFLAGS_DIR}" || fail "Failed to create ${PFLAGS_DIR}"

# -----------------------------------------------------------------------------
# Install systemd service (replace placeholder)
# -----------------------------------------------------------------------------

log "Installing ${SERVICE_NAME}..."

sed "s|__PIWATCHDOG_SCRIPT__|${SCRIPT_PATH}|g" "${SERVICE_TEMPLATE}" > "${SERVICE_DST}" \
    || fail "Failed to generate ${SERVICE_DST}"

# Safety net:
# Ensure the installed oneshot service does not kill AdProcess when PiWatchdog
# launches it and then exits.
if ! grep -q "^KillMode=process$" "${SERVICE_DST}"; then
    sed -i '/^\[Service\]/a KillMode=process' "${SERVICE_DST}" \
        || fail "Failed to add KillMode=process to ${SERVICE_DST}"
fi

chmod 644 "${SERVICE_DST}" || fail "Failed to chmod ${SERVICE_DST}"

# -----------------------------------------------------------------------------
# Install timer
# -----------------------------------------------------------------------------

log "Installing ${TIMER_NAME}..."

cp -f "${TIMER_SRC}" "${TIMER_DST}" \
    || fail "Failed to copy ${TIMER_NAME}"

chmod 644 "${TIMER_DST}" || fail "Failed to chmod ${TIMER_DST}"

# -----------------------------------------------------------------------------
# Enable + start
# -----------------------------------------------------------------------------

log "Reloading systemd..."
systemctl daemon-reload || fail "daemon-reload failed"

log "Enabling timer..."
systemctl enable "${TIMER_NAME}" || fail "enable failed"

log "Restarting timer..."
systemctl restart "${TIMER_NAME}" || fail "restart failed"

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------

log "Install complete."
log "Script path: ${SCRIPT_PATH}"
log "Persistent flags dir: ${PFLAGS_DIR}"
