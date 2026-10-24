#!/bin/sh
# Local AI Manager v0.1.0: remove the user services. Does not delete ~/LocalAI (jobs, logs, config).
set -u
case "$(uname)" in
Linux)
  for u in localai-worker localai-dashboard localai-watchdog.timer; do systemctl --user disable --now "$u" 2>/dev/null; done
  rm -f "$HOME/.config/systemd/user/localai-worker.service" "$HOME/.config/systemd/user/localai-dashboard.service" "$HOME/.config/systemd/user/localai-watchdog.service"
  systemctl --user daemon-reload ;;
Darwin)
  for s in worker dashboard watchdog; do P="$HOME/Library/LaunchAgents/com.localai.$s.plist"; [ -f "$P" ] && launchctl unload "$P" && rm -f "$P"; done ;;
esac
echo "Services removed. ~/LocalAI left in place."
