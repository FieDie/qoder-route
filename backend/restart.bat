@echo off
REM restart.bat — kill the running QoderRoute server and start it fresh (prod).
REM Usage: restart.bat
REM Optional: set QODERROUTE_FORCE_RESTART_AFTER=<seconds> to force-kill after waiting.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PORT=8010"
set "DATA=%CD%\data"
set "LOG=%DATA%\server.log"
set "PIDFILE=%DATA%\server.pid"
set "LOCKDIR=%DATA%\server.lock.dir"
set "FORCE_AFTER_SECONDS=%QODERROUTE_FORCE_RESTART_AFTER%"
if not defined FORCE_AFTER_SECONDS set "FORCE_AFTER_SECONDS=0"

echo %FORCE_AFTER_SECONDS%| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 (
    echo [!] QODERROUTE_FORCE_RESTART_AFTER must be a non-negative integer
    exit /b 1
)

if not exist "%DATA%" mkdir "%DATA%"

mkdir "%LOCKDIR%" 2>nul
if errorlevel 1 (
    echo [!] another QoderRoute start/restart is already running
    exit /b 1
)

call :resolve_python
if errorlevel 1 goto :fail

echo [*] stopping current server...
set "OLD_PID="
if exist "%PIDFILE%" (
    set /p CANDIDATE_PID=<"%PIDFILE%"
    set "CANDIDATE_PID=!CANDIDATE_PID: =!"
)

if defined CANDIDATE_PID (
    call :is_qoderroute "!CANDIDATE_PID!"
    if not errorlevel 1 (
        set "OLD_PID=!CANDIDATE_PID!"
    ) else (
        call :pid_alive "!CANDIDATE_PID!"
        if not errorlevel 1 (
            echo [!] pidfile points to non-QoderRoute process !CANDIDATE_PID!; refusing to kill it
            goto :fail
        )
    )
)

if not defined OLD_PID goto :after_stop

taskkill /PID !OLD_PID! >nul 2>&1
set /a WAIT_TICKS=0

:wait_old
call :pid_alive "!OLD_PID!"
if errorlevel 1 goto :old_gone
set /a WAIT_TICKS+=1
set /a _mod=WAIT_TICKS %% 20
if !_mod! EQU 0 echo [*] waiting for old server pid !OLD_PID! to finish active streams...
if !FORCE_AFTER_SECONDS! GTR 0 (
    set /a _force_ticks=FORCE_AFTER_SECONDS*2
    if !WAIT_TICKS! GEQ !_force_ticks! (
        echo [!] force timeout reached; killing exact old pid !OLD_PID!
        taskkill /PID !OLD_PID! /T /F >nul 2>&1
        goto :old_gone
    )
)
powershell -NoProfile -Command "Start-Sleep -Milliseconds 500" >nul
goto :wait_old

:old_gone
call :pid_alive "!OLD_PID!"
if not errorlevel 1 (
    echo [!] old server pid !OLD_PID! did not exit; refusing to overlap backends
    goto :fail
)

:after_stop
call :port_in_use
if not errorlevel 1 (
    set "PORT_PID=unknown"
    for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do set "PORT_PID=%%P"
    echo [!] port %PORT% is still owned by an unexpected process ^(!PORT_PID!^); refusing to kill it
    goto :fail
)
echo [*] port %PORT% free

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

:pid_alive
set "_PID=%~1"
echo %_PID%| findstr /r "^[0-9][0-9]*$" >nul || exit /b 1
tasklist /FI "PID eq %_PID%" 2>nul | findstr /r /c:" %_PID% " >nul
if not errorlevel 1 exit /b 0
exit /b 1

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
