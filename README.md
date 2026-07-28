# 🧩 PiWatchdog -- AdProcess Watchdog

A lightweight watchdog for Raspberry Pi that monitors one or more
heartbeat monitor files. If a monitored component hangs, PiWatchdog
automatically attempts recovery and escalates to a reboot only when
recovery has already failed.

------------------------------------------------------------------------

## 🎯 Purpose

PiWatchdog is an autonomous recovery service. Its job is to keep
long-running components healthy without embedding watchdog logic inside
each application.

For each monitored component it can:

-   Monitor heartbeat (`*.mon`) files.
-   Detect stalled or hung processes.
-   Request a restart through AdLauncher.
-   Reboot the Pi if a restarted component fails again before proving it
    is healthy.

------------------------------------------------------------------------

## ⚙️ How It Works

1.  Components publish a monitor contract (`*.mon`).
2.  PiWatchdog scans all monitor files every 30 seconds.
3.  Healthy components are left alone.
4.  Stale components are stopped and a `.launch` request is written.
5.  AdLauncher restarts the component.
6.  If the component fails again during its probation period, PiWatchdog
    reboots the Pi.

------------------------------------------------------------------------

## 📁 Runtime Layout

``` text
/dev/shm/AdProcess/
└── Flags/
    ├── *.mon
    ├── *.launch
    ├── PiWatchdog.state
    └── PiWatchdog.reboot
```

The runtime directory resides in RAM to minimize SD card writes.

------------------------------------------------------------------------

## 🧠 Path Logic

All paths are derived relative to the script location. No usernames or
home directories are hard-coded.

------------------------------------------------------------------------

## 📌 Monitor Files

Each `.mon` file contains a monitor contract describing:

-   component name
-   stop procedure
-   launch command
-   recovery policy

If no `.mon` file exists, PiWatchdog takes no action.

------------------------------------------------------------------------

## 🧪 Timing Rules

-   Watchdog cycle: every 30 seconds
-   Healthy: ≤ 6 minutes
-   Stall notice: \> 8 minutes
-   Stale: \> 15 minutes

------------------------------------------------------------------------

## 🔄 Recovery

On the first stale timeout:

-   Stop the component.
-   Write a `.launch` request.
-   Delete the stale `.mon` file.
-   Wait for AdLauncher to restart it.

If the component later proves healthy, the restart history is cleared.

If it fails again before the probation period expires, PiWatchdog
reboots the Pi.

------------------------------------------------------------------------

## 🔁 Reboot Strategy

PiWatchdog first attempts an orderly reboot:

``` bash
sudo -n systemctl reboot
```

If still running about 15 seconds later:

``` bash
sudo -n sync
sudo -n reboot -f
```

This guarantees recovery even if systemd hangs.

------------------------------------------------------------------------

## 🐞 Debug Mode

Enable debug logging by creating either:

``` text
~/PFlags/debug-PiWatchdog
```

or

``` text
~/PFlags/debug-all
```

Remove the file to return to normal logging.

------------------------------------------------------------------------

## 🚀 Startup

PiWatchdog is started automatically during login/startup alongside
AdProcess.

It runs continuously; no systemd timer is required.

------------------------------------------------------------------------

## 📊 Logging

Normal logging records:

-   restart requests
-   successful recoveries
-   reboot requests
-   errors

Debug logging additionally records heartbeat timing and state
transitions.

------------------------------------------------------------------------

## 🔄 Component Responsibilities

Each monitored component is responsible for:

-   creating its `.mon` file
-   updating its heartbeat
-   deleting the `.mon` file during an orderly shutdown

------------------------------------------------------------------------

## ⚠️ Important Notes

-   PiWatchdog only acts on components that publish monitor contracts.
-   Recovery is attempted before rebooting.
-   Runtime state is stored in `PiWatchdog.state` so recovery history
    survives watchdog restarts.

------------------------------------------------------------------------

## 🧠 Control Model

-   Components publish monitor contracts.
-   PiWatchdog monitors health.
-   AdLauncher performs launches.
-   PiWatchdog escalates to reboot only after software recovery fails.

------------------------------------------------------------------------

## ✅ Summary

-   Continuous watchdog
-   Multiple monitored components
-   JSON monitor contracts
-   Automatic restart through AdLauncher
-   Probation-based recovery
-   Graceful reboot with forced fallback
-   RAM-based runtime files
