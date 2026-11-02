#!/bin/bash
# Double-click to set up Auto Ride On (one time).
cd "$(dirname "$0")"
bash ./install.sh
echo
read -n 1 -s -r -p "Press any key to close..."
