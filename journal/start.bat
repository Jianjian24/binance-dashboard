@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."

if exist ".env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if not defined %%A (
      set "_v=%%B"
      set "_v=!_v:"=!"
      set "%%A=!_v!"
    )
  )
)

if not defined BINANCE_API_KEY (
  for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('BINANCE_API_KEY','Machine')"`) do set "BINANCE_API_KEY=%%i"
)
if not defined BINANCE_API_SECRET (
  for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('BINANCE_API_SECRET','Machine')"`) do set "BINANCE_API_SECRET=%%i"
)
if not defined BINANCE_API_KEY (
  for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('BINANCE_API_KEY_TRADE','Machine')"`) do set "BINANCE_API_KEY=%%i"
)
if not defined BINANCE_API_SECRET (
  for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('BINANCE_API_SECRET_TRADE','Machine')"`) do set "BINANCE_API_SECRET=%%i"
)

if not defined BINANCE_API_KEY (
  echo [ERROR] Set BINANCE_API_KEY and BINANCE_API_SECRET.
  pause
  exit /b 1
)

if /I "%PROXY_TYPE%"=="CLASH" (
  if not defined CLASH_HTTP_PROXY set "CLASH_HTTP_PROXY=http://127.0.0.1:7890"
)

powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/api/health -TimeoutSec 2).StatusCode } catch { 0 }" | findstr /r "200" >nul
if %ERRORLEVEL%==0 (
  echo Ledger already running — opening browser.
  start "" "http://127.0.0.1:8765/"
  exit /b 0
)

echo Starting Ledger ...
echo   URL:   http://127.0.0.1:8765/
echo   Key:   %BINANCE_API_KEY:~0,8%...
echo   Proxy: %PROXY_TYPE%
echo   Stop:  double-click stop.bat

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$env:BINANCE_API_KEY = $env:BINANCE_API_KEY;" ^
  "$env:BINANCE_API_SECRET = $env:BINANCE_API_SECRET;" ^
  "if ($env:PROXY_TYPE) { } else { $env:PROXY_TYPE = 'NONE' };" ^
  "if ($env:PROXY_TYPE -eq 'CLASH' -and -not $env:CLASH_HTTP_PROXY) { $env:CLASH_HTTP_PROXY = 'http://127.0.0.1:7890' };" ^
  "Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k','title Ledger Journal && python -m journal.server --port 8765') -WorkingDirectory '%CD%' -WindowStyle Normal;" ^
  "for ($i=0; $i -lt 40; $i++) { try { $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/api/health -TimeoutSec 1; if ($r.StatusCode -eq 200) { Start-Process 'http://127.0.0.1:8765/'; Write-Host 'Ready.'; exit 0 } } catch {} ; Start-Sleep -Milliseconds 400 };" ^
  "Write-Host 'Server did not become ready. Check the Ledger Journal window.'; exit 1"

if errorlevel 1 pause
endlocal
