#!/bin/bash
# Build, install, and reload the Calibre plugin
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

# 2. Quit Calibre if running
if pgrep -x calibre > /dev/null 2>&1; then
    echo "Stopping Calibre..."
    osascript -e 'quit app "calibre"' 2>/dev/null || pkill -x calibre
    while pgrep -x calibre > /dev/null 2>&1; do
        sleep 0.5
    done
    echo "Calibre stopped."
fi

# 3. Install plugin
echo "Installing plugin..."
/Applications/calibre.app/Contents/MacOS/calibre-customize -a "$OUTPUT"

# 4. Relaunch Calibre
echo "Starting Calibre..."
open -a calibre
echo "Done."
