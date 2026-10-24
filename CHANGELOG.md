# Changelog

## v0.1.0 (2026-10-23)
First release. Tested live on Windows 11 + NVIDIA RTX 3070 Laptop GPU + Ollama 0.40.10.
- `scan.py`: read-only hardware and installed-tools scan, JSON output (`CREATE_NO_WINDOW`, `-WindowStyle Hidden`, `ollama ps`, `py`/`python`/`python3`, WSL).
- `worker.py`: job-folder runner (inbox → running → done/failed) with containment allowlist, Game Mode snooze (`is_snoozed()`), `utf-8-sig` reads (Windows BOM safe), Ollama native `/api/chat` (`think:false` so thinking models return `content`), safe job ids, and `usage.jsonl` logging.
- `watchdog.py`: endpoint, GPU temperature, VRAM, disk, and stuck-job checks (`CREATE_NO_WINDOW`); Game Mode snooze (`snooze_until.txt` / `watchdog_state.json`); alerts after sustained failures; 15/30/60 min backoff; recovery ping; `alerts.log`.
- `dashboard.py`: single-file dark dashboard on 127.0.0.1:8765 with gauges, live charts, job and alert panels, Windows `GlobalMemoryStatusEx` RAM fallback, `CREATE_NO_WINDOW`, and confirmed Start/Stop/Restart/Unload + Pause 2h (Game Mode) / Resume from a fixed allowlist.
- Installers for systemd --user, launchd, and Windows Task Scheduler (`py -3` fallback for `pythonw.exe`, hidden `LocalAI Ollama` task), plus uninstallers.
- pytest suite (21 tests) for worker, watchdog, dashboard, scan.

Known limits: NVIDIA GPU telemetry only (AMD and Mac GPU temp show n/a; Windows CPU temp needs admin); macOS launchd and Linux systemd paths not yet run on live hardware; webhook auth header is a placeholder until confirmed.
