@echo off
REM ============================================================
REM  Fix-MsiPolicy.bat
REM  Diagnose and remove the policy that blocks MSI installs:
REM     HKLM\SOFTWARE\Policies\Microsoft\Windows\Installer\DisableMSI
REM  Symptom: MSI 1625 "system policy forbids this installation"
REM           / Burn wrapper 0x80070659
REM
REM  Double-click this file, or right-click -> Run as administrator.
REM  It will re-launch itself elevated (UAC prompt) automatically.
REM ============================================================
setlocal
set "PS1=%~dp0Fix-MsiPolicy.ps1"

if not exist "%PS1%" (
    echo [X] Fix-MsiPolicy.ps1 not found next to this .bat
    pause
    exit /b 1
)

REM --- self-elevate (the "::" trick: elevated copy receives :: as %1) ---
%1 mshta vbscript:CreateObject("Shell.Application").ShellExecute("cmd.exe","/c %~s0 ::","","runas",1)(window.close)&&exit

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
echo.
pause
