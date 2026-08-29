@echo off
REM start.bat — start the QoderRoute server (prod). Does nothing if already running.
REM Usage: start.bat
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PORT=8010"
set "DATA=%CD%\data"
set "LOG=%DATA%\server.log"
set "PIDFILE=%DATA%\server.pid"
set "LOCKDIR=%DATA%\server.lock.dir"

if not exist "%DATA%" mkdir "%DATA%"

mkdir "%LOCKDIR%" 2>nul
if errorlevel 1 (
    echo [!] another QoderRoute start/restart is already running
    exit /b 1
)

call :resolve_python
if errorlevel 1 goto :fail

REM already running?
if exist "%PIDFILE%" (
    set /p EXISTING_PID=<"%PIDFILE%"
    set "EXISTING_PID=!EXISTING_PID: =!"
    call :is_qoderroute "!EXISTING_PID!"
    if not errorlevel 1 (
        call :health_ok
        if not errorlevel 1 (
            echo [OK] server already running ^(pid !EXISTING_PID!^) - http://0.0.0.0:%PORT%
            goto :ok
        )
        echo [!] QoderRoute pid !EXISTING_PID! is running but not ready
        goto :fail
    )
)

call :port_in_use
if not errorlevel 1 (
    echo [!] port %PORT% is already in use by another process, not starting
    goto :fail
)

echo [*] starting server ^(prod, no reload^)...
call :start_server
if errorlevel 1 goto :fail

call :wait_ready
if errorlevel 1 goto :fail
goto :ok

:ok
rmdir "%LOCKDIR%" 2>nul
exit /b 0

:fail
rmdir "%LOCKDIR%" 2>nul
exit /b 1

REM ── helpers ──────────────────────────────────────────────

:resolve_python
set "PYEXE="
where py >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%I"
)
if not defined PYEXE (
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%I"
    )
)
if not defined PYEXE (
    echo [!] neither py nor python found in PATH
    exit /b 1
)
exit /b 0

:is_qoderroute
set "_PID=%~1"
echo %_PID%| findstr /r "^[0-9][0-9]*$" >nul || exit /b 1
powershell -NoProfile -Command ^
  "$p = Get-CimInstance Win32_Process -Filter ('ProcessId=%_PID%') -ErrorAction SilentlyContinue;" ^
  "if (-not $p) { exit 1 };" ^
  "if ($p.CommandLine -match 'uvicorn\s+app\.main:app') { exit 0 } else { exit 1 }"
exit /b %ERRORLEVEL%

:health_ok
curl.exe -sf "http://127.0.0.1:%PORT%/api/health" >nul 2>&1
if not errorlevel 1 exit /b 0
powershell -NoProfile -Command ^
  "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri 'http://127.0.0.1:%PORT%/api/health'; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) { exit 0 } else { exit 1 } } catch { exit 1 }"
exit /b %ERRORLEVEL%

:port_in_use
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 exit /b 0
exit /b 1

:start_server
powershell -NoProfile -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$py = '%PYEXE%';" ^
  "$log = '%LOG%'; $wd = '%CD%'; $pidfile = '%PIDFILE%'; $port = '%PORT%';" ^
  "$arg = '/c \"\"' + $py + '\" -m uvicorn app.main:app --host 0.0.0.0 --port ' + $port + ' >> \"' + $log + '\" 2>&1\"';" ^
  "$wrapper = Start-Process -FilePath $env:ComSpec -ArgumentList $arg -WorkingDirectory $wd -WindowStyle Hidden -PassThru;" ^
  "$deadline = (Get-Date).AddSeconds(8); $child = $null;" ^
  "while ((Get-Date) -lt $deadline) {" ^
  "  $child = Get-CimInstance Win32_Process -Filter ('ParentProcessId=' + $wrapper.Id) -ErrorAction SilentlyContinue |" ^
  "    Where-Object { $_.CommandLine -match 'uvicorn\s+app\.main:app' } |" ^
  "    Select-Object -First 1;" ^
  "  if ($child) { break }; Start-Sleep -Milliseconds 100" ^
  "};" ^
  "if (-not $child) {" ^
  "  $child = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |" ^
  "    Where-Object { $_.CommandLine -match 'uvicorn\s+app\.main:app' -and $_.CommandLine -match ('--port\s+' + $port) } |" ^
  "    Sort-Object CreationDate -Descending | Select-Object -First 1" ^
  "};" ^
  "if (-not $child) { Write-Host '[!] failed to start uvicorn process'; exit 1 };" ^
  "Set-Content -LiteralPath $pidfile -Value $child.ProcessId -Encoding ascii;" ^
  "exit 0"
if errorlevel 1 (
    echo [!] failed to launch server
    exit /b 1
)
exit /b 0

:wait_ready
set /a _i=0
:wait_loop
call :health_ok
if not errorlevel 1 goto :wait_ok
if not exist "%PIDFILE%" goto :wait_dead
set /p _PID=<"%PIDFILE%"
call :is_qoderroute "!_PID!"
if errorlevel 1 goto :wait_dead
set /a _i+=1
if !_i! GEQ 80 goto :wait_timeout
powershell -NoProfile -Command "Start-Sleep -Milliseconds 500" >nul
goto :wait_loop

:wait_ok
set /p _PID=<"%PIDFILE%"
echo [OK] server up ^(pid !_PID!^) - http://0.0.0.0:%PORT%
exit /b 0

:wait_timeout
echo [!] server did not become ready in 40s - last log lines:
powershell -NoProfile -Command "if (Test-Path -LiteralPath '%LOG%') { Get-Content -LiteralPath '%LOG%' -Tail 20 } else { Write-Host '(no log yet)' }"
exit /b 1

:wait_dead
echo [!] server process exited before becoming ready - last log lines:
powershell -NoProfile -Command "if (Test-Path -LiteralPath '%LOG%') { Get-Content -LiteralPath '%LOG%' -Tail 20 } else { Write-Host '(no log yet)' }"
exit /b 1
