# -*- coding: utf-8 -*-
"""开机自启条目：登录触发的计划任务 + 注册表 Run 键。

主程序带 ``requireAdministrator`` 清单（BuildPackage.py 里 ``uac_admin=True``），
如果自启只写 ``HKCU\\...\\Run``，登录时 Windows 会先弹一次 UAC：用户不点「是」
就不会启动，等于自启失效。因此需要提权的程序优先注册成「登录时触发 + 以最高
权限运行」的计划任务 —— 任务计划会先提权再启动进程，登录过程中不弹 UAC。

不需要提权的程序（WinSSH 代理是普通托盘程序）用注册表 Run 键更简单，也能避免
被计划任务的「最高权限」带成管理员进程。

兜底：注册计划任务失败时（组策略限制、未以管理员身份运行等）自动退回 Run 键，
此时登录会弹一次 UAC —— 功能可用，只是不够安静。
"""

import os
import subprocess
import sys

try:
    import winreg
except ImportError:                       # 非 Windows 平台（便于静态检查）
    winreg = None

# HKCU 下的启动项位置
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# 不弹出控制台窗口（schtasks / powershell）
NO_WINDOW = 0x08000000
# 单条命令的超时时间（秒）：schtasks / Register-ScheduledTask 正常都在 1 秒内
TIMEOUT = 60

_POWERSHELL = ["powershell", "-NoProfile", "-NonInteractive",
               "-ExecutionPolicy", "Bypass"]


def project_root():
    """程序根目录（开发运行时用它拼 SmartCardAPP.py 的路径）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def launched_command():
    """本程序自身的启动方式，返回 (可执行文件, 附加参数)。

    打包后就是安装目录里的 SmartCardAPP.exe；源码运行时用 pythonw
    （无控制台）+ 脚本路径，这样开发机上也能验证自启。
    """
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable), []
    exe = os.path.abspath(sys.executable)
    windowless = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(windowless):
        exe = windowless
    script = os.path.join(project_root(), "SmartCardAPP.py")
    return exe, [script]


def run_command(in_args):
    """执行命令，返回 (是否成功, 输出文本)。输出仅用于日志排查。"""
    try:
        done = subprocess.run(in_args, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                              timeout=TIMEOUT, text=True, errors="replace")
    except Exception as err:
        return False, str(err)
    return done.returncode == 0, (done.stdout or "").strip()


class AutoStart:
    """一个自启条目（计划任务名 / 注册表 Run 值名共用一个 key）。

    :param in_key: 任务名与 Run 值名
    :param in_command: 可执行文件绝对路径
    :param in_args: 附加命令行参数
    :param in_elevated: 目标程序是否要求管理员权限（True 时优先用计划任务）
    """

    def __init__(self, in_key, in_command, in_args=None, in_elevated=False):
        self.key = in_key
        self.command = in_command
        self.args = list(in_args or [])
        self.elevated = in_elevated

    # 查询 ====================================================================
    @property
    def command_line(self):
        """注册表 Run 值的内容，例如 "C:\\...\\SmartCardAPP.exe" --minimized。"""
        text = '"%s"' % self.command
        for arg in self.args:
            text += ' "%s"' % arg if " " in arg else " %s" % arg
        return text

    def has_task(self):
        """计划任务是否存在（schtasks 查询成功即存在）。"""
        return run_command(["schtasks", "/query", "/tn", self.key])[0]

    def run_value(self):
        """注册表 Run 值的内容；不存在时返回空字符串。"""
        if winreg is None:
            return ""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as handle:
                return winreg.QueryValueEx(handle, self.key)[0]
        except OSError:
            return ""

    def is_enabled(self):
        return bool(self.has_task() or self.run_value())

    # 修改 ====================================================================
    def enable(self):
        """写入自启；返回实际使用的方式（``"task"`` / ``"run"``），失败返回空串。"""
        self.disable()                       # 先清掉旧机制，避免登录时启动两次
        if self.elevated and self.create_task():
            return "task"
        if self.write_run_value():
            return "run"
        return ""

    def disable(self):
        """删除两种自启条目（不存在时忽略）。"""
        if self.has_task():
            run_command(["schtasks", "/delete", "/tn", self.key, "/f"])
        self.delete_run_value()
        return None

    def create_task(self):
        """注册「登录时触发 + 最高权限运行」的计划任务（登录不弹 UAC）。

        用 PowerShell 的 ScheduledTasks 模块而不是 ``schtasks /create``：
        命令行版本建出来的任务默认开着「只在交流电源下启动」和 3 天执行时限，
        笔记本电池供电时不会启动、常驻程序还会被中途结束。
        """
        if not self.elevated:
            return False
        arguments = ""
        if self.args:
            arguments = " -Argument '%s'" % " ".join(self.args)
        script = (
            "$ErrorActionPreference='Stop';"
            "$action=New-ScheduledTaskAction -Execute '%s'%s;"
            "$trigger=New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME;"
            "$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries"
            " -DontStopIfGoingOnBatteries"
            " -ExecutionTimeLimit (New-TimeSpan -Seconds 0)"
            " -MultipleInstances IgnoreNew;"
            "$principal=New-ScheduledTaskPrincipal -UserId $env:USERNAME"
            " -LogonType Interactive -RunLevel Highest;"
            "Register-ScheduledTask -TaskName '%s' -Action $action"
            " -Trigger $trigger -Settings $settings -Principal $principal -Force"
            " | Out-Null"
        ) % (self.command, arguments, self.key)
        success, output = run_command(_POWERSHELL + ["-Command", script])
        if not success:
            print("AutoStart: 注册计划任务 %s 失败：%s" % (self.key, output))
        return success

    def write_run_value(self):
        if winreg is None:
            return False
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY) as handle:
                winreg.SetValueEx(handle, self.key, 0, winreg.REG_SZ, self.command_line)
        except OSError as err:
            print("AutoStart: 写入启动项 %s 失败：%s" % (self.key, err))
            return False
        return True

    def delete_run_value(self):
        if winreg is None:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as handle:
                winreg.DeleteValue(handle, self.key)
        except OSError:
            return False
        return True


def app_entry():
    """主程序的自启条目（需要管理员权限，登录后最小化到托盘）。"""
    exe, args = launched_command()
    return AutoStart("TPMSmartCard", exe, args + ["--minimized"], in_elevated=True)


def agent_entry(in_agent_path):
    """WinSSH 代理的自启条目（托盘程序，不提权，直接写 Run 键）。"""
    return AutoStart("WinCryptSSHAgent", in_agent_path, [], in_elevated=False)
