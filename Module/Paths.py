# -*- coding: utf-8 -*-
"""程序路径 —— 随程序分发的资源一律从「程序根目录」解析，不依赖工作目录。

背景
----
程序里大量使用 ``Config/xxx.json``、``OpenSC/opensc-tool.exe`` 这类相对路径，
它们都相对**工作目录**解析。安装后从安装目录启动（快捷方式带 ``WorkingDir``）
一切正常，但以下几种启动方式给的工作目录并不是程序目录：

* 双击 ``.tsb`` 备份文件（文件类型关联，命令行是 ``SmartCardAPP.exe "%1"``，
  注意注册表里没法给 ``shell\\open\\command`` 指定工作目录）；
* 登录自启（注册表 ``Run`` 值 / 计划任务，工作目录是 ``C:\\Windows`` 或其它）；
* 从别的目录用命令行启动。

此时 ``Config/tables.json`` 找不到，打包版会直接弹出 cx_Freeze 的错误框::

    FileNotFoundError: [Errno 2] No such file or directory: 'Config/tables.json'

解决办法（两种一起用，互为兜底）：

1. 资源路径统一走 :func:`resource`，与工作目录无关；
2. 各入口（``SmartCardAPP`` / ``SmartCardWEB`` / ``SubApp.*``）启动时调用
   :func:`ensure_workdir`，把工作目录切到程序根目录，顺带兜住第三方库与
   ``subprocess`` 调用里的相对路径（例如 OpenSC 工具、TPMImport.exe）。

程序根目录可用环境变量 ``TPMSMART_HOME`` 覆盖（便于挂外部资源目录）。
"""

import os
import sys

# 用来判定「这个目录是不是程序根目录」的标志子目录
CONFIG_DIR = "Config"

# 用户数据目录名（%APPDATA%\<这个名字>）：设置、日志、FIDO 凭据都放这里
APP_DIR_NAME = "TPMSmartCard"


def project_root():
    """程序根目录（存在 ``Config`` 子目录的那个目录）。

    优先级：``TPMSMART_HOME`` > 打包后可执行文件所在目录 > 源码目录 > 当前工作目录。
    """
    override = os.environ.get("TPMSMART_HOME")
    if override and os.path.isdir(override):
        return os.path.abspath(override)
    if getattr(sys, "frozen", False):
        # cx_Freeze / PyInstaller 打包后以可执行文件所在目录为准
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        if os.path.isdir(os.path.join(exe_dir, CONFIG_DIR)):
            return exe_dir
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    if os.path.isdir(os.path.join(root, CONFIG_DIR)):
        return root
    return os.getcwd()


def resource(*parts):
    """程序根目录下的资源绝对路径，例如 ``resource("Config", "tables.json")``。"""
    return os.path.join(project_root(), *parts)


def appdata_dir():
    """用户数据目录 ``%APPDATA%\\TPMSmartCard``（不存在时按需创建）。"""
    base = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(base, APP_DIR_NAME)


def data_path(*parts):
    """用户数据目录下的路径；目录不存在时自动创建。"""
    folder = appdata_dir()
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        pass
    return os.path.join(folder, *parts)


def fido_dir():
    """FIDO2 凭据与配置目录 ``%APPDATA%\\TPMSmartCard\\Fido``。"""
    folder = data_path("Fido")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        pass
    return folder


def ensure_workdir():
    """把工作目录切到程序根目录，返回切换前的工作目录。

    命令行里给出的相对路径（例如双击 ``.tsb`` 时主程序收到的备份文件）会先按
    原工作目录转成绝对路径，避免切换后找不到；切换失败（目录被删、无权限）
    时保持原工作目录，仅靠 :func:`resource` 兜底。
    """
    try:
        old_dir = os.getcwd()
    except OSError:                      # 工作目录已被删除等情况
        old_dir = project_root()
    _resolve_argv_paths(old_dir)
    root = project_root()
    if os.path.isdir(root):
        try:
            os.chdir(root)
        except OSError:
            pass
    return old_dir


def _resolve_argv_paths(base_dir):
    """把命令行参数里确实指向文件的相对路径改成绝对路径（原地改写 ``sys.argv``）。

    含 ``sys.argv[0]``（源码运行时是脚本路径，重启自身要用到）。只改写
    「相对 ``base_dir`` 存在」的参数，其余（开关、URL、不存在的路径）原样保留，
    行为与切换工作目录前一致。
    """
    for index in range(len(sys.argv)):
        text = str(sys.argv[index]).strip().strip('"')
        if not text or text.startswith("-") or os.path.isabs(text):
            continue
        full = os.path.join(base_dir, text)
        if os.path.exists(full):
            sys.argv[index] = os.path.abspath(full)
