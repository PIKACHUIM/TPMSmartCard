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

安装成功的关键在 :meth:`MoreConfig.installOpenSC`：命令行的 ``msiexec`` **不会自己
提权**，非管理员进程里安装按机器安装的 MSI 会被 Windows Installer 直接拒掉
（实测退出码 1625，日志里 ``MainEngineThread is returning 1625``），所以非提权时
用 ``ShellExecuteEx(runas)`` 触发 UAC 后再装。
"""

import os
import platform
import shutil
import subprocess
import tempfile
import time

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
# 安装包在临时目录里的落脚点（就地安装不可用时改从这里装，见 stageMsi）
OPENSC_STAGE_DIR = "TPMSmartCard-OpenSC"
# 随程序分发的 SSH 代理
SSH_AGENT = "SSHCardAgent.exe"
# 用户设置里「程序启动时自动启动代理」的键（与主题/语言同一个 settings.json）
SSH_AUTOSTART_KEY = "ssh_agent_autostart"


class MoreConfig:
    # msiexec 退出码：0 成功；3010/1641 成功但需要重启
    MSI_OK_CODES = (0, 3010, 1641)
    # 1625：安装被系统策略禁止，**或者**当前进程没有管理员权限（实测：非提权安装
    # 按机器安装的 MSI 就返回 1625）
    MSI_CODE_POLICY = 1625
    # 1618：另一个安装正在进行，稍后重试一次即可
    MSI_CODE_BUSY = 1618
    # 自造失败码（不是 msiexec 的）：找不到随包安装包 / 没跑起来(含取消提权) / 超时
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
    def stagedMsiPath(in_msi_path):
        """安装包在本地临时目录里的副本路径（不保证该副本已存在）。"""
        if not in_msi_path:
            return ""
        return os.path.join(tempfile.gettempdir(), OPENSC_STAGE_DIR,
                            os.path.basename(in_msi_path))

    @staticmethod
    def _clearNetMark(in_path):
        """删掉文件上的「来自网络」标记（NTFS 备用数据流 Zone.Identifier）。

        从网上解压出来的安装包会带这个标记，就地安装时有被拦成「无法打开此安装
        程序包」的风险；删不掉（无权限/文件系统不支持）就算了，不影响安装。
        """
        for stream in (":Zone.Identifier", ":Zone.Identifier:$DATA"):
            try:
                os.remove(in_path + stream)
            except OSError:
                continue
            print("OpenSC Unblock:", in_path + stream)

    @staticmethod
    def stageMsi(in_msi_path):
        """把安装包复制到本地临时目录并清掉来源标记，返回交给 msiexec 的路径。

        为什么要先复制一份（Inno 安装器同样是先把 MSI 解到 ``{tmp}`` 再装）：

        * 程序目录可能在 U 盘 / 网络盘 / 权限受限目录，Windows Installer 服务打不开
          时就地安装会报 1619/1620「无法打开此安装程序包」；
        * 下载来的包带「网络来源」标记时同理；
        * 复制失败则退回原路径，行为与以前一致。
        """
        target = MoreConfig.stagedMsiPath(in_msi_path)
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(in_msi_path, target)          # 覆盖上一次的副本
        except OSError as err:
            print("OpenSC Stage Error:", err)
            return in_msi_path
        MoreConfig._clearNetMark(target)
        return target

    @staticmethod
    def isAdmin():
        """当前进程是否已提权（管理员）。判断不出来时按已提权处理，走直连安装。"""
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception as err:
            print("OpenSC Admin Check Error:", err)
            return True

    @staticmethod
    def _runMsiexecElevated(in_parameters, in_timeout):
        """用 ``ShellExecuteEx(runas)`` 提权运行 msiexec，等它结束并取退出码。

        命令行 msiexec 不会自己提权（见模块说明，实测非提权直接 1625），所以这里显式
        触发 UAC。返回退出码；启动失败（含用户在 UAC 上点了「否」）返回 None。
        """
        import ctypes
        from ctypes import wintypes

        class _ShellExecuteInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD),
                        ("fMask", ctypes.c_ulong),
                        ("hwnd", wintypes.HWND),
                        ("lpVerb", wintypes.LPCWSTR),
                        ("lpFile", wintypes.LPCWSTR),
                        ("lpParameters", wintypes.LPCWSTR),
                        ("lpDirectory", wintypes.LPCWSTR),
                        ("nShow", ctypes.c_int),
                        ("hInstApp", wintypes.HINSTANCE),
                        ("lpIDList", ctypes.c_void_p),
                        ("lpClass", wintypes.LPCWSTR),
                        ("hkeyClass", wintypes.HKEY),
                        ("dwHotKey", wintypes.DWORD),
                        ("hIconOrMonitor", wintypes.HANDLE),
                        ("hProcess", wintypes.HANDLE)]

        SEE_MASK_NOCLOSEPROCESS = 0x00000040
        SEE_MASK_NOASYNC = 0x00000100
        WAIT_TIMEOUT = 0x00000102
        SW_SHOWNORMAL = 1
        info = _ShellExecuteInfo()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
        info.lpVerb = "runas"
        info.lpFile = "msiexec.exe"
        info.lpParameters = in_parameters
        info.nShow = SW_SHOWNORMAL
        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
            # 1223 = 用户在 UAC 提示上点了「否」
            print("OpenSC Elevate Error:", ctypes.GetLastError())
            return None
        try:
            waited = ctypes.windll.kernel32.WaitForSingleObject(
                info.hProcess, int(in_timeout * 1000) & 0x7FFFFFFF)
            if waited == WAIT_TIMEOUT:
                print("OpenSC Elevate Timeout")
                return None
            code = wintypes.DWORD()
            if not ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess,
                                                             ctypes.byref(code)):
                return None
            return int(code.value)
        finally:
            ctypes.windll.kernel32.CloseHandle(info.hProcess)

    @staticmethod
    def _runMsiexec(in_args, in_timeout):
        """运行 msiexec 安装，返回退出码；没跑起来返回 None。

        已提权时直接调用（参数列表传参，路径里的空格/中文都安全）；没提权时先提权
        —— 否则按机器安装的 MSI 会被 Windows Installer 拒掉（1625）。
        """
        if MoreConfig.isAdmin():
            try:
                result = subprocess.run(["msiexec"] + in_args, timeout=in_timeout)
            except subprocess.TimeoutExpired:
                print("Install OpenSC Timeout:", in_timeout)
                return MoreConfig.MSI_TIMEOUT
            except Exception as err:
                print("Install OpenSC Error:", err)
                return None
            return int(result.returncode)
        parameters = " ".join('"%s"' % item if " " in item else item for item in in_args)
        return MoreConfig._runMsiexecElevated(parameters, in_timeout)

    @staticmethod
    def installOpenSC(in_timeout=1800):
        """安装随程序分发的 OpenSC，返回 ``(是否成功, 退出码, 日志路径)``。

        * 先复制到本地临时目录再装（见 :meth:`stageMsi`），避开「安装包打不开」类故障；
        * 没提权时用 runas 触发 UAC（命令行 msiexec 自己不提权，非提权安装必失败）；
        * ``/qb`` 只显示进度条（用户看得到在装、可取消，出错时 MSI 也会弹原因），
          ``/l*v`` 写详细日志 —— 退出码与日志路径回给界面；
        * 1618（另一个安装正在进行）等几秒重试一次；
        * 退出码 3010/1641 表示「装好了但需要重启」，也算成功。

        旧实现用 ``os.system`` 相对路径且丢掉退出码：安装失败时既没有原因，调用方还会
        照样重启，重启后又提示未安装，用户只能看到「反复提示 + 什么都没装上」。
        """
        msi_path = MoreConfig.msiPath()
        if not msi_path:
            return False, MoreConfig.MSI_NO_PACKAGE, ""
        log_path = os.path.join(tempfile.gettempdir(), OPENSC_LOG)
        args = ["/i", MoreConfig.stageMsi(msi_path), "/qb", "/norestart",
                "REMOVE=OpenSC_menu", "/l*v", log_path]
        print("Install OpenSC:", args[1])
        code = None
        for attempt in (1, 2):
            code = MoreConfig._runMsiexec(args, in_timeout)
            if code is None or code != MoreConfig.MSI_CODE_BUSY:
                break
            print("Install OpenSC Busy(1618), retry after 3s")
            time.sleep(3)
        if code is None:
            return False, MoreConfig.MSI_NO_START, log_path
        if code == MoreConfig.MSI_TIMEOUT:
            return False, MoreConfig.MSI_TIMEOUT, log_path
        return code in MoreConfig.MSI_OK_CODES, code, log_path

    @staticmethod
    def installFailText(in_i18n, in_code, in_log=""):
        """把安装失败的结果拼成给用户看的文案（主程序与系统设置共用）。

        ``in_i18n`` 是 ``Module.I18n`` 的翻译器/管理器；退出码用来给出最贴近的原因，
        日志路径与可直接双击的安装包路径一并列出，用户可自行重试或把日志回传排查。
        """
        if in_code == MoreConfig.MSI_NO_PACKAGE:
            return in_i18n.t("msg_osc_fail_missing")
        if in_code == MoreConfig.MSI_NO_START:
            reason = in_i18n.t("msg_osc_reason_admin")
        elif in_code == MoreConfig.MSI_CODE_POLICY:
            reason = in_i18n.t("msg_osc_reason_policy")
        else:
            reason = in_i18n.t("msg_osc_reason_other")
        # 优先给"临时目录里的副本"，它已经清掉来源标记，双击装最省事
        staged = MoreConfig.stagedMsiPath(MoreConfig.msiPath())
        package = staged if os.path.isfile(staged) else (MoreConfig.msiPath() or "-")
        return in_i18n.tp("msg_osc_fail", in_code if in_code >= 0 else "-",
                          reason, in_log or "-", package)

    # WinSSH 代理 ==============================================================
    @staticmethod
    def sshAgentPath():
        """返回随程序分发的 SSH 代理绝对路径；文件缺失时返回空字符串。"""
        path_now = Paths.resource(SSH_AGENT)
        return path_now if os.path.isfile(path_now) else ""

    @staticmethod
    def sshAutoStart():
        """程序启动时是否自动拉起 WinSSH 代理（用户设置，默认关）。"""
        from Module.I18n import read_user_settings
        return bool(read_user_settings().get(SSH_AUTOSTART_KEY))

    @staticmethod
    def setSshAutoStart(in_value):
        """记住「程序启动时自动启动代理」开关；失败返回 False。"""
        from Module.I18n import read_user_settings, write_user_settings
        settings = read_user_settings()
        settings[SSH_AUTOSTART_KEY] = bool(in_value)
        return write_user_settings(settings)

    @staticmethod
    def sshAgentRunning():
        """代理进程是否已经在跑（避免重复拉起）。"""
        from Module import WinPlatform
        return WinPlatform.process_running(SSH_AGENT)

    @staticmethod
    def startSSHIfNeeded():
        """程序启动时按设置拉起代理；返回 ``(是否拉起, 说明)``。"""
        if not MoreConfig.sshAutoStart():
            return False, "未开启「程序启动时自动启动」"
        path_now = MoreConfig.sshAgentPath()
        if not path_now:
            return False, "找不到随程序分发的 %s" % SSH_AGENT
        if MoreConfig.sshAgentRunning():
            return False, "代理已在运行"
        try:
            os.startfile(path_now)
        except Exception as err:
            return False, "启动失败: %s" % err
        return True, "已启动 %s" % path_now

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
