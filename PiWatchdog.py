#!/usr/bin/env python3
# [PiWatchdog.py] - [PiWatchdog] System
# Copyright (c) 2026 James Eddy (James McFaddin)
# This software is licensed under the MIT License.
# See the LICENSE file or https://opensource.org/licenses/MIT for details.
# [PiWatchdog.py] Monitor AdProcess.mon and recover/reboot if it goes stale.

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os
import pwd
import subprocess
import time


# -----------------------------------------------------------------------------
# Path setup
# -----------------------------------------------------------------------------

def _get_ram_base() -> Path:
    try:
        ram = Path("/dev/shm")
        if ram.exists() and ram.is_dir():
            return ram
    except Exception:
        pass

    return Path("/tmp")


SCRIPT_DIR: Path = Path(__file__).resolve().parent
HOME_DIR: Path = SCRIPT_DIR.parent

RAM_BASE: Path = _get_ram_base()
RUNTIME_DIR: Path = RAM_BASE / "AdProcess"
FLAGS_DIR: Path = RUNTIME_DIR / "Flags"

DEBUG_FLAG: Path = FLAGS_DIR / "debug-PiWatchdog"

PROCESS_NAME = "AdProcess"
MON_FILE: Path = FLAGS_DIR / f"{PROCESS_NAME}.mon"
STATE_FILE: Path = FLAGS_DIR / "PiWatchdog.state"

ADPROCESS_SCRIPT: Path = HOME_DIR / "AdProcess" / "AdProcess.py"

STALE_SECONDS = 15 * 60  # 15 minutes
STALL_NOTICE_SECONDS = 30.0


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

def debug_enabled() -> bool:
    return DEBUG_FLAG.exists()


def log_info(msg: str) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{now} [PiWatchdog] {msg}", flush=True)


def log_debug(msg: str) -> None:
    if debug_enabled():
        log_info(msg)


# -----------------------------------------------------------------------------
# State helpers
# -----------------------------------------------------------------------------

def default_state() -> dict[str, Any]:
    return {
        "last_mon_time": 0.0,
        "stall_time": 0.0,
        "restart_done": False,
    }


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return default_state()

    try:
        raw = STATE_FILE.read_text(encoding="utf-8").strip()

        if not raw:
            return default_state()

        obj: Any = json.loads(raw)

        if not isinstance(obj, dict):
            return default_state()

        return {
            "last_mon_time": float(obj.get("last_mon_time", 0.0)),
            "stall_time": float(obj.get("stall_time", 0.0)),
            "restart_done": bool(obj.get("restart_done", False)),
        }

    except Exception as e:
        log_info(f"failed to read state file {STATE_FILE}: {e}")
        return default_state()


def save_state(state: dict[str, Any]) -> None:
    try:
        FLAGS_DIR.mkdir(parents=True, exist_ok=True)

        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(STATE_FILE)

    except Exception as e:
        log_info(f"failed to write state file {STATE_FILE}: {e}")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def file_mtime_seconds(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except Exception as e:
        log_info(f"stat failed for {path}: {e}")
        return 0.0


def format_minutes(seconds: float) -> str:
    return f"{seconds / 60.0:.1f} minutes"


def update_stall_state(mon_time: float, age: float) -> None:
    """
    Track heartbeat stalls without waiting for a watchdog recovery action.
    """
    state = load_state()

    last_mon_time = float(state.get("last_mon_time", 0.0))
    stall_time = float(state.get("stall_time", 0.0))

    if last_mon_time <= 0.0:
        state["last_mon_time"] = mon_time
        state["stall_time"] = 0.0
        save_state(state)
        log_debug(f"state initialized last_mon_time={mon_time:.3f}")
        return

    if age > STALL_NOTICE_SECONDS and age > stall_time:
        state["stall_time"] = age
        state["last_mon_time"] = mon_time
        save_state(state)
        log_debug(
            f"{PROCESS_NAME}.mon stall observed age={age:.1f}s "
            f"stall_time={age:.1f}s"
        )
        return

    if stall_time > STALL_NOTICE_SECONDS and age < stall_time:
        estimated_start = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(time.time() - stall_time),
        )

        log_info(
            f"{PROCESS_NAME} stalled for {format_minutes(stall_time)} "
            f"and recovered; estimated stall start: {estimated_start}"
        )

        state["stall_time"] = 0.0
        state["last_mon_time"] = mon_time
        save_state(state)
        return

    if mon_time != last_mon_time:
        state["last_mon_time"] = mon_time
        save_state(state)


