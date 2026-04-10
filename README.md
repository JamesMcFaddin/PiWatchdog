# 🧩 PiWatchdog – AdProcess Watchdog

A lightweight watchdog for Raspberry Pi that monitors a heartbeat file created by AdProcess. If the heartbeat stops updating, the system automatically reboots.

---

## 🎯 Purpose

PiWatchdog exists to solve one problem:

If AdProcess hangs, crashes, or silently dies, reboot the Pi.

It does this by watching a single file:

/home/astepup/flags/AdProcess.mon

If that file stops being updated, the watchdog assumes the system is unhealthy.

---

## ⚙️ How It Works

1. AdProcess creates and updates a heartbeat file
2. PiWatchdog checks that file every 30 seconds
3. If the file is older than 1 hour → reboot

No file = no monitoring = no action

---

## 📁 Directory Layout

PiWatchdog/
├── README.md
├── PiWatchdog.py
├── install_pi-watchdog.sh
└── systemd/
    ├── pi-watchdog.service
    └── pi-watchdog.timer

---

## 🧠 Path Logic

- Script location: /home/astepup/PiWatchdog/PiWatchdog.py
- Home directory: /home/astepup
- Flags directory: /home/astepup/flags

---

## 📌 Heartbeat File

Watched file:

/home/astepup/flags/AdProcess.mon

Behavior:

- Exists and updating → healthy
- Exists but stale → reboot
- Does not exist → do nothing

---

## 🧪 Timing Rules

- AdProcess updates every ~30 seconds
- Watchdog runs every 30 seconds
- Reboot threshold = 1 hour

---

## 🛑 Shutdown Behavior

AdProcess should delete:

/home/astepup/flags/AdProcess.mon

on clean shutdown.

---

## 🐞 Debug Mode

Enable debug logging:

/home/astepup/flags/debug

Delete it to disable.

---

## 🚀 Installation

chmod +x install_pi-watchdog.sh
sudo ./install_pi-watchdog.sh

---

## 🔧 What the Installer Does

- Copies PiWatchdog.py to /home/astepup/PiWatchdog
- Creates /home/astepup/flags
- Installs systemd service and timer
- Enables and starts the timer

---

## ⏱️ systemd Timer

Runs every 30 seconds.

---

## 🧩 systemd Service

Runs watchdog once per trigger.

---

## 📊 Status Commands

systemctl status pi-watchdog.timer
systemctl list-timers | grep watchdog

sudo systemctl start pi-watchdog.service

---

## 📜 Logs

journalctl -u pi-watchdog.service -n 50
journalctl -u pi-watchdog.service -f

---

## 🧪 Testing

Fresh test:

touch /home/astepup/flags/AdProcess.mon
sudo systemctl start pi-watchdog.service

Stale test:

touch /home/astepup/flags/AdProcess.mon
touch -d "2 hours ago" /home/astepup/flags/AdProcess.mon
sudo systemctl start pi-watchdog.service

Debug test:

touch /home/astepup/flags/debug
sudo systemctl start pi-watchdog.service
journalctl -u pi-watchdog.service -n 50
rm -f /home/astepup/flags/debug

---

## 🔄 AdProcess Responsibilities

- Create the heartbeat file
- Update it every 30 seconds
- Delete it on shutdown

---

## ⚠️ Important Notes

- Watchdog always runs once installed
- Only acts if heartbeat file exists
- Only reboots if file becomes stale

---

## ✅ Summary

- One process: AdProcess
- One heartbeat file
- One watchdog
- Reboot on failure

Simple. Reliable.