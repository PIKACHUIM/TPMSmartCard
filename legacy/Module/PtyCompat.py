# -*- coding: utf-8 -*-
"""统一的可交互控制台进程入口：winpty 优先，拿不到就退回纯 ctypes 后端。

* **64 位构建**：``pywinpty`` 有可用 wheel（自带 winpty 伪控制台），行为与历史版本
  完全一致，pip 装上即可；
* **32 位构建**：``pywinpty`` 没有任何 win32 wheel（该包只在 cp37 及更早发过
  win32 wheel），自动退回 :mod:`Module.ConsoleIO` —— 用系统自带控制台 API 实现
  同样的能力，``spawn`` / ``write`` / ``read`` / ``isalive`` / ``close`` 语义一致。

需要强制某个后端时用环境变量 ``TPMSMART_PTY_BACKEND``（``winpty`` 或 ``console``），
例如在 64 位机器上验证 ctypes 后端::

    set TPMSMART_PTY_BACKEND=console
"""

import os

BACKEND = ""
_PTY_PROCESS = None

_wanted = os.environ.get("TPMSMART_PTY_BACKEND", "").strip().lower()

if _wanted != "console":
    try:
        from winpty import PtyProcess as _PTY_PROCESS
        BACKEND = "winpty"
    except Exception as err:                       # ImportError / DLL 加载失败
        if _wanted == "winpty":
            raise ImportError(
                "已指定 TPMSMART_PTY_BACKEND=winpty，但 pywinpty 不可用：%s" % err)
        _PTY_PROCESS = None

if _PTY_PROCESS is None:
    from Module.ConsoleIO import ConsoleProcess as _PTY_PROCESS
    BACKEND = "console"


def spawn(command, **kwargs):
    """起一个可以交互的控制台进程（写按键 / 读输出）。"""
    return _PTY_PROCESS.spawn(command, **kwargs)
