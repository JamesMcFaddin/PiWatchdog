#!/usr/bin/env python3
# [PiWatchdog.py] - [PiWatchdog] System
# Copyright (c) 2026 James Eddy (James McFaddin)
# This software is licensed under the MIT License.
# See the LICENSE file or https://opensource.org/licenses/MIT for details.
# [PiWatchdog.py] Monitor *.mon files and recover/reboot if they go stale.

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
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
PFLAGS_DIR: Path = HOME_DIR / "PFlags"

DEBUG_FLAG: Path = PFLAGS_DIR / "debug-PiWatchdog"
PDEBUG_ALL_FLAG: Path = PFLAGS_DIR / "debug-all"

STATE_FILE: Path = FLAGS_DIR / "PiWatchdog.state"
REBOOT_REQUESTED_FLAG: Path = FLAGS_DIR / "PiWatchdog.reboot"

HEALTHY_SECONDS = 6 * 60
STALL_NOTICE_SECONDS = 8 * 60
STALE_SECONDS = 15 * 60

DEFAULT_RESTART_CLEAR_HEALTHY_SECONDS = 10 * 60
DEFAULT_TERM_WAIT_SECONDS = 10


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

def debug_enabled() -> bool:
    return DEBUG_FLAG.exists() or PDEBUG_ALL_FLAG.exists()


def log_info(msg: str) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{now} [PiWatchdog] {msg}", flush=True)


def log_debug(msg: str) -> None:
    if debug_enabled():
        log_info(msg)


# -----------------------------------------------------------------------------
# State helpers
# -----------------------------------------------------------------------------

def default_component_state() -> dict[str, Any]:
    return {
        "last_mon_time": 0.0,
        "stall_time": 0.0,
        "restart_done": False,
        "launch_requested": False,
        "healthy_since": 0.0,
    }


