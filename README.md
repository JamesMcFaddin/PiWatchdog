# 🧩 Process Watchdog Setup

This guide sets up a very small watchdog for `AdProcess`. The watchdog checks one heartbeat file, and if that file gets too old, it reboots the Pi.

---

## Contract

### 1. HOME_DIR
Each project derives `HOME_DIR` like this:

```python
SCRIPT_DIR = Path(__file__).resolve().parent
HOME_DIR = SCRIPT_DIR.parent
```

For the watchdog project installed in:

```text
/home/astepup/PiWatchdog
```

this resolves to:

```text
/home/astepup
```

So the flags directory is:

```text
/home/astepup/flags
```

### 2. Monitor file
For now, this watchdog is hardcoded to watch:

```text
/home/astepup/flags/AdProcess.mon
```

### 3. If there is no `.mon` file
The watchdog does nothing.

This lets the monitored process decide whether it is under watchdog care.

### 4. Orderly shutdown
A monitored process should delete its `.mon` file when it shuts down cleanly.

### 5. Debug logging
If this file exists:

```text
/home/astepup/flags/debug
```

the watchdog writes debug chatter to the system journal.

If it does not exist, the watchdog only logs important messages.

### 6. Timing
Current settings in this version:

- `AdProcess` should touch `AdProcess.mon` every 30 seconds.
- The watchdog runs every 30 seconds.
- If `AdProcess.mon` gets older than 1 hour, the watchdog reboots the Pi.

> Note: Earlier discussion used a 30-minute watchdog interval. This file set uses **30 seconds**, matching the latest request.

---

## Files

Put these files in place:

### Watchdog script
```text
/home/astepup/PiWatchdog/PiWatchdog.py
```

### systemd service
```text
/etc/systemd/system/pi-watchdog.service
```

### systemd timer
```text
/etc/systemd/system/pi-watchdog.timer
```

---

## 1) Create the watchdog folder and flags folder

```bash
mkdir -p /home/astepup/PiWatchdog
mkdir -p /home/astepup/flags
```

---

## 2) Copy in the watchdog script

Copy `PiWatchdog.py` to:

```text
/home/astepup/PiWatchdog/PiWatchdog.py
```

Make it executable:

```bash
chmod +x /home/astepup/PiWatchdog/PiWatchdog.py
```

---

## 3) Install the systemd service

Copy `pi-watchdog.service` to:

```text
/etc/systemd/system/pi-watchdog.service
```

---

## 4) Install the systemd timer

Copy `pi-watchdog.timer` to:

```text
/etc/systemd/system/pi-watchdog.timer
```

---

## 5) Reload systemd and enable the timer

```bash
sudo systemctl daemon-reload
sudo systemctl enable pi-watchdog.timer
sudo systemctl start pi-watchdog.timer
```

---

## 6) Check status

Check the timer:

```bash
sudo systemctl status pi-watchdog.timer
sudo systemctl list-timers --all | grep pi-watchdog
```

Run the service manually once:

```bash
sudo systemctl start pi-watchdog.service
sudo systemctl status pi-watchdog.service
```

---

## 7) View watchdog logs

```bash
journalctl -u pi-watchdog.service -n 50 --no-pager
```

Follow live:

```bash
journalctl -u pi-watchdog.service -f
```

---

## 8) Test behavior

### Fresh file test

```bash
touch /home/astepup/flags/AdProcess.mon
sudo systemctl start pi-watchdog.service
```

Expected result: no reboot.

### Stale file test

```bash
touch /home/astepup/flags/AdProcess.mon
touch -d "2 hours ago" /home/astepup/flags/AdProcess.mon
sudo systemctl start pi-watchdog.service
```

Expected result: watchdog attempts to reboot.

### Debug mode

```bash
touch /home/astepup/flags/debug
sudo systemctl start pi-watchdog.service
journalctl -u pi-watchdog.service -n 50 --no-pager
rm -f /home/astepup/flags/debug
```

---

## 9) Process-side responsibility

`AdProcess` should:

- create `/home/astepup/flags/AdProcess.mon`
- touch it every 30 seconds while healthy
- delete it on orderly shutdown

That means the watchdog only acts when:

- the process created the `.mon` file, and
- then stopped updating it long enough to go stale

---

## Summary

This version is intentionally narrow:

- hardcoded for `AdProcess`
- one `.mon` file
- one watchdog script
- one timer
- reboot on stale heartbeat

That keeps it simple and gets the job done.
