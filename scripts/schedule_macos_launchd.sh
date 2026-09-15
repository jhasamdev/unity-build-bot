#!/usr/bin/env bash
# Installs a macOS launchd agent that polls every N seconds.
# Usage: ./schedule_macos_launchd.sh /path/to/unity-build-bot 300
set -euo pipefail

TOOL_PATH="${1:?Usage: $0 <tool_path> <interval_seconds>}"
INTERVAL="${2:-300}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="${PLIST_DIR}/com.unitybuildbot.run.plist"

mkdir -p "${PLIST_DIR}"
cat > "${PLIST_PATH}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.unitybuildbot.run</string>
    <key>ProgramArguments</key>
    <array>
        <string>python3</string>
        <string>-m</string>
        <string>unity_build_bot</string>
        <string>run</string>
        <string>--config</string>
        <string>${TOOL_PATH}/config/config.yaml</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${TOOL_PATH}</string>
    <key>StartInterval</key>
    <integer>${INTERVAL}</integer>
    <key>StandardOutPath</key>
    <string>${TOOL_PATH}/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>${TOOL_PATH}/logs/launchd.err.log</string>
</dict>
</plist>
EOF

launchctl unload "${PLIST_PATH}" 2>/dev/null || true
launchctl load "${PLIST_PATH}"

echo "Installed and loaded launchd agent at ${PLIST_PATH} (interval: ${INTERVAL}s)."