def delete_all_mon_files() -> None:
    try:
        if not FLAGS_DIR.exists():
            log_debug(f"flags dir missing; no .mon files to delete: {FLAGS_DIR}")
            return

        mon_files = sorted(FLAGS_DIR.glob("*.mon"))

        if not mon_files:
            log_debug(f"no .mon files found in {FLAGS_DIR}")
            return

        for mon_file in mon_files:
            try:
                mon_file.unlink()
                log_debug(f"deleted monitor file: {mon_file}")
            except Exception as e:
                log_info(f"failed to delete monitor file {mon_file}: {e}")

    except Exception as e:
        log_info(f"exception while deleting .mon files: {e}")


def _kill_matching_processes(pattern: str) -> None:
    try:
        subprocess.run(
            ["/usr/bin/pkill", "-9", "-f", pattern],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        log_info(f"failed running pkill for pattern {pattern!r}: {e}")


def kill_adprocess_and_vlc() -> None:
    log_info("Stopping AdProcess and VLC/cvlc...")

    # Kill player first so stale video does not keep playing.
    _kill_matching_processes("cvlc")
    _kill_matching_processes("vlc")

    # Then kill the stuck AdProcess process.
    _kill_matching_processes("AdProcess.py")


def _deployment_user() -> str:
    try:
        st = HOME_DIR.stat()
        return pwd.getpwuid(st.st_uid).pw_name
    except Exception:
        return "astepup"


def restart_adprocess(reason: str) -> int:
    """
    First-strike recovery:
      - Kill AdProcess and VLC/cvlc.
      - Remove stale monitor files.
      - Restart AdProcess.
      - Set restart_done=true in RAM state.

    If AdProcess hangs again before the next reboot, PiWatchdog escalates
    to a full system reboot.
    """
    log_info(f"RESTART REQUIRED: {reason}")

    if not ADPROCESS_SCRIPT.exists():
        log_info(f"cannot restart AdProcess; missing script: {ADPROCESS_SCRIPT}")
        return 1

    kill_adprocess_and_vlc()
    delete_all_mon_files()

    user = _deployment_user()
    uid = HOME_DIR.stat().st_uid

    env = os.environ.copy()
    env["HOME"] = str(HOME_DIR)
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")

    cmd = [
        "/usr/sbin/runuser",
        "-u",
        user,
        "--",
        "/usr/bin/python3",
        str(ADPROCESS_SCRIPT),
    ]

    try:
        subprocess.Popen(
            cmd,
            cwd=str(HOME_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        state = load_state()
        state["restart_done"] = True
        state["stall_time"] = 0.0
        state["last_mon_time"] = 0.0
        save_state(state)

        log_info(f"AdProcess restart requested as user {user}")
        return 0

    except Exception as e:
        log_info(f"exception while restarting AdProcess: {e}")
        return 1


def reboot_system(reason: str) -> int:
    log_info(f"REBOOT REQUIRED: {reason}")

    state = load_state()
    state["restart_done"] = False
    save_state(state)

    delete_all_mon_files()

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
        f"start home_dir={HOME_DIR} runtime_dir={RUNTIME_DIR} flags_dir={FLAGS_DIR} "
        f"mon_file={MON_FILE} state_file={STATE_FILE}"
    )

    if not MON_FILE.exists():
        log_debug(f"monitor file missing; nothing to do: {MON_FILE}")
        return 0

    mon_time = file_mtime_seconds(MON_FILE)

    if mon_time <= 0.0:
        log_info(f"unable to read monitor file time: {MON_FILE}")
        return 0

    age = time.time() - mon_time

    update_stall_state(mon_time, age)

    if age <= STALL_NOTICE_SECONDS:
        log_debug(f"{PROCESS_NAME}.mon fresh age={age:.1f}s")
        return 0

    if age < STALE_SECONDS:
        log_debug(
            f"{PROCESS_NAME}.mon stale-but-within-limit "
            f"age={age:.1f}s limit={STALE_SECONDS}s"
        )
        return 0

    state = load_state()
    restart_done = bool(state.get("restart_done", False))

    log_info(
        f"{PROCESS_NAME}.mon timed out age={age:.1f}s "
        f"restart_done={restart_done}"
    )

    if restart_done:
        return reboot_system(
            f"{PROCESS_NAME}.mon stale again after AdProcess restart "
            f"age={age:.1f}s"
        )

    return restart_adprocess(f"{PROCESS_NAME}.mon stale age={age:.1f}s")


if __name__ == "__main__":
    raise SystemExit(main())
