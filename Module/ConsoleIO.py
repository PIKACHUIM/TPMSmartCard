# -*- coding: utf-8 -*-
"""纯 ctypes 的「可交互控制台进程」——没有 pywinpty 时的后端（32 位构建走这条）。

为什么需要
----------
``tpmvscmgr create`` 的 ``/AdminKey`` ``/PUK`` ``/PIN`` 只接受
``PROMPT`` / ``DEFAULT`` / ``RANDOM``，**没有**「把密码直接写在命令行上」的写法，
自定义密码只能靠「回答控制台提示」录入；这一类提示由控制台 API
（``ReadConsole`` / ``_getch``）读取，而 ``subprocess`` 的 ``stdin=PIPE`` 是管道、
不是控制台，喂不进去（表现为一直卡在提示上直到超时）。

64 位构建用 pywinpty（自带 winpty 伪控制台）；32 位没有任何可用的 pywinpty wheel
（该包只在 cp37 及更早才发过 win32 wheel），所以这里用系统自带 API 实现同一件事：

1. ``CreateProcess(CREATE_NEW_CONSOLE)`` —— 子进程拥有自己的控制台；
2. 父进程 ``FreeConsole()`` 后 ``AttachConsole(子进程 pid)`` —— 父进程打开
   ``CONIN$`` / ``CONOUT$`` 就接到了子进程的控制台上；
3. 写按键用 ``WriteConsoleInputW``（每个字符一条 KEY_EVENT，按下 + 抬起），
   读回显用 ``ReadConsoleOutputCharacterW``；
4. 结束时关掉句柄并 ``FreeConsole()``（GUI 程序本来没有控制台，断开即可）。

对外接口刻意与 ``winpty.PtyProcess`` 对齐（``spawn`` / ``write`` / ``read`` /
``isalive`` / ``close``），由 :mod:`Module.PtyCompat` 在两种后端之间切换。

与 winpty 的差别（调用方都只读一次，不受影响）
------------------------------------------------
``read()`` 返回的是「当前控制台屏幕缓冲区里的全部文本」，
而不是「上次读取之后的新增部分」。
"""

import ctypes
import ctypes.wintypes as wintypes
import shlex
import subprocess
import sys
import time

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

# ---- 常量 -------------------------------------------------------------------
CREATE_NEW_CONSOLE = 0x00000010
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

KEY_EVENT = 0x0001
VK_BACK = 0x08
VK_RETURN = 0x0D
SW_HIDE = 0
ATTACH_PARENT_PROCESS = 0xFFFFFFFF
STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE = -12

# 控制台缓冲区开大一点，避免命令输出较多时把关键行滚动冲掉
BUFFER_WIDTH = 120
BUFFER_HEIGHT = 2000


class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short),
                ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [("dwSize", COORD),
                ("dwCursorPosition", COORD),
                ("wAttributes", ctypes.c_ushort),
                ("srWindow", SMALL_RECT),
                ("dwMaximumWindowSize", COORD)]


class KEY_EVENT_RECORD(ctypes.Structure):
    """与 Win32 的 KEY_EVENT_RECORD 布局一致（16 字节，含 4 字节对齐）。"""

    _fields_ = [("bKeyDown", wintypes.BOOL),
                ("wRepeatCount", ctypes.c_ushort),
                ("wVirtualKeyCode", ctypes.c_ushort),
                ("wVirtualScanCode", ctypes.c_ushort),
                ("UnicodeChar", ctypes.c_wchar),
                ("dwControlKeyState", wintypes.DWORD)]


class _INPUT_EVENT(ctypes.Union):
    _fields_ = [("KeyEvent", KEY_EVENT_RECORD),
                ("_padding", ctypes.c_byte * 16)]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", ctypes.c_ushort), ("Event", _INPUT_EVENT)]


kernel32.AttachConsole.argtypes = [wintypes.DWORD]
kernel32.AttachConsole.restype = wintypes.BOOL
kernel32.FreeConsole.argtypes = []
kernel32.FreeConsole.restype = wintypes.BOOL
kernel32.GetConsoleWindow.argtypes = []
kernel32.GetConsoleWindow.restype = wintypes.HWND
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.SetConsoleScreenBufferSize.argtypes = [wintypes.HANDLE, COORD]
kernel32.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE,
                                                ctypes.POINTER(CONSOLE_SCREEN_BUFFER_INFO)]
kernel32.WriteConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(INPUT_RECORD),
                                        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
kernel32.ReadConsoleOutputCharacterW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
                                                 wintypes.DWORD, COORD,
                                                 ctypes.POINTER(wintypes.DWORD)]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]


