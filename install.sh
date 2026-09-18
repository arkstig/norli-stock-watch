#!/bin/bash
# Installerer overvakingen som en launchd-jobb som kjorer hvert 5. minutt.
# Bruk: ./install.sh <ntfy-topic>      Avinstaller: ./install.sh --uninstall
set -euo pipefail

LABEL="no.stigark.norli-stock-watch"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HOME/Library/Logs/norli-stock-watch"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Avinstallert. Loggene ligger fortsatt i $LOG_DIR"
  exit 0
fi

TOPIC="${1:-}"
if [ -z "$TOPIC" ]; then
  echo "Bruk: ./install.sh <ntfy-topic>" >&2
  exit 1
fi

PYTHON="$(command -v python3)"
mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$DIR/check_norli.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>NTFY_TOPIC</key><string>$TOPIC</string></dict>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG_DIR/out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/err.log</string>
</dict>
</plist>
PLISTEOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installert. Sjekker hvert 5. minutt."
echo "  Status:  launchctl list | grep norli"
echo "  Logg:    tail -f $LOG_DIR/out.log"
echo "  Stopp:   $DIR/install.sh --uninstall"
