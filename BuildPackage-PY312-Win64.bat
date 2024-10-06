@echo off
rmdir /s /q build
%1 mshta vbscript:CreateObject("Shell.Application").ShellExecute("cmd.exe","/c %~s0 ::","","runas",1)(window.close)&&exit
cd /d "%~dp0"
G:\Venvs\TPMSmartCard\Scripts\python.exe BuildPackage.py  build
xcopy Config "build\exe.win-amd64-3.11\Config\"
xcopy Config\myfont "build\exe.win-amd64-3.11\Config\\myfont\"
xcopy Tooler "build\exe.win-amd64-3.11\Tooler\"
xcopy OpenSC "build\exe.win-amd64-3.11\OpenSC\"
