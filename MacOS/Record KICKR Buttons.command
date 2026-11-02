#!/bin/bash
# Double-click to record how your real Wi-Fi KICKR talks to Zwift (developer tool).
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python3 ]; then echo "Run Install.command first."; read -n 1 -s -r; exit 1; fi
.venv/bin/python3 sniff_kickr.py
