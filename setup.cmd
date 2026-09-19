@echo off
rem Find a Python new enough to run the setup check, and run it.
rem
rem Windows. Everything this project needs is checked by mild-setup.py,
rem which is Python -- so the only job here is the one job that cannot be
rem done in Python: getting there on a machine that has none.
rem
rem Batch rather than PowerShell on purpose. A .ps1 cannot be double-clicked
rem and will not run at all under the default execution policy, which is the
rem first thing anybody meets and the least useful thing to have to explain.
rem This file runs from a double-click, from cmd and from PowerShell alike.
rem
rem Anything passed here is passed straight on:
rem     setup.cmd --check
rem     setup.cmd --heavy
rem
rem Set MILD_NO_PAUSE to keep it from holding the window open at the end,
rem which is what a script running this without anybody watching wants.
setlocal
set "HERE=%~dp0"

rem Explorer starts a double-clicked script as `cmd /c "..."`, and that
rem window closes the instant this ends -- taking every line of the report
rem with it. This is how to know to hold it open at the end.
set "CLICKED="
echo %cmdcmdline% | find /i "/c" >nul && set "CLICKED=1"
if defined MILD_NO_PAUSE set "CLICKED="

rem Two variables rather than one. The launcher is a program plus a version
rem flag, a found interpreter is one path that may well have a space in it,
rem and there is no single string that can be quoted correctly as both.
set "PYEXE="
set "PYARGS="
set "ASK=import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"

rem The py launcher first. It is installed with Python itself, knows about
rem every version on the machine, and is the one name that does not depend
rem on PATH having been set up.
py -3 -c "%ASK%" >nul 2>&1
if not errorlevel 1 (
    set "PYEXE=py"
    set "PYARGS=-3"
)
if defined PYEXE goto found

rem Then python on PATH -- but not the one Windows puts there itself. A
rem machine with no Python still has a python.exe in WindowsApps: a stub
rem that opens the Microsoft Store and exits. Running it to ask its version
rem opens a shop window in front of whoever ran this.
rem `if defined` is read when the line runs rather than when the block is
rem parsed, so the loop stops looking once one has been found without
rem needing either delayed expansion or a jump out of a block -- and a jump
rem out of a for is the one construct here that different shells have
rem different opinions about.
for /f "delims=" %%p in ('where python 2^>nul') do (
    if not defined PYEXE (
        echo %%p | find /i "WindowsApps" >nul
        if errorlevel 1 (
            "%%p" -c "%ASK%" >nul 2>&1
            if not errorlevel 1 set "PYEXE=%%p"
        )
    )
)
if defined PYEXE goto found

echo [ !!!! ] Python  no 3.10 or newer on this machine
echo.
echo          Install it, and tick "Add python.exe to PATH" in the installer:
echo              https://www.python.org/downloads/
echo          or, from a terminal:
echo              winget install -e --id Python.Python.3.12
echo.
echo          If Python IS installed and this still says so, it is the
echo          Microsoft Store stub that is on PATH rather than the real one.
echo          Settings ^> Apps ^> Advanced app settings ^> App execution
echo          aliases, and turn the python.exe alias off.
if defined CLICKED pause
exit /b 1

:found
"%PYEXE%" %PYARGS% "%HERE%mild-setup.py" %*
set "CODE=%ERRORLEVEL%"
if defined CLICKED pause
exit /b %CODE%
