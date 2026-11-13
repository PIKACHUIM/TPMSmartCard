@echo off
rmdir /s /q build
%1 mshta vbscript:CreateObject("Shell.Application").ShellExecute("cmd.exe","/c %~s0 ::","","runas",1)(window.close)&&exit
cd /d "%~dp0"
D:\Venvs\TPMSmartCard-PY308\Scripts\python.exe BuildPackage.py build -p ttkbootstrap
xcopy Config "build\exe.win-amd64-3.8\Config\"
xcopy Config\myfont "build\exe.win-amd64-3.8\Config\\myfont\"
xcopy Tooler "build\exe.win-amd64-3.8\Tooler\"
xcopy OpenSC "build\exe.win-amd64-3.8\OpenSC\"