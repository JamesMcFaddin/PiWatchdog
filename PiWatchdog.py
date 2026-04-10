#!/usr/bin/env python3
# [PiWatchdog.py] - [PiWatchdog] System
# Copyright (c) 2026 James Eddy (James McFaddin)
# This software is licensed under the MIT License.
# See the LICENSE file or https://opensource.org/licenses/MIT for details.
# [PiWatchdog.py] Monitor AdProcess.mon and reboot the system if it goes stale.

from __future__ import annotations

from pathlib import Path
import subprocess
import time


# -----------------------------------------------------------------------------
# Path setup
# -----------------------------------------------------------------------------

# Resolve the absolute directory of the running script
# And use its parent as HOME_DIR
SCRIPT_DIR = Path(__file__).resolve().parent
HOME_DIR = SCRIPT_DIR.parent
FLAGS_DIR = HOME_DIR / "flags"
DEBUG_FLAG = FLAGS_DIR / "debug"

# Hardcoded for now
PROCESS_NAME = "AdProcess"
MON_FILE = FLAGS_DIR / f"{PROCESS_NAME}.mon"
STATE_FILE = FLAGS_DIR / f"{PROCESS_NAME}.watchdog.state"

# Process should touch every 30 seconds
# Watchdog runs every 30 seconds
# Reboot if heartbeat gets older than 1 hour
STALE_SECONDS = 60 * 60  # 1 hour


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

def debug_enabled() -> bool:
    return DEBUG_FLAG.exists()


def log_info(msg: str) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{now} [PiProcessWatchdog] {msg}", flush=True)


def log_debug(msg: str) -> None:
    if debug_enabled():
        log_info(msg)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def file_age_seconds(path: Path) -> float:
    try:
        return time.time() - path.stat().st_mtime
    except Exception as e:
        log_info(f"stat failed for {path}: {e}")
        return 999999999.0


def mark_stale_logged() -> None:
    try:
        STATE_FILE.touch(exist_ok=True)
    except Exception as e:
        log_info(f"failed to create state file {STATE_FILE}: {e}")


def clear_stale_logged() -> None:
    try:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
    except Exception as e:
        log_info(f"failed to delete state file {STATE_FILE}: {e}")


def stale_already_logged() -> bool:
    return STATE_FILE.exists()


def reboot_system(reason: str) -> int:
    log_info(f"REBOOT REQUIRED: {reason}")
    try:
        proc = subprocess.run(
            ["/usr/bin/systemctl", "reboot"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            detail = stderr if stderr else stdout
            log_info(f"reboot command failed rc={proc.returncode}: {detail}")

        return proc.returncode

    except Exception as e:
        log_info(f"exception while trying to reboot: {e}")
        return 1


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    log_debug(
        f"start home_dir={HOME_DIR} flags_dir={FLAGS_DIR} "
        f"mon_file={MON_FILE} state_file={STATE_FILE}"
    )

    # Do nothing unless the monitored process has created its .mon file.
    if not MON_FILE.exists():
        log_debug(f"monitor file missing; nothing to do: {MON_FILE}")
        return 0

    age = file_age_seconds(MON_FILE)

    # Fresh heartbeat
    if age <= STALE_SECONDS:
        if stale_already_logged():
            log_info(f"{PROCESS_NAME}.mon recovered age={age:.1f}s")
            clear_stale_logged()
        else:
            log_debug(f"{PROCESS_NAME}.mon fresh age={age:.1f}s")
        return 0

    # Stale heartbeat
    if not stale_already_logged():
        log_info(f"{PROCESS_NAME}.mon timed out age={age:.1f}s")
        mark_stale_logged()
    else:
        log_debug(f"{PROCESS_NAME}.mon still stale age={age:.1f}s")

    return reboot_system(f"{PROCESS_NAME}.mon stale age={age:.1f}s")


if __name__ == "__main__":
    raise SystemExit(main())