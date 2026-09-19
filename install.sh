#!/bin/bash
# Installerer overvakingen som en launchd-jobb.
#
#   ./install.sh <ntfy-topic>              installer
#   ./install.sh <ntfy-topic> --always-on  installer + hindre at maskinen sovner
#   ./install.sh --uninstall               fjern jobben
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
if [ -z "$PYTHON" ]; then
  echo "Fant ingen python3. Kjor: xcode-select --install" >&2
  exit 1
fi
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
    <string>$DIR/check_stock.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>NTFY_TOPIC</key><string>$TOPIC</string></dict>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartInterval</key><integer>180</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG_DIR/out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/err.log</string>
</dict>
</plist>
PLISTEOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

if [ "${2:-}" = "--always-on" ]; then
  echo
  echo "Setter maskinen til a sta pa. Krever administratorpassord."
  # sleep 0        maskinen sovner aldri nar den star i strom
  # disablesleep 1 lar den sta vaken med lokket lukket, uten ekstern skjerm
  # autorestart 1  starter igjen av seg selv etter stromburdd
  sudo pmset -c sleep 0 disablesleep 1 autorestart 1
  sudo pmset -c displaysleep 5
  echo "Gjeldende innstillinger:"
  pmset -g custom | sed -n '/AC Power/,$p' | grep -E "sleep|autorestart|displaysleep" | sed 's/^/  /'
  echo
  echo "VIKTIG: sla pa automatisk innlogging i Systeminnstillinger ->"
  echo "Brukere og grupper, ellers starter ikke jobben etter en omstart."
fi

echo "Installert. Sjekker hvert 3. minutt."
echo "  Status:  launchctl list | grep norli"
echo "  Logg:    tail -f $LOG_DIR/out.log"
echo "  Stopp:   $DIR/install.sh --uninstall"
