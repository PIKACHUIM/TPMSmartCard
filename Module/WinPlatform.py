# -*- coding: utf-8 -*-
"""32/64 位相关的平台判定与 WOW64 处理。

背景
----
本工具现在出两套包：64 位（Windows 8.1+ x64）与 32 位（Windows 8.1 x86）。
**32 位进程跑在 64 位系统上**时，系统会做 WOW64 重定向，有两处会直接影响功能：

1. 访问 ``%SystemRoot%\\System32`` 实际落到 ``SysWOW64``。
   ``tpmvscmgr.exe`` 只存在于真正的 System32 里（SysWOW64 下没有），
   所以建卡/删卡会直接报「找不到文件」（见 :mod:`Module.TPMSmartCard`）；
2. 访问 ``HKLM\\SOFTWARE`` 实际落到 ``WOW6432Node``。
   Calais 读卡器键（``SOFTWARE\\Microsoft\\Cryptography\\Calais\\Readers``）、
   OpenSC 的安装信息都在 64 位视图里，32 位的 reg.exe 不加 ``/reg:64`` 就查不到
   （见 :mod:`Module.TPMBackup`；MoreConfig 里已经同时查两个视图）。

判定方式
--------
用环境变量 ``PROCESSOR_ARCHITEW6432``：**只有**「32 位进程跑在 64 位系统上」时
才存在，值是真实架构（AMD64/ARM64）。刻意不用 ``platform.architecture()`` ——
它返回的是解释器位宽，分不清「32 位系统」和「32 位进程在 64 位系统上」。
"""

import os
import sys

# 真实系统架构（含 WOW64 场景）
WOW64_ARCH = os.environ.get("PROCESSOR_ARCHITEW6432", "")
PROCESS_ARCH = os.environ.get("PROCESSOR_ARCHITECTURE", "")


def is_wow64():
    """当前是不是「32 位进程跑在 64 位系统上」。"""
    return bool(WOW64_ARCH)


def is_64bit_os():
    """操作系统本身是不是 64 位（不看当前进程位宽）。"""
    if WOW64_ARCH:
        return True
    return PROCESS_ARCH.lower() in ("amd64", "ia64", "arm64")


def is_32bit_python():
    """当前解释器是不是 32 位（打包/自检时用来核对产物）。"""
    return sys.maxsize <= 2 ** 32


def system32_dir():
    """真正的「System32」目录。

    32 位进程在 64 位系统上必须走 ``Sysnative``（该别名只对 WOW64 进程可见），
    否则拿到的 ``tpmvscmgr.exe`` 路径会指向 SysWOW64 下不存在的文件。
    """
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    if is_wow64():
        native = os.path.join(root, "Sysnative")
        if os.path.isdir(native):
            return native
    return os.path.join(root, "System32")


def reg_view_args():
    """``reg.exe`` 的注册表视图参数。

    64 位系统上强制 64 位视图（``/reg:64``），32 位系统上不加
    （32 位系统只有单一视图，传该开关在部分版本上会报错）。
    """
    return ["/reg:64"] if is_64bit_os() else []


def describe():
    """一行平台描述，写进日志便于排查。"""
    return "python=%s process=%s os=%s wow64=%s" % (
        "x86" if is_32bit_python() else "x64",
        PROCESS_ARCH or "?",
        "x64" if is_64bit_os() else "x86",
        "yes" if is_wow64() else "no",
    )
