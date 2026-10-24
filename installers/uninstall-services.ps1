# Local AI Manager v0.1.0: remove scheduled tasks. Leaves %USERPROFILE%\LocalAI in place.
foreach ($t in "LocalAI Ollama","LocalAI Worker","LocalAI Dashboard","LocalAI Watchdog") { schtasks /Delete /TN $t /F 2>$null }
Write-Output "Tasks removed. LocalAI folder left in place."
