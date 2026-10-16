# -*- coding: utf-8 -*-
"""运行环境相关操作：安装 OpenSC、安装/启动 WinSSH 代理。

这些操作原先挂在主界面按钮上，现在统一由「系统设置」的
「OpenSC」「WinSSH 代理」页签调用。

OpenSC 有两条链路，不要混用：

* **读卡**用的是随程序分发的 ``<程序目录>\\OpenSC`` 工具与 opensc.dll（见
  ``Module.Paths``），与下面要装的系统级 MSI 无关；
* **装没装**看系统里有没有 OpenSC（:meth:`MoreConfig.openscPath`）：优先读 MSI
  自己写的注册表（``HKLM\\SOFTWARE\\OpenSC Project\\OpenSC``），再按
  ``%ProgramFiles%`` 环境变量拼，最后才是两个默认目录兜底。只写死
  ``C:\\Program Files...`` 的话，系统盘不是 C: 或者用户装在别处时，装好了也会被
  判成「未安装」而反复提示。
"""

import os
import platform
import subprocess
import tempfile

from Module import Paths

# OpenSC 安装包（随程序分发的 Light 版 MSI）
OPENSC_DIR = "OpenSC"
OPENSC_MSI = "OpenSC-0.25.1_win%s-Light.msi"
# 系统里 OpenSC 的默认安装目录（兜底用，正常应命中注册表或 %ProgramFiles%）
OPENSC_PATHS = (r"C:\Program Files\OpenSC Project\OpenSC",
                r"C:\Program Files (x86)\OpenSC Project\OpenSC")
# MSI 在注册表里留下的安装信息：ConfigFile / SmDir / ProfileDir 都指向安装目录内的
# 文件或子目录，取其所在目录即为安装目录
OPENSC_REG_KEYS = (r"SOFTWARE\OpenSC Project\OpenSC",
                   r"SOFTWARE\WOW6432Node\OpenSC Project\OpenSC")
OPENSC_REG_VALUES = ("ConfigFile", "SmDir", "ProfileDir")
# 安装日志文件名（失败时把完整路径显示给用户，便于回传排查）
OPENSC_LOG = "TPMSmartCard-opensc-install.log"
# 随程序分发的 SSH 代理
SSH_AGENT = "SSHCardAgent.exe"