def _rebind_std_streams():
    """把 sys.stdout / sys.stderr 重新绑到当前控制台。

    FreeConsole / AttachConsole 之后，Python 里缓存的标准句柄会失效，
    继续 print() 会抛 OSError（句柄无效），所以重新打开 CONOUT$。
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            continue
        try:
            stream = open("CONOUT$", "w", buffering=1, encoding="utf-8", errors="replace")
        except OSError:
            continue
        setattr(sys, name, stream)


class ConsoleProcess:
    """连着子进程控制台的会话：把按键写进去、把屏幕内容读回来。"""

    def __init__(self, process, input_handle=None, output_handle=None, attached=False):
        self._proc = process
        self._input = input_handle
        self._output = output_handle
        self._attached = attached
        self._closed = False

    # ---- 构造 ---------------------------------------------------------------
    @classmethod
    def spawn(cls, command, **kwargs):
        """起一个独占控制台的子进程并挂上去。

        ``command`` 可以是参数列表，也可以是命令行字符串（与 PtyProcess 一致，
        字符串按 shell 规则拆词）。
        """
        if isinstance(command, str):
            command = shlex.split(command)
        process = subprocess.Popen(list(command), creationflags=CREATE_NEW_CONSOLE,
                                   close_fds=True, **kwargs)

        session = cls(process)
        if not session._attach():
            session.close(force=True)
            raise RuntimeError("无法连接到子进程的控制台（进程可能已退出）")
        return session

    def _attach(self):
        """FreeConsole + AttachConsole(子进程)：挂上子进程的控制台。"""
        # 等子进程把控制台建出来（AttachConsole 在此之前会失败）
        for _ in range(60):                      # 最多 6 秒
            kernel32.FreeConsole()
            if kernel32.AttachConsole(self._proc.pid):
                self._attached = True
                break
            if self._proc.poll() is not None:    # 子进程已经退出（命令本身有问题）
                break
            time.sleep(0.1)
        if not self._attached:
            return False

        # 把窗口藏起来：建卡过程不需要给用户看一个黑窗口
        window = kernel32.GetConsoleWindow()
        if window:
            user32.ShowWindow(window, SW_HIDE)

        self._input = kernel32.CreateFileW(
            "CONIN$", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, 0, None)
        self._output = kernel32.CreateFileW(
            "CONOUT$", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, 0, None)
        if self._input == INVALID_HANDLE_VALUE or self._output == INVALID_HANDLE_VALUE:
            return False

        # 缓冲区尽量开大（失败就算了，用系统默认值）
        kernel32.SetConsoleScreenBufferSize(self._output, COORD(BUFFER_WIDTH, BUFFER_HEIGHT))
        return True

    # ---- 与 PtyProcess 对齐的接口 -------------------------------------------
    def write(self, text):
        """把文本当键盘输入写进控制台（``\\n`` 视作回车）。"""
        if self._input is None or self._input == INVALID_HANDLE_VALUE:
            return
        text = str(text).replace("\n", "\r")
        if not text:
            return

        records = (INPUT_RECORD * (len(text) * 2))()
        count = 0
        for char in text:
            if char == "\b":
                virtual_key = VK_BACK
            elif char == "\r":
                virtual_key = VK_RETURN
            else:
                virtual_key = 0
            for key_down in (True, False):        # 按下 + 抬起
                record = records[count]
                count += 1
                record.EventType = KEY_EVENT
                record.Event.KeyEvent.bKeyDown = key_down
                record.Event.KeyEvent.wRepeatCount = 1
                record.Event.KeyEvent.wVirtualKeyCode = virtual_key
                record.Event.KeyEvent.wVirtualScanCode = 0
                record.Event.KeyEvent.UnicodeChar = char
                record.Event.KeyEvent.dwControlKeyState = 0

        written = wintypes.DWORD(0)
        kernel32.WriteConsoleInputW(self._input, records, count, ctypes.byref(written))

    def read(self):
        """取回控制台屏幕缓冲区里的全部文本（行分隔用 ``\\r\\n``）。"""
        if self._output is None or self._output == INVALID_HANDLE_VALUE:
            return ""
        info = CONSOLE_SCREEN_BUFFER_INFO()
        if not kernel32.GetConsoleScreenBufferInfo(self._output, ctypes.byref(info)):
            return ""

        width = max(int(info.dwSize.X), 1)
        last_row = max(int(info.dwCursorPosition.Y), 0)
        buffer = ctypes.create_unicode_buffer(width + 1)
        rows = []
        for row in range(0, last_row + 1):
            read = wintypes.DWORD(0)
            if not kernel32.ReadConsoleOutputCharacterW(self._output, buffer, width,
                                                        COORD(0, row), ctypes.byref(read)):
                continue
            rows.append(buffer[:read.value].rstrip())
        while rows and not rows[-1]:             # 去掉尾部空行
            rows.pop()
        return "\r\n".join(rows)

    def isalive(self):
        return self._proc.poll() is None

    def close(self, force=False):
        if self._closed:
            return
        self._closed = True
        if force and self._proc.poll() is None:
            try:
                self._proc.kill()
            except OSError:
                pass
        try:
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except Exception:
                pass
        self._detach()

    # ---- 内部 ---------------------------------------------------------------
    def _detach(self):
        for name in ("_input", "_output"):
            handle = getattr(self, name)
            if handle and handle != INVALID_HANDLE_VALUE:
                kernel32.CloseHandle(handle)
            setattr(self, name, None)
        if self._attached:
            kernel32.FreeConsole()
            self._attached = False
            # 从终端直接跑源码时父进程本来有控制台（GUI 版没有），把控制台接回来，
            # 否则之后的 print() 会因标准句柄失效而报错
            if kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
                _rebind_std_streams()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
