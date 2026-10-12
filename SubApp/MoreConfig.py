# -*- coding: utf-8 -*-
"""运行环境相关操作：安装 OpenSC、安装/启动 WinSSH 代理。

这些操作原先挂在主界面按钮上，现在统一由「系统设置」的
「OpenSC」「WinSSH 代理」页签调用。
"""

import os
import platform

# OpenSC 安装包（随程序分发的 Light 版 MSI）
OPENSC_DIR = "OpenSC"
OPENSC_MSI = "OpenSC-0.25.1_win%s-Light.msi"
# 系统里 OpenSC 的常见安装目录（用于判断是否已安装）
OPENSC_PATHS = (r"C:\Program Files\OpenSC Project\OpenSC",
                r"C:\Program Files (x86)\OpenSC Project\OpenSC")
# 随程序分发的 SSH 代理
SSH_AGENT = "SSHCardAgent.exe"


class MoreConfig:
    def __init__(self):
        pass

    # OpenSC ===================================================================
    @staticmethod
    def openscPath():
        """返回检测到的 OpenSC 安装目录；未安装时返回空字符串。"""
        for path_now in OPENSC_PATHS:
            if os.path.exists(path_now):
                return path_now
        return ""

    @staticmethod
    def installOpenSC():
        """静默安装随程序分发的 OpenSC，返回安装后的检测结果（需要管理员权限）。"""
        arch = platform.architecture()[0][:2]  # 32 / 64
        msi_path = os.path.join(OPENSC_DIR, OPENSC_MSI % arch)
        os.system('msiexec /i "%s" /passive /norestart' % msi_path)
        return MoreConfig.openscPath()

    # WinSSH 代理 ==============================================================
    @staticmethod
    def sshAgentPath():
        """返回随程序分发的 SSH 代理路径；文件缺失时返回空字符串。"""
        if os.path.exists(SSH_AGENT):
            return os.path.abspath(SSH_AGENT)
        return ""

    @staticmethod
    def setupSSH():
        """通过 Chocolatey 安装 wincrypt-sshagent 并启动代理。"""
        command = ("Set-ExecutionPolicy Bypass -Scope Process -Force;"
                   " [System.Net.ServicePointManager]::SecurityProtocol"
                   " = [System.Net.ServicePointManager]::SecurityProtocol"
                   " -bor 3072; iex ((New-Object System.Net.WebClient)"
                   ".DownloadString('https://community.chocolatey.org/install.ps1'))")
        os.system("powershell %s" % command)
        command = "choco install wincrypt-sshagent"
        os.system("powershell %s" % command)
        return MoreConfig.startSSH()

    @staticmethod
    def startSSH():
        """启动随程序分发的 SSH 代理；文件缺失时返回 False。"""
        agent_path = MoreConfig.sshAgentPath()
        if not agent_path:
            return False
        os.startfile(agent_path)
        return True


if __name__ == "__main__":
    MoreConfig.setupSSH()
