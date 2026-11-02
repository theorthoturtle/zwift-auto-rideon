#!/bin/bash
# Double-click to run Auto Ride On in a Terminal window (shows its log as it runs).
cd "$(dirname "$0")"
[ -x .venv/bin/python3 ] || bash ./install.sh || exit 1
.venv/bin/python3 auto_rideon.py "$@"
read -n 1 -s -r -p "Press any key to close..."
