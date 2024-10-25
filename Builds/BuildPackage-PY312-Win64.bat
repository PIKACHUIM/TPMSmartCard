@echo off
rmdir /s /q build
%1 mshta vbscript:CreateObject("Shell.Application").ShellExecute("cmd.exe","/c %~s0 ::","","runas",1)(window.close)&&exit
cd /d "%~dp0"
cd ..
G:\Venvs\TPMSmartCard\Scripts\python.exe BuildPackage.py  build
REM xcopy Config "build\exe.win-amd64-3.11\Config\"
REM xcopy Config\myfont "build\exe.win-amd64-3.11\Config\\myfont\"
REM xcopy Tooler "build\exe.win-amd64-3.11\Tooler\"
REM xcopy OpenSC "build\exe.win-amd64-3.11\OpenSC\"
