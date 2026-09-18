@echo off
setlocal
echo Stopping Ledger on port 8765 ...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pids = @();" ^
  "Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { if ($_.OwningProcess -gt 0) { $pids += $_.OwningProcess } };" ^
  "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'journal\.server' } | ForEach-Object { $pids += $_.ProcessId };" ^
  "$pids = $pids | Select-Object -Unique;" ^
  "if (-not $pids) { Write-Host 'Ledger is not running.'; exit 0 };" ^
  "foreach ($procId in $pids) { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue; Write-Host \"Stopped PID $procId\" }"

echo Done.
timeout /t 2 >nul
endlocal
