# Uninstall

1. Remove services: `sh installers/uninstall-services.sh` (Linux/macOS) or `powershell -File installers\uninstall-services.ps1` (Windows).
2. If you set up phone access: `tailscale serve reset` (this clears **all** Serve configs on that machine).
3. Delete the scripts: `rm ~/LocalAI/{scan,worker,watchdog}.py && rm -r ~/LocalAI/dashboard`.
4. Optional, removes your history: `rm -r ~/LocalAI` (jobs, conversations, logs, usage, containment and webhook config).
5. Confirm port 8765 is closed with the listener check from INSTALL.md.

This does not remove your AI runtime or models. For Ollama, LM Studio, ComfyUI and others, see the bot's install skill or each vendor's uninstall docs.
