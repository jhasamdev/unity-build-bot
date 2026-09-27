#!/usr/bin/env bash
# Installs a macOS launchd agent that polls every N seconds.
# Usage: ./schedule_macos_launchd.sh /path/to/unity-build-bot 300 [config_path]
# Remove: ./schedule_macos_launchd.sh --uninstall [tool_path] [config_path]
set -euo pipefail

PLIST_DIR="$HOME/Library/LaunchAgents"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
UNINSTALL=false
if [[ "${1:-}" == "--uninstall" ]]; then
    UNINSTALL=true
    shift
fi

TOOL_PATH="${1:-$(cd "${SCRIPT_DIR}/.." && pwd -P)}"
TOOL_PATH="$(cd "${TOOL_PATH}" && pwd -P)"
if [[ "${UNINSTALL}" == "true" ]]; then
    CONFIG_PATH="${2:-config/config.yaml}"
else
    INTERVAL="${2:-300}"
    CONFIG_PATH="${3:-config/config.yaml}"
fi
if [[ "${CONFIG_PATH}" != /* ]]; then
    CONFIG_PATH="${TOOL_PATH}/${CONFIG_PATH}"
fi
CONFIG_PATH="$(cd "$(dirname "${CONFIG_PATH}")" && pwd -P)/$(basename "${CONFIG_PATH}")"

LABEL="com.unitybuildbot.run"
if [[ "${CONFIG_PATH}" != "${TOOL_PATH}/config/config.yaml" ]]; then
    CONFIG_NAME="$(basename "${CONFIG_PATH}" .yaml | LC_ALL=C tr -c 'A-Za-z0-9' '-')"
    CONFIG_HASH="$(printf '%s' "${CONFIG_PATH}" | shasum -a 256 | cut -c 1-8)"
    LABEL="${LABEL}.${CONFIG_NAME}-${CONFIG_HASH}"
fi
PLIST_PATH="${PLIST_DIR}/${LABEL}.plist"

if [[ "${UNINSTALL}" == "true" ]]; then
    if [[ -f "${PLIST_PATH}" ]]; then
        launchctl unload "${PLIST_PATH}" 2>/dev/null || true
        rm "${PLIST_PATH}"
        echo "Removed launchd agent ${LABEL}."
    else
        echo "launchd agent ${LABEL} is not installed."
    fi
    exit 0
fi

PYTHON_PATH="${TOOL_PATH}/.venv/bin/python"

if [[ ! -x "${PYTHON_PATH}" ]]; then
    echo "Python virtual environment not found at ${PYTHON_PATH}. Run the Python setup first." >&2
    exit 1
fi
if [[ ! -f "${CONFIG_PATH}" ]]; then
    echo "Config file not found at ${CONFIG_PATH}." >&2
    exit 1
fi

OUT_LOG="${TOOL_PATH}/logs/launchd.out.log"
ERR_LOG="${TOOL_PATH}/logs/launchd.err.log"
if [[ "${LABEL}" != "com.unitybuildbot.run" ]]; then
    OUT_LOG="${TOOL_PATH}/logs/${LABEL}.out.log"
    ERR_LOG="${TOOL_PATH}/logs/${LABEL}.err.log"
fi

xml_escape() {
    printf '%s' "$1" | sed -e 's/\&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}
XML_PYTHON_PATH="$(xml_escape "${PYTHON_PATH}")"
XML_CONFIG_PATH="$(xml_escape "${CONFIG_PATH}")"
XML_TOOL_PATH="$(xml_escape "${TOOL_PATH}")"
XML_OUT_LOG="$(xml_escape "${OUT_LOG}")"
XML_ERR_LOG="$(xml_escape "${ERR_LOG}")"

mkdir -p "${PLIST_DIR}" "${TOOL_PATH}/logs"
cat > "${PLIST_PATH}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${XML_PYTHON_PATH}</string>
        <string>-m</string>
        <string>unity_build_bot</string>
        <string>run</string>
        <string>--config</string>
        <string>${XML_CONFIG_PATH}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${XML_TOOL_PATH}</string>
    <key>StartInterval</key>
    <integer>${INTERVAL}</integer>
    <key>StandardOutPath</key>
    <string>${XML_OUT_LOG}</string>
    <key>StandardErrorPath</key>
    <string>${XML_ERR_LOG}</string>
</dict>
</plist>
EOF

launchctl unload "${PLIST_PATH}" 2>/dev/null || true
launchctl load "${PLIST_PATH}"

echo "Installed and loaded launchd agent at ${PLIST_PATH} (config: ${CONFIG_PATH}, interval: ${INTERVAL}s)."
