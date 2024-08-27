@echo off
%1 mshta vbscript:CreateObject("Shell.Application").ShellExecute("cmd.exe","/c %~s0 ::","","runas",1)(window.close)&&exit
cd /d "%~dp0"
G:\Venvs\TPMSmartCard\Scripts\python.exe BuildPackage.py build
xcopy Config "build\exe.win-amd64-3.11\Config\"
xcopy tools "build\exe.win-amd64-3.11\tools\"
