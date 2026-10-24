# Local AI Manager v0.1.0: register ollama, worker, watchdog, dashboard as per-user scheduled tasks (no admin, no console windows).
param([string[]]$Only = @("worker","watchdog","dashboard"))
$D = Join-Path $env:USERPROFILE "LocalAI"
$PyW = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $PyW) { $Py = (& py -3 -c "import sys;print(sys.executable)" 2>$null).Trim(); if ($Py) { $PyW = Join-Path (Split-Path $Py) "pythonw.exe" } }
if (-not $PyW -or -not (Test-Path $PyW)) { throw "pythonw.exe not found; install Python 3 from python.org" }
foreach ($s in $Only) {
  switch ($s) {
    "ollama"    { schtasks /Create /TN "LocalAI Ollama"    /SC ONLOGON /TR "`"$PyW`" `"$D\ollama_serve.py`"" /F }
    "worker"    { schtasks /Create /TN "LocalAI Worker"    /SC ONLOGON /TR "`"$PyW`" `"$D\worker.py`"" /F }
    "dashboard" { schtasks /Create /TN "LocalAI Dashboard" /SC ONLOGON /TR "`"$PyW`" `"$D\dashboard\dashboard.py`"" /F }
    "watchdog"  { schtasks /Create /TN "LocalAI Watchdog"  /SC MINUTE /MO 1 /TR "`"$PyW`" `"$D\watchdog.py`"" /F }
  }
}
Write-Output "Installed: $($Only -join ', ')"
