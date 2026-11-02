# Auto Ride On for Zwift

<img src="icon.png" width="96" align="right" alt="">

Gives Ride Ons automatically while you ride on Zwift. It appears in Zwift as an extra
**KICKR BIKE PRO** controller over Wi-Fi and holds its Ride On (Z) button for 3 seconds
at a random moment every 8–10 seconds — the same "Ride On bomb" you get by holding the
button on a real controller.

By Michael B.

## Features

- Small always-on-top corner window with an **ON / OFF** switch (the controller stays
  connected when off), a slim title bar, and a resize grip — the text scales with the window.
- Only presses while you're in a ride (moving or stopped), checked through
  [Sauce for Zwift](https://www.sauce.llc/) if it's running.
- Shows **riders reached**: an estimate from nearby riders' Ride On counts, at most 5 per
  press, each rider counted once per ride.
- Health check: if the window crashes or freezes it reopens within seconds; closing it
  with the × quits.
- Every install creates its own serial number, device ID and network address on first run,
  so each copy looks like a different bike to Zwift.

## Requirements

- Windows 10/11
- [Python 3](https://www.python.org/downloads/windows/) (tick **Add python.exe to PATH** when installing)
- Zwift on the same computer or network
- Optional: Sauce for Zwift, for in-ride detection and the riders-reached count

## Install

1. Download and unzip the release (or clone this repository).
2. Double-click **Start Auto Ride On.bat** once. It sets up a private Python environment
   (`.venv`) and installs the one package it needs (`zeroconf`). Close it when it says it's
   advertising.
3. Double-click **Create Desktop Shortcut.vbs** for a desktop shortcut.
4. Start it from the shortcut (or **Auto Ride On.vbs**). Allow it through Windows Firewall
   on private networks when asked.
5. In Zwift: **Pair Devices → Controls** → pick **KICKR BIKE PRO xxxx** (the 4 characters are
   unique to your install).

## Files

| File | What it is |
|---|---|
| `auto_rideon.py` | The virtual controller and Ride On logic (can also run on its own in a console) |
| `auto_rideon_app.pyw` | Main app: runs the controller and keeps the window healthy |
| `auto_rideon_gui.pyw` | The corner window |
| `Auto Ride On.vbs` | Starts the app with no console window |
| `Start Auto Ride On.bat` | First-time setup, or run in a console for troubleshooting |
| `Create Desktop Shortcut.vbs` | Adds a desktop shortcut with the icon |
| `sniff_kickr.py`, `Record KICKR Buttons.bat` | Developer tool: records how a real Wi-Fi KICKR talks to Zwift |

Files created while running (`identity.json`, `auto_rideon.log`, `gui_settings.txt`,
`gui_position.txt`, `.venv/`) are personal to each computer and are not part of the repository.

## Troubleshooting

- **Doesn't appear in Zwift's pairing list:** check Windows Firewall allowed it on private
  networks, and that Zwift and this computer are on the same network.
- **Details:** `auto_rideon.log` in the app folder records connections, presses and riders
  reached. Run `.venv\Scripts\python auto_rideon.py --verbose` to log every message to and
  from Zwift.

Options for the console version: `--min 8 --max 10 --hold 3 --sauce http://127.0.0.1:1080 --no-sauce --verbose`
