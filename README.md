# Task Manager for Linux

Version 0.1.1 — created October 4, 2026 for Zorin OS.

A dark desktop system monitor inspired by Windows Task Manager, built for Linux.

Features: live CPU, memory, disk and network graphs; a resource sidebar; searchable and sortable processes; graceful End task with confirmation; storage capacity; pause/resume updates; desktop and menu launchers.

## Requirements on Zorin / Ubuntu

```bash
sudo apt install python3-tk python3-psutil
```

## Run

```bash
python3 task_manager.py
```

## Install desktop icon

From this extracted folder:

```bash
python3 install.py
```

No sudo is needed for the installer. If necessary, right-click the desktop icon and choose Allow Launching. The installer copies the app to your user data folder and adds a menu entry. Run it again to update.

## Measurement notes

Data is sampled approximately once per second using psutil. CPU readings need a warm-up interval. Process CPU is normalized to total machine capacity. Memory in use is total minus available (matching the percentage). Disk throughput aggregates counters exposed by Linux and can include stacked-device accounting. Network excludes loopback. Disk and network graphs scale automatically. Graph history starts empty and fills over one minute. Pausing stops display updates, not background collection. GPU monitoring and per-core charts are not included in this first version.

End task sends SIGTERM to the selected process after checking its identity. It does not elevate privileges or force-kill tasks. PID 1 and this monitor are protected. Processes may ignore a graceful termination request.

## Update notifications

The app checks GitHub once when launched, in the background with a five-second timeout. If a newer version is available, a small link appears in the bottom-right corner. Click it to open the installation instructions. No popups, recurring checks, or automatic installations are used. Offline checks fail silently.

For maintainers: update `APP_VERSION` and the root `VERSION` file together when publishing an installable update. Versions use `major.minor.patch`.
