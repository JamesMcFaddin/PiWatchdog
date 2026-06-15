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

# AdProcess normally touches the heartbeat every loop. During a large sync,
# a healthy heartbeat can legitimately be several minutes old.
HEALTHY_SECONDS = 6 * 60          # expected healthy upper bound
STALL_NOTICE_SECONDS = 8 * 60     # suspicious, but not yet recovery-worthy
STALE_SECONDS = 15 * 60           # first-strike restart / second-strike reboot
RESTART_CLEAR_HEALTHY_SECONDS = 10 * 60


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
        "healthy_since": 0.0,
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
            "healthy_since": float(obj.get("healthy_since", 0.0)),
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


def update_stall_state(mon_time: float, age: float, now: float) -> None:
    """
    Track heartbeat stalls without waiting for a watchdog recovery action.

    Also expires restart_done after a sustained healthy period. The restart_done
    flag means "AdProcess has already had one first-strike restart since the last
    healthy run." It must not live forever, because a later unrelated stall
    should get its own first-strike restart before reboot escalation.
    """
    state = load_state()

    last_mon_time = float(state.get("last_mon_time", 0.0))
    stall_time = float(state.get("stall_time", 0.0))
    restart_done = bool(state.get("restart_done", False))
    healthy_since = float(state.get("healthy_since", 0.0))

    if last_mon_time <= 0.0:
        state["last_mon_time"] = mon_time
        state["stall_time"] = 0.0
        save_state(state)
        log_debug(f"state initialized last_mon_time={mon_time:.3f}")
        return

    # If AdProcess has been restarted once, forgive that first strike after
    # a sustained period of healthy heartbeats.
    if restart_done:
        if age <= HEALTHY_SECONDS:
            if healthy_since <= 0.0:
                state["healthy_since"] = now
                save_state(state)
                log_debug(
                    f"{PROCESS_NAME}.mon healthy after restart; "
                    f"healthy_since={now:.3f}"
                )
                return

            healthy_for = now - healthy_since
            if healthy_for >= RESTART_CLEAR_HEALTHY_SECONDS:
                state["restart_done"] = False
                state["healthy_since"] = 0.0
                state["stall_time"] = 0.0
                state["last_mon_time"] = mon_time
                save_state(state)

                log_info(
                    f"restart flag cleared after {format_minutes(healthy_for)} "
                    f"of healthy {PROCESS_NAME} heartbeats"
                )
                return
        else:
            if healthy_since > 0.0:
                state["healthy_since"] = 0.0
                save_state(state)
                log_debug(
                    f"{PROCESS_NAME}.mon no longer healthy; "
                    f"clearing healthy_since age={age:.1f}s"
                )

    # If age is growing past the notice threshold, remember the largest stall.
    if age > STALL_NOTICE_SECONDS and age > stall_time:
        state["stall_time"] = age
        state["last_mon_time"] = mon_time
        save_state(state)
        log_debug(
            f"{PROCESS_NAME}.mon stall observed age={age:.1f}s "
            f"stall_time={age:.1f}s"
        )
        return

    # If we had a stored stall and the heartbeat age is now lower,
    # AdProcess recovered before reaching the recovery/reboot threshold.
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


def _run_pkill(signal_name: str, pattern: str) -> None:
    try:
        subprocess.run(
            ["/usr/bin/pkill", signal_name, "-f", pattern],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        log_info(f"failed running pkill {signal_name} for pattern {pattern!r}: {e}")


def _process_exists(pattern: str) -> bool:
    try:
        proc = subprocess.run(
            ["/usr/bin/pgrep", "-f", pattern],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode == 0 and bool((proc.stdout or "").strip())
    except Exception as e:
        log_info(f"failed running pgrep for pattern {pattern!r}: {e}")
        return False


def kill_adprocess_and_vlc() -> None:
    log_info("Stopping AdProcess and VLC/cvlc...")

    # Ask AdProcess politely first. If it is hung, it may not respond.
    _run_pkill("-TERM", "AdProcess.py")
    time.sleep(10)

    if _process_exists("AdProcess.py"):
        log_info("AdProcess did not exit after SIGTERM; forcing SIGKILL")
        _run_pkill("-KILL", "AdProcess.py")

    # Kill player after AdProcess has had a chance to stop it cleanly.
    _run_pkill("-TERM", "cvlc")
    _run_pkill("-TERM", "vlc")
    time.sleep(2)

    if _process_exists("cvlc"):
        _run_pkill("-KILL", "cvlc")
    if _process_exists("vlc"):
        _run_pkill("-KILL", "vlc")


def restart_adprocess(reason: str) -> int:
    """
    First-strike recovery:
      - Stop AdProcess and VLC/cvlc.
      - Remove stale monitor files.
      - Restart AdProcess.
      - Set restart_done=true in RAM state.

    If AdProcess hangs again before restart_done expires, PiWatchdog escalates
    to a full system reboot.
    """
    log_info(f"RESTART REQUIRED: {reason}")

    if not ADPROCESS_SCRIPT.exists():
        log_info(f"cannot restart AdProcess; missing script: {ADPROCESS_SCRIPT}")
        return 1

    kill_adprocess_and_vlc()
    delete_all_mon_files()

    uid = HOME_DIR.stat().st_uid
    env = os.environ.copy()
    env["HOME"] = str(HOME_DIR)
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")

    cmd = [
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
        state["healthy_since"] = 0.0
        state["stall_time"] = 0.0
        state["last_mon_time"] = 0.0
        save_state(state)

        log_info("AdProcess restart requested")
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

    now = time.time()
    age = now - mon_time

    update_stall_state(mon_time, age, now)

    if age <= HEALTHY_SECONDS:
        log_debug(f"{PROCESS_NAME}.mon healthy age={age:.1f}s")
        return 0

    if age < STALL_NOTICE_SECONDS:
        log_debug(
            f"{PROCESS_NAME}.mon slow-but-acceptable "
            f"age={age:.1f}s healthy_limit={HEALTHY_SECONDS}s"
        )
        return 0

    if age < STALE_SECONDS:
        log_debug(
            f"{PROCESS_NAME}.mon stale-but-within-limit "
            f"age={age:.1f}s restart_limit={STALE_SECONDS}s"
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
            f"{PROCESS_NAME}.mon stale again before restart flag expired "
            f"age={age:.1f}s"
        )

    return restart_adprocess(f"{PROCESS_NAME}.mon stale age={age:.1f}s")


if __name__ == "__main__":
    raise SystemExit(main())
