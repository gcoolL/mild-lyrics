@echo off
rem Double-click installer for Windows: runs install.ps1 beside this file, or
rem the latest release's when this file was downloaded on its own.
rem Pass -Uninstall to take Mild Lyrics back out.
setlocal
if exist "%~dp0install.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = 3072; $w = New-Object Net.WebClient; try { $s = $w.DownloadString('https://github.com/gcoolL/mild-lyrics/releases/latest/download/install.ps1') } catch { $s = $w.DownloadString('https://raw.githubusercontent.com/gcoolL/mild-lyrics/main/install.ps1') }; & ([scriptblock]::Create($s)) %*"
    pause
)
