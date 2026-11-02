#!/bin/bash
# Auto Ride On - one-time setup for macOS.
#   * makes a private Python environment (.venv) with the one package it needs
#   * builds "Auto Ride On.app" in this folder (double-click it, or keep it in the Dock)
# Run again after moving this folder or updating Python.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
APP="$DIR/Auto Ride On.app"

echo "Auto Ride On setup"
echo "------------------"

# 1. Find a Python 3.8+ that has Tkinter (needed for the window)
PY=""
for cand in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
            /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$cand" >/dev/null 2>&1 && \
       "$cand" -c 'import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
        PY="$cand"; break
    fi
done
if [ -z "$PY" ]; then
    echo
    echo "Couldn't find Python 3 with Tkinter."
    echo "Install Python from https://www.python.org/downloads/macos/ (it includes Tkinter),"
    echo "or with Homebrew: brew install python python-tk"
    echo "Then run this setup again."
    exit 1
fi
echo "Using $("$PY" --version) at $(command -v "$PY")"

# 2. Private environment with zeroconf
if [ ! -x .venv/bin/python3 ]; then
    echo "Creating the Python environment (one time)..."
    "$PY" -m venv .venv
fi
.venv/bin/python3 -m pip install -q --upgrade pip >/dev/null 2>&1 || true
.venv/bin/python3 -m pip install -q -r requirements.txt
.venv/bin/python3 -c 'import tkinter, zeroconf' || { echo "Setup check failed."; exit 1; }

# 3. Make the scripts runnable and clear the "downloaded from the internet" flag
chmod +x ./*.command install.sh 2>/dev/null || true
xattr -dr com.apple.quarantine "$DIR" 2>/dev/null || true

# 4. Build the app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp AutoRideOn.icns "$APP/Contents/Resources/"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Auto Ride On</string>
    <key>CFBundleDisplayName</key><string>Auto Ride On</string>
    <key>CFBundleIdentifier</key><string>com.michaelb.autorideon</string>
    <key>CFBundleVersion</key><string>1.0.1</string>
    <key>CFBundleShortVersionString</key><string>1.0.1</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>AutoRideOn</string>
    <key>CFBundleIconFile</key><string>AutoRideOn</string>
    <key>LSUIElement</key><true/>
    <key>LSMinimumSystemVersion</key><string>10.15</string>
    <key>NSLocalNetworkUsageDescription</key>
    <string>Auto Ride On appears to Zwift as a Wi-Fi controller on your local network.</string>
    <key>NSBonjourServices</key>
    <array><string>_wahoo-fitness-tnp._tcp</string></array>
</dict>
</plist>
PLIST
cat > "$APP/Contents/MacOS/AutoRideOn" <<LAUNCH
#!/bin/bash
# Starts Auto Ride On from its folder (the folder this app was built in, or the one it sits in).
HERE="\$(cd "\$(dirname "\$0")/../../.." && pwd)"
DIR="$DIR"
[ -f "\$HERE/auto_rideon_app.py" ] && DIR="\$HERE"
cd "\$DIR" && exec "\$DIR/.venv/bin/python3" "\$DIR/auto_rideon_app.py"
LAUNCH
chmod +x "$APP/Contents/MacOS/AutoRideOn"
touch "$APP"

echo
echo "Done. Double-click \"Auto Ride On\" in this folder to start it."
echo "Tip: drag it to your Dock or Applications folder for one-click starting."
echo "The first time, allow Python to accept incoming connections and to find devices"
echo "on your local network if macOS asks - Zwift can't see the controller otherwise."