class MoreConfig:
    # msiexec 退出码：0 成功；3010/1641 成功但需要重启
    MSI_OK_CODES = (0, 3010, 1641)
    # 系统/组策略禁止安装 MSI（DisableMSI），现场最常见的一种失败
    MSI_CODE_POLICY = 1625
    # 自造失败码（不是 msiexec 的）：找不到随包安装包 / msiexec 没起来 / 超时
    MSI_NO_PACKAGE = -1
    MSI_NO_START = -2
    MSI_TIMEOUT = -3

    def __init__(self):
        pass

    # OpenSC ===================================================================
    @staticmethod
    def _dirOf(in_value):
        """把注册表里的「文件或目录」值还原成确实存在的目录；都不存在返回空字符串。"""
        text = str(in_value or "").strip().strip('"')
        if not text:
            return ""
        for path_now in (text, os.path.dirname(text.rstrip("\\/"))):
            if path_now and os.path.isdir(path_now):
                return path_now
        return ""

    @staticmethod
    def openscRegPath():
        """从注册表读 OpenSC 安装目录（MSI 自己写的键，最可靠）；读不到返回空字符串。"""
        try:
            import winreg
        except ImportError:               # 非 Windows 平台（本工具跑不到）
            return ""
        for key_name in OPENSC_REG_KEYS:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_name) as handle:
                    for value_name in OPENSC_REG_VALUES:
                        try:
                            value, _ = winreg.QueryValueEx(handle, value_name)
                        except OSError:
                            continue
                        path_now = MoreConfig._dirOf(value)
                        if path_now:
                            return path_now
            except OSError:
                continue
        return ""

    @staticmethod
    def openscProgramFiles():
        """按环境变量拼 OpenSC 的默认安装目录（系统盘不是 C: 时写死路径必然失效）。"""
        for env_name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(env_name)
            if not base:
                continue
            path_now = os.path.join(base, "OpenSC Project", "OpenSC")
            if os.path.isdir(path_now):
                return path_now
        return ""

    @staticmethod
    def openscPath():
        """返回检测到的 OpenSC 安装目录；未安装时返回空字符串。

        检测顺序（任一命中即视为已安装）：注册表 → 环境变量拼出的 Program Files
        → 两个默认目录兜底。
        """
        for finder in (MoreConfig.openscRegPath, MoreConfig.openscProgramFiles):
            path_now = finder()
            if path_now:
                return path_now
        for path_now in OPENSC_PATHS:
            if os.path.isdir(path_now):
                return path_now
        return ""

    @staticmethod
    def msiPath():
        """返回随程序分发的 OpenSC 安装包**绝对路径**；文件缺失时返回空字符串。

        必须是绝对路径：程序可能从任意工作目录启动（登录自启、双击 .tsb 关联文件），
        相对路径会去别处找安装包，msiexec 报 1619「无法打开此安装程序包」。
        优先本机架构对应的包，其次是另一个架构的包（都装系统组件），最后任意 MSI。
        """
        directory = Paths.resource(OPENSC_DIR)
        try:
            names = sorted(os.listdir(directory))
        except OSError as err:
            print("OpenSC Package Dir Error:", err)
            return ""
        arch = (platform.architecture()[0] or "64bit")[:2]
        wanted = [OPENSC_MSI % arch, OPENSC_MSI % ("32" if arch == "64" else "64")]
        wanted += [name for name in names if name.lower().endswith(".msi")]
        for name in wanted:
            path_now = os.path.join(directory, name)
            if os.path.isfile(path_now):
                return path_now
        print("OpenSC Package Missing:", directory)
        return ""

    @staticmethod
    def installOpenSC(in_timeout=1800):
        """静默安装随程序分发的 OpenSC，返回 ``(是否成功, 退出码, 日志路径)``。

        * 绝对路径 + 参数列表调用：工作目录、路径里的空格/中文都不会再影响 msiexec；
        * ``/qb`` 只显示进度条（用户看得到在装、可取消，出错时 MSI 也会弹原因），
          ``/l*v`` 写详细日志 —— 退出码与日志路径回给界面；
        * 退出码 3010/1641 表示「装好了但需要重启」，也算成功。

        旧实现用 ``os.system`` 且丢掉退出码：安装失败时既没有原因，调用方还会照样
        重启，重启后又提示未安装，用户只能看到「反复提示 + 什么都没装上」。
        """
        msi_path = MoreConfig.msiPath()
        if not msi_path:
            return False, MoreConfig.MSI_NO_PACKAGE, ""
        log_path = os.path.join(tempfile.gettempdir(), OPENSC_LOG)
        command = ["msiexec", "/i", msi_path, "/qb", "/norestart",
                   "REMOVE=OpenSC_menu", "/l*v", log_path]
        print("Install OpenSC:", msi_path)
        try:
            result = subprocess.run(command, timeout=in_timeout)
        except subprocess.TimeoutExpired:
            print("Install OpenSC Timeout:", in_timeout)
            return False, MoreConfig.MSI_TIMEOUT, log_path
        except Exception as err:
            print("Install OpenSC Error:", err)
            return False, MoreConfig.MSI_NO_START, log_path
        code = int(result.returncode)
        return code in MoreConfig.MSI_OK_CODES, code, log_path

    @staticmethod
    def installFailText(in_i18n, in_code, in_log=""):
        """把安装失败的结果拼成给用户看的文案（主程序与系统设置共用）。

        ``in_i18n`` 是 ``Module.I18n`` 的翻译器/管理器；退出码用来给出最贴近的原因，
        日志路径与安装包路径一并列出，用户可自行重试或把日志回传排查。
        """
        if in_code == MoreConfig.MSI_NO_PACKAGE:
            return in_i18n.t("msg_osc_fail_missing")
        reason = in_i18n.t("msg_osc_reason_policy" if in_code == MoreConfig.MSI_CODE_POLICY
                           else "msg_osc_reason_other")
        return in_i18n.tp("msg_osc_fail", in_code if in_code >= 0 else "-",
                          reason, in_log or "-", MoreConfig.msiPath() or "-")

    # WinSSH 代理 ==============================================================
    @staticmethod
    def sshAgentPath():
        """返回随程序分发的 SSH 代理绝对路径；文件缺失时返回空字符串。"""
        path_now = Paths.resource(SSH_AGENT)
        return path_now if os.path.isfile(path_now) else ""

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
