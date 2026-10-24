# Install (v0.1.0)

The Grok Bot does these steps for you, asking before each one. To do it by hand:

1. **Download and verify** the release assets into `~/LocalAI`:
   ```sh
   mkdir -p ~/LocalAI/dashboard && cd ~/LocalAI
   B=https://github.com/anselmcmakin/local-ai-manager/releases/download/v0.1.0
   for f in scan.py worker.py watchdog.py dashboard.py SHA256SUMS; do curl -fsSLO "$B/$f"; done
   sha256sum -c SHA256SUMS        # macOS: shasum -a 256 -c SHA256SUMS ; Windows: Get-FileHash -Algorithm SHA256
   mv dashboard.py dashboard/
   ```
   Stop if any checksum fails.
2. **Containment file** `~/LocalAI/containment.json` (the worker refuses input files without it):
   ```json
   {"version":1,"mode":"local-only","read_folders":["~/LocalAI"],"write_folders":["~/LocalAI"],"files_leave_machine":"never","network":"localhost"}
   ```
3. **Webhook (optional)**: paste the URL and key from your Grok Bot routine panel into `~/LocalAI/watchdog.env.json` as `{"url":"…","key":"…"}`, then `chmod 600` it.
4. **Test once**: `python3 ~/LocalAI/scan.py`, `python3 ~/LocalAI/watchdog.py`, `python3 ~/LocalAI/dashboard/dashboard.py` (open http://127.0.0.1:8765).
5. **Services**: Linux/macOS `sh install-services.sh [worker] [watchdog] [dashboard]`; Windows `powershell -ExecutionPolicy Bypass -File install-services.ps1`.
6. **Verify loopback only**: `ss -ltnp | grep 8765` (Linux), `lsof -iTCP:8765 -sTCP:LISTEN` (macOS), `netstat -an | findstr 8765` (Windows). You should see only `127.0.0.1`.

Phone access (optional): `tailscale serve --https 8443 --http 127.0.0.1:8765` and set `LOCALAI_TS_HOST=<machine>.<tailnet>.ts.net`. Never use `tailscale funnel`.
