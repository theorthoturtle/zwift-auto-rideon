# Auto Ride On for Zwift — macOS

<img src="icon.png" width="96" align="right" alt="">

Gives Ride Ons automatically while you ride on Zwift. It appears in Zwift as an extra
**KICKR BIKE PRO** controller over Wi-Fi and holds its Ride On (Z) button for 3 seconds
at a random moment every 8–10 seconds — the same "Ride On bomb" you get by holding the
button on a real controller.

By Michael B. (For Windows, see the `Windows` folder.)

## Features

- Small always-on-top window with an **ON / OFF** switch (the controller stays connected
  when off), a slim title bar, and a resize grip — the text scales with the window.
- Only presses while you're in a ride (moving or stopped), checked through
  [Sauce for Zwift](https://www.sauce.llc/) if it's running.
- Shows **riders reached**: an estimate from nearby riders' Ride On counts, at most 5 per
  press, each rider counted once per ride.
- Health check: if the window crashes or freezes it reopens within seconds; closing it
  with the × quits.
- Every install creates its own serial number, device ID and network address on first run,
  so each copy looks like a different bike to Zwift.

## Requirements

- macOS 10.15 or later
- Python 3 with Tkinter — easiest is the installer from
  [python.org](https://www.python.org/downloads/macos/) (Homebrew: `brew install python python-tk`)
- Zwift on the same Mac or network
- Optional: Sauce for Zwift, for in-ride detection and the riders-reached count

## Install

1. Download and unzip the release zip.
2. Double-click **Install.command**. (If macOS says it can't be opened, right-click it →
   **Open** → **Open**.) It sets up a private Python environment and builds
   **Auto Ride On.app** in the folder.
   - Cloned with git instead? Open Terminal in the folder and run `bash install.sh`.
3. Double-click **Auto Ride On** (drag it to the Dock for one-click starting).
4. When macOS asks, **allow** Python to accept incoming network connections and to find
   devices on your local network — Zwift can't see the controller otherwise.
   (System Settings → Privacy & Security → Local Network, if you missed the prompt.)
5. In Zwift: **Pair Devices → Controls** → pick **KICKR BIKE PRO xxxx** (the 4 characters are
   unique to your install).

If you move the folder, run **Install.command** again to rebuild the app.

## Files

| File | What it is |
|---|---|
| `auto_rideon.py` | The virtual controller and Ride On logic (same as the Windows version) |
| `auto_rideon_app.py` | Main app: runs the controller and keeps the window healthy |
| `auto_rideon_gui.py` | The window |
| `install.sh`, `Install.command` | One-time setup; builds `Auto Ride On.app` |
| `Start Auto Ride On.command` | Runs in a Terminal window, for troubleshooting |
| `AutoRideOn.icns`, `icon.png` | App icon |
| `sniff_kickr.py`, `Record KICKR Buttons.command` | Developer tool: records how a real Wi-Fi KICKR talks to Zwift |

Created on each Mac and not part of the repository: `.venv/`, `Auto Ride On.app`,
`identity.json`, `auto_rideon.log`, `gui_settings.txt`, `gui_position.txt`.

## Troubleshooting

- **Doesn't appear in Zwift's pairing list:** check the Local Network and firewall
  permissions above, and that Zwift and this Mac are on the same network.
- **Details:** `auto_rideon.log` in the folder records connections, presses and riders
  reached. Run `.venv/bin/python3 auto_rideon.py --verbose` in Terminal to log every
  message to and from Zwift.
