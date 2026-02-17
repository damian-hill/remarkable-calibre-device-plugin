#!/bin/bash
# Build, install, and reload the Calibre plugin
# Works on macOS, Linux, and Windows (Git Bash / MSYS2)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$SCRIPT_DIR/plugin"
OUTPUT="$SCRIPT_DIR/remarkable-calibre-device-plugin.zip"

# 1. Build ZIP (flat — all plugin files at the root of the archive)
rm -f "$OUTPUT"
zip -j "$OUTPUT" \
    "$PLUGIN_DIR/__init__.py" \
    "$PLUGIN_DIR/rm_web_interface.py" \
    "$PLUGIN_DIR/rm_data.py" \
    "$PLUGIN_DIR/log_helper.py" \
    "$PLUGIN_DIR/config_widget.py" \
    "$PLUGIN_DIR/plugin-import-name-remarkable_calibre_device_plugin.txt"
echo "Built: $OUTPUT"

# 2. Find calibre-customize
if [ -n "$CALIBRE_CUSTOMIZE" ]; then
    CUSTOMIZE="$CALIBRE_CUSTOMIZE"
elif [ -x "/Applications/calibre.app/Contents/MacOS/calibre-customize" ]; then
    CUSTOMIZE="/Applications/calibre.app/Contents/MacOS/calibre-customize"
elif command -v calibre-customize > /dev/null 2>&1; then
    CUSTOMIZE="calibre-customize"
else
    echo "Built ZIP only — calibre-customize not found."
    echo "Install manually: Preferences > Plugins > Load plugin from file"
    exit 0
fi

# 3. Quit Calibre if running
case "$(uname -s)" in
    Darwin)
        if pgrep -x calibre > /dev/null 2>&1; then
            echo "Stopping Calibre..."
            osascript -e 'quit app "calibre"' 2>/dev/null || pkill -x calibre
            while pgrep -x calibre > /dev/null 2>&1; do sleep 0.5; done
            echo "Calibre stopped."
        fi
        ;;
    Linux)
        if pgrep -x calibre > /dev/null 2>&1; then
            echo "Stopping Calibre..."
            pkill -x calibre || true
            while pgrep -x calibre > /dev/null 2>&1; do sleep 0.5; done
            echo "Calibre stopped."
        fi
        ;;
    MINGW*|MSYS*|CYGWIN*)
        if tasklist 2>/dev/null | grep -qi "calibre.exe"; then
            echo "Stopping Calibre..."
            taskkill //IM calibre.exe //F > /dev/null 2>&1 || true
            sleep 2
            echo "Calibre stopped."
        fi
        ;;
esac

# 4. Install plugin
echo "Installing plugin..."
"$CUSTOMIZE" -a "$OUTPUT"

# 5. Relaunch Calibre
echo "Starting Calibre..."
case "$(uname -s)" in
    Darwin)       open -a calibre ;;
    Linux)        nohup calibre > /dev/null 2>&1 & ;;
    MINGW*|MSYS*|CYGWIN*) start calibre 2>/dev/null || calibre & ;;
esac
echo "Done."
