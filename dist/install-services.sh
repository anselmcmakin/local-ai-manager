#!/bin/sh
# Local AI Manager v0.1.0: register worker, watchdog, dashboard as user services (Linux systemd --user / macOS launchd).
# Usage: sh install-services.sh [worker] [watchdog] [dashboard]   (no args = all). Nothing runs as root.
set -eu
D="$HOME/LocalAI"; PY="$(command -v python3)"
[ $# -eq 0 ] && set -- worker watchdog dashboard
case "$(uname)" in
Linux)
  U="$HOME/.config/systemd/user"; mkdir -p "$U"
  for s in "$@"; do case $s in
    worker)    printf '[Service]\nExecStart=%s %s/worker.py\nRestart=on-failure\n[Install]\nWantedBy=default.target\n' "$PY" "$D" > "$U/localai-worker.service"; systemctl --user enable --now localai-worker ;;
    dashboard) printf '[Service]\nExecStart=%s %s/dashboard/dashboard.py\nRestart=on-failure\n[Install]\nWantedBy=default.target\n' "$PY" "$D" > "$U/localai-dashboard.service"; systemctl --user enable --now localai-dashboard ;;
    watchdog)  printf '[Service]\nType=oneshot\nExecStart=%s %s/watchdog.py\n' "$PY" "$D" > "$U/localai-watchdog.service"
               printf '[Timer]\nOnBootSec=60\nOnUnitActiveSec=60\n[Install]\nWantedBy=timers.target\n' > "$U/localai-watchdog.timer"
               systemctl --user daemon-reload; systemctl --user enable --now localai-watchdog.timer ;;
  esac; done ;;
Darwin)
  L="$HOME/Library/LaunchAgents"; mkdir -p "$L"
  for s in "$@"; do
    case $s in worker) F="$D/worker.py";; dashboard) F="$D/dashboard/dashboard.py";; watchdog) F="$D/watchdog.py";; *) continue;; esac
    if [ "$s" = watchdog ]; then EXTRA='<key>StartInterval</key><integer>60</integer>'; else EXTRA='<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>'; fi
    P="$L/com.localai.$s.plist"
    cat > "$P" <<PL
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>Label</key><string>com.localai.$s</string>
<key>ProgramArguments</key><array><string>$PY</string><string>$F</string></array>$EXTRA</dict></plist>
PL
    launchctl load "$P"
  done ;;
*) echo "Unsupported OS; use install-services.ps1 on Windows"; exit 1 ;;
esac
echo "Installed: $*"