def _normalize_component_state(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        return default_component_state()

    return {
        "last_mon_time": float(obj.get("last_mon_time", 0.0)),
        "stall_time": float(obj.get("stall_time", 0.0)),
        "restart_done": bool(obj.get("restart_done", False)),
        "launch_requested": bool(obj.get("launch_requested", False)),
        "healthy_since": float(obj.get("healthy_since", 0.0)),
    }


def default_state() -> dict[str, Any]:
    return {}


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

        # Backward compatibility for older flat AdProcess-only state files.
        if any(
            k in obj
            for k in (
                "last_mon_time",
                "stall_time",
                "restart_done",
                "restart_pending",
                "launch_requested",
                "healthy_since",
            )
        ):
            migrated = _normalize_component_state(obj)

            if bool(obj.get("restart_pending", False)):
                migrated["launch_requested"] = True

            return {
                "AdProcess": migrated,
            }

        state: dict[str, Any] = {}

        for component, component_obj in obj.items():
            if isinstance(component, str):
                state[component] = _normalize_component_state(component_obj)

        return state

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


def load_component_state(component: str) -> dict[str, Any]:
    state = load_state()
    component_state = state.get(component)

    if not isinstance(component_state, dict):
        component_state = default_component_state()
        state[component] = component_state
        save_state(state)

    return _normalize_component_state(component_state)


def save_component_state(component: str, component_state: dict[str, Any]) -> None:
    state = load_state()
    state[component] = _normalize_component_state(component_state)
    save_state(state)


def reset_component_to_launch_requested(component: str) -> None:
    state = load_state()
    state[component] = {
        "launch_requested": True,
    }
    save_state(state)


# -----------------------------------------------------------------------------
# Monitor contract helpers
# -----------------------------------------------------------------------------

def load_mon_contract(mon_file: Path) -> dict[str, Any] | None:
    try:
        raw = mon_file.read_text(encoding="utf-8").strip()

        if not raw:
            log_info(f"monitor file is empty: {mon_file}")
            return None

        obj: Any = json.loads(raw)

        if not isinstance(obj, dict):
            log_info(f"monitor file root is not an object: {mon_file}")
            return None

        name = obj.get("name")

        if not isinstance(name, str) or not name:
            log_info(f"monitor file missing valid name: {mon_file}")
            return None

        return obj

    except Exception as e:
        log_info(f"failed to read monitor contract {mon_file}: {e}")
        return None


def get_contract_name(contract: dict[str, Any], mon_file: Path) -> str:
    name = contract.get("name")

    if isinstance(name, str) and name:
        return name

    return mon_file.stem


def get_policy(contract: dict[str, Any]) -> dict[str, Any]:
    policy = contract.get("policy")

    if isinstance(policy, dict):
        return policy

    return {}


def get_stop(contract: dict[str, Any]) -> dict[str, Any]:
    stop = contract.get("stop")

    if isinstance(stop, dict):
        return stop

    return {}


def get_start(contract: dict[str, Any]) -> dict[str, Any]:
    start = contract.get("start")

    if isinstance(start, dict):
        return start

    return {}


def get_string_list(obj: dict[str, Any], key: str) -> list[str]:
    raw = obj.get(key)

    if not isinstance(raw, list):
        return []

    items: list[str] = []

    for item in raw:
        if isinstance(item, str) and item:
            items.append(item)

    return items


def get_float(obj: dict[str, Any], key: str, default_value: float) -> float:
    try:
        value = obj.get(key, default_value)
        return float(value)
    except Exception:
        return default_value


def get_bool(obj: dict[str, Any], key: str, default_value: bool) -> bool:
    value = obj.get(key, default_value)

    if isinstance(value, bool):
        return value

    return default_value


def get_clear_restart_seconds(contract: dict[str, Any]) -> float:
    policy = get_policy(contract)

    return get_float(
        policy,
        "clear_restart_after_seconds",
        DEFAULT_RESTART_CLEAR_HEALTHY_SECONDS,
    )


def get_stale_again_action(contract: dict[str, Any]) -> str:
    policy = get_policy(contract)
    action = policy.get("stale_again", "reboot")

    if isinstance(action, str) and action:
        return action.lower()

    return "reboot"


# -----------------------------------------------------------------------------
# General helpers
# -----------------------------------------------------------------------------

def file_mtime_seconds(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except Exception as e:
        log_info(f"stat failed for {path}: {e}")
        return 0.0


def format_minutes(seconds: float) -> str:
    return f"{seconds / 60.0:.1f} minutes"


def monitor_file_for_component(component: str) -> Path:
    return FLAGS_DIR / f"{component}.mon"


def archive_existing_file(path: Path) -> None:
    if not path.exists():
        return

    try:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        archived = path.with_name(f"{path.name}.{stamp}.old")
        path.replace(archived)
        log_info(f"existing file archived: {archived}")

    except Exception as e:
        log_info(f"failed to archive existing file {path}: {e}")


# -----------------------------------------------------------------------------
# Process helpers
# -----------------------------------------------------------------------------

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


def stop_component(component: str, contract: dict[str, Any]) -> None:
    stop = get_stop(contract)

    term_targets = get_string_list(stop, "term")
    kill_targets = get_string_list(stop, "kill")
    term_wait_seconds = get_float(
        stop,
        "term_wait_seconds",
        DEFAULT_TERM_WAIT_SECONDS,
    )

    if not term_targets and not kill_targets:
        log_info(f"{component}: no stop targets defined in monitor contract")
        return

    log_info(f"Stopping {component}...")

    for target in term_targets:
        log_debug(f"{component}: sending SIGTERM to {target!r}")
        _run_pkill("-TERM", target)

    if term_targets and term_wait_seconds > 0.0:
        time.sleep(term_wait_seconds)

    for target in kill_targets:
        if _process_exists(target):
            log_info(f"{component}: {target!r} still running; forcing SIGKILL")
            _run_pkill("-KILL", target)


# -----------------------------------------------------------------------------
# Launch helpers
# -----------------------------------------------------------------------------

def get_launch_path(component: str, start: dict[str, Any]) -> Path | None:
    raw_launch_file = start.get("launch_file", f"{component}.launch")

    if not isinstance(raw_launch_file, str) or not raw_launch_file:
        log_info(f"{component}: invalid launch_file in monitor contract")
        return None

    launch_name = Path(raw_launch_file).name

    if launch_name != raw_launch_file:
        log_info(
            f"{component}: launch_file must be a filename only, "
            f"not a path: {raw_launch_file!r}"
        )
        return None

    return FLAGS_DIR / launch_name


def get_command(component: str, start: dict[str, Any]) -> list[str] | None:
    raw_command = start.get("command")

    if not isinstance(raw_command, list):
        log_info(f"{component}: missing or invalid start.command list")
        return None

    command: list[str] = []

    for part in raw_command:
        if not isinstance(part, str) or not part:
            log_info(f"{component}: start.command must contain only non-empty strings")
            return None

        command.append(part)

    if not command:
        log_info(f"{component}: start.command cannot be empty")
        return None

    return command


def get_cwd(component: str, start: dict[str, Any]) -> str | None:
    raw_cwd = start.get("cwd", str(HOME_DIR))

    if not isinstance(raw_cwd, str) or not raw_cwd:
        log_info(f"{component}: invalid start.cwd")
        return None

    cwd_path = Path(raw_cwd).expanduser()

    if not cwd_path.exists() or not cwd_path.is_dir():
        log_info(f"{component}: start.cwd does not exist or is not a directory: {cwd_path}")
        return None

    return str(cwd_path)


def write_launch_file(component: str, contract: dict[str, Any], reason: str) -> bool:
    start = get_start(contract)

    launch_path = get_launch_path(component, start)

    if launch_path is None:
        return False

    command = get_command(component, start)

    if command is None:
        return False

    cwd = get_cwd(component, start)

    if cwd is None:
        return False

    detach = get_bool(start, "detach", True)

    try:
        FLAGS_DIR.mkdir(parents=True, exist_ok=True)
        archive_existing_file(launch_path)

        payload: dict[str, Any] = {
            "name": component,
            "command": command,
            "cwd": cwd,
            "detach": detach,
            "delete_on_success": True,
            "stdout": str(FLAGS_DIR / f"{component}.launcher.stdout.log"),
            "stderr": str(FLAGS_DIR / f"{component}.launcher.stderr.log"),
            "reason": reason,
            "requested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        tmp = launch_path.with_suffix(".tmp")

        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        tmp.replace(launch_path)

        log_info(f"{component}: launch request written: {launch_path}")
        return True

    except Exception as e:
        log_info(f"{component}: failed to write launch request {launch_path}: {e}")
        return False


def request_launch(component: str, mon_file: Path, contract: dict[str, Any], reason: str) -> int:
    log_info(f"{component}: LAUNCH REQUIRED: {reason}")

    stop_component(component, contract)

    if not write_launch_file(component, contract, reason):
        return 1

    reset_component_to_launch_requested(component)

    try:
        if mon_file.exists():
            mon_file.unlink()
            log_debug(f"{component}: deleted monitor file: {mon_file}")
    except Exception as e:
        log_info(f"{component}: failed to delete monitor file {mon_file}: {e}")

    log_info(f"{component}: launch request complete: launch_requested=True")
    return 0


def mark_launch_completed(component: str, mon_time: float, now: float) -> None:
    state = load_component_state(component)

    state["launch_requested"] = False
    state["restart_done"] = True
    state["healthy_since"] = now
    state["stall_time"] = 0.0
    state["last_mon_time"] = mon_time

    save_component_state(component, state)

    log_info(
        f"{component}.mon returned after launch request; "
        f"restart_done=True healthy_since={now:.3f}"
    )


# -----------------------------------------------------------------------------
# Stall / restart state
# -----------------------------------------------------------------------------

def update_stall_state(
    component: str,
    mon_file: Path,
    mon_time: float,
    age: float,
    now: float,
    clear_restart_after_seconds: float,
) -> None:
    state = load_component_state(component)

    last_mon_time = float(state.get("last_mon_time", 0.0))
    stall_time = float(state.get("stall_time", 0.0))
    restart_done = bool(state.get("restart_done", False))
    healthy_since = float(state.get("healthy_since", 0.0))

    if last_mon_time <= 0.0:
        state["last_mon_time"] = mon_time
        state["stall_time"] = 0.0
        save_component_state(component, state)
        log_debug(f"{component}: state initialized last_mon_time={mon_time:.3f}")
        return

    if restart_done:
        if age <= HEALTHY_SECONDS:
            if healthy_since <= 0.0:
                state["healthy_since"] = now
                save_component_state(component, state)
                log_debug(f"{component}.mon healthy after restart; healthy_since={now:.3f}")
                return

            healthy_for = now - healthy_since

            if healthy_for >= clear_restart_after_seconds:
                state["restart_done"] = False
                state["healthy_since"] = 0.0
                state["stall_time"] = 0.0
                state["last_mon_time"] = mon_time
                save_component_state(component, state)

                log_info(
                    f"{component}: restart flag cleared after "
                    f"{format_minutes(healthy_for)} of healthy heartbeats"
                )
                return

        else:
            if healthy_since > 0.0:
                state["healthy_since"] = 0.0
                save_component_state(component, state)
                log_debug(
                    f"{component}.mon no longer healthy; "
                    f"clearing healthy_since age={age:.1f}s"
                )

    if age > STALL_NOTICE_SECONDS and age > stall_time:
        state["stall_time"] = age
        state["last_mon_time"] = mon_time
        save_component_state(component, state)
        log_debug(
            f"{component}.mon stall observed age={age:.1f}s "
            f"stall_time={age:.1f}s"
        )
        return

    if stall_time > STALL_NOTICE_SECONDS and age < stall_time:
        estimated_start = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(time.time() - stall_time),
        )

        log_info(
            f"{component} stalled for {format_minutes(stall_time)} "
            f"and recovered; estimated stall start: {estimated_start}"
        )

        state["stall_time"] = 0.0
        state["last_mon_time"] = mon_time
        save_component_state(component, state)
        return

    if mon_time != last_mon_time:
        state["last_mon_time"] = mon_time
        save_component_state(component, state)


# -----------------------------------------------------------------------------
# Reboot
# -----------------------------------------------------------------------------

def reboot_system(reason: str) -> int:
    first_request = not REBOOT_REQUESTED_FLAG.exists()

    if first_request:
        log_info(f"REBOOT REQUIRED: {reason}")

        try:
            FLAGS_DIR.mkdir(parents=True, exist_ok=True)
            REBOOT_REQUESTED_FLAG.touch()
        except Exception as e:
            log_info(
                f"failed to create reboot-request flag "
                f"{REBOOT_REQUESTED_FLAG}: {e}"
            )
    else:
        log_debug("reboot already requested; retrying reboot command")

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

            if first_request:
                log_info(
                    f"reboot command failed rc={proc.returncode}: {detail}"
                )
            else:
                log_debug(
                    f"reboot retry failed rc={proc.returncode}: {detail}"
                )

        return proc.returncode

    except Exception as e:
        if first_request:
            log_info(f"exception while trying to reboot: {e}")
        else:
            log_debug(f"exception while retrying reboot: {e}")

        return 1


# -----------------------------------------------------------------------------
# Monitor processing
# -----------------------------------------------------------------------------

def process_monitor_file(mon_file: Path) -> int:
    contract = load_mon_contract(mon_file)

    if contract is None:
        return 0

    component = get_contract_name(contract, mon_file)
    state = load_component_state(component)
    launch_requested = bool(state.get("launch_requested", False))

    mon_time = file_mtime_seconds(mon_file)

    if mon_time <= 0.0:
        log_info(f"{component}: unable to read monitor file time: {mon_file}")
        return 0

    now = time.time()
    age = now - mon_time

    if launch_requested:
        mark_launch_completed(component, mon_time, now)
        return 0

    clear_restart_after_seconds = get_clear_restart_seconds(contract)

    update_stall_state(
        component=component,
        mon_file=mon_file,
        mon_time=mon_time,
        age=age,
        now=now,
        clear_restart_after_seconds=clear_restart_after_seconds,
    )

    if age <= HEALTHY_SECONDS:
        log_debug(f"{component}.mon healthy age={age:.1f}s")
        return 0

    if age < STALL_NOTICE_SECONDS:
        log_debug(
            f"{component}.mon slow-but-acceptable "
            f"age={age:.1f}s healthy_limit={HEALTHY_SECONDS}s"
        )
        return 0

    if age < STALE_SECONDS:
        log_debug(
            f"{component}.mon stale-but-within-limit "
            f"age={age:.1f}s restart_limit={STALE_SECONDS}s"
        )
        return 0

    state = load_component_state(component)
    restart_done = bool(state.get("restart_done", False))
    stale_again_action = get_stale_again_action(contract)

    log_info(
        f"{component}.mon timed out age={age:.1f}s "
        f"restart_done={restart_done} stale_again={stale_again_action}"
    )

    if restart_done:
        if stale_again_action == "launch":
            return request_launch(
                component,
                mon_file,
                contract,
                f"{component}.mon stale again age={age:.1f}s",
            )

        return reboot_system(
            f"{component}.mon stale again before restart flag expired "
            f"age={age:.1f}s"
        )

    return request_launch(
        component,
        mon_file,
        contract,
        f"{component}.mon stale age={age:.1f}s",
    )


def process_pending_launches() -> None:
    state = load_state()

    for component, component_state in state.items():
        if not isinstance(component_state, dict):
            continue

        normalized = _normalize_component_state(component_state)
        launch_requested = bool(normalized.get("launch_requested", False))

        if not launch_requested:
            continue

        mon_file = monitor_file_for_component(component)

        if mon_file.exists():
            continue

        log_debug(
            f"{component}: monitor file missing and launch_requested=True; "
            f"waiting for AdLauncher/heartbeat"
        )


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    log_debug(
        f"start home_dir={HOME_DIR} runtime_dir={RUNTIME_DIR} "
        f"flags_dir={FLAGS_DIR} pflags_dir={PFLAGS_DIR} "
        f"state_file={STATE_FILE}"
    )

    try:
        FLAGS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log_info(f"failed to create flags dir {FLAGS_DIR}: {e}")
        return 1

    process_pending_launches()

    try:
        mon_files = sorted(FLAGS_DIR.glob("*.mon"))
    except Exception as e:
        log_info(f"failed to list monitor files in {FLAGS_DIR}: {e}")
        return 1

    if not mon_files:
        log_debug(f"no monitor files found in {FLAGS_DIR}")
        return 0

    result = 0

    for mon_file in mon_files:
        rc = process_monitor_file(mon_file)

        if rc != 0:
            result = rc

    return result


if __name__ == "__main__":
    raise SystemExit(main())