# -*- coding: utf-8 -*-
"""Windows 托盘图标（Shell_NotifyIcon 的 ctypes 封装）。

主程序「最小化 / 关闭到托盘」需要一个常驻通知区域的图标，并提供右键菜单
（显示主程序 / 退出）。这里没有引入 pystray 之类的第三方托盘库：ctypes 是
标准库，既不用改 requirements.txt，也不给 cx_Freeze 打包增加隐藏依赖，
与 Module/TPMSmartCard.py、Module/TPMBackup.py 直接调 Win32 的做法一致。

线程模型：
* 托盘窗口（隐藏窗口）与消息循环跑在独立线程里（``start()`` 启动），
  不干扰 Tk 的主循环；
* 鼠标/菜单事件先入队，再由 Tk 线程按 ``POLL_MS`` 轮询取走并执行回调
  —— Tk 控件只能在创建它的线程里操作，回调不能直接在托盘线程里跑。
"""

import ctypes
import queue
import threading
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# 窗口消息
WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_TRAYICON = 0x0400 + 20          # WM_USER + 20：托盘回调消息

# Shell_NotifyIcon
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_INFO = 0x01

# 图标与菜单
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
IDI_APPLICATION = 32512
SM_CXSMICON, SM_CYSMICON = 49, 50
MF_STRING, MF_SEPARATOR = 0x0000, 0x0800
TPM_RETURNCMD, TPM_RIGHTBUTTON = 0x0100, 0x0002

# 菜单项与内部动作
MENU_SHOW, MENU_EXIT = 1, 2
ACTION_SHOW, ACTION_EXIT = "show", "exit"

_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wintypes.HWND, wintypes.UINT,
                              wintypes.WPARAM, wintypes.LPARAM)


class _NOTIFYICONDATAW(ctypes.Structure):
    """NOTIFYICONDATAW（Vista 及以上版本的完整布局）。"""

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeout", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


# 句柄/指针必须显式声明类型：ctypes 默认把返回值当 C int、把 Python 整数参数
# 当 32 位 int，64 位下句柄会被截断，症状是"窗口/图标建不出来"或回调收不到消息。
_user32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
_user32.RegisterClassExW.restype = wintypes.WORD
_user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
_user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR,
                                    wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                    wintypes.HINSTANCE, ctypes.c_void_p]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = _LRESULT
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT]
_user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.DispatchMessageW.restype = _LRESULT
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM]
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.PostQuitMessage.argtypes = [ctypes.c_int]
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.CreatePopupMenu.argtypes = []
_user32.CreatePopupMenu.restype = wintypes.HMENU
_user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT,
                                ctypes.c_size_t, wintypes.LPCWSTR]
_user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   ctypes.c_void_p]
_user32.TrackPopupMenu.restype = ctypes.c_int
_user32.DestroyMenu.argtypes = [wintypes.HMENU]
_user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                               wintypes.UINT, ctypes.c_int, ctypes.c_int,
                               wintypes.UINT]
_user32.LoadImageW.restype = wintypes.HANDLE
_user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
_user32.LoadIconW.restype = wintypes.HICON
_user32.DestroyIcon.argtypes = [wintypes.HICON]
_shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                       ctypes.POINTER(_NOTIFYICONDATAW)]
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
_user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
_user32.RegisterWindowMessageW.restype = wintypes.UINT

# explorer 重启（崩溃、更新）会清空通知区域，系统会广播该消息，
# 收到后必须重新 NIM_ADD，否则托盘图标就永久消失了
_TASKBAR_CREATED = _user32.RegisterWindowMessageW("TaskbarCreated")


class TrayIcon:
    """通知区域图标：左键单击（或双击）显示主窗口，右键弹出「显示/退出」菜单。

    托盘不可用时（例如窗口建立失败）``start()`` 返回 False，调用方应当
    放弃「隐藏到托盘」的行为，否则程序会既看不见窗口又退不出去。
    """

    POLL_MS = 120                  # Tk 线程取事件的间隔（毫秒）
    CLASS_NAME = "TPMSmartCardTrayWnd"

    def __init__(self, in_root, in_icon, in_tip, in_menu_show, in_menu_exit,
                 in_on_show, in_on_exit):
        self.root = in_root
        self.icon_path = in_icon
        self.tip = str(in_tip)[:127]                 # szTip 最大 127 字符
        self.menu_show = in_menu_show
        self.menu_exit = in_menu_exit
        self.on_show = in_on_show
        self.on_exit = in_on_exit
        self.actions = queue.Queue()
        self.alive = False
        self.hwnd = 0
        self.hicon = 0
        self.added = False
        self.thread = None
        self.ready = threading.Event()
        self.error = ""
        # 回调函数必须保持引用，否则会被回收，窗口过程回调时就崩了
        self.wnd_proc = _WNDPROC(self._wnd_proc)

    # 对外接口 =================================================================
    def start(self):
        """启动托盘线程并注册图标；返回是否成功（失败原因见 ``self.error``）。"""
        if self.alive:
            return True
        self.alive = True
        self.thread = threading.Thread(target=self._run, name="TrayIcon", daemon=True)
        self.thread.start()
        self.ready.wait(timeout=5)
        if not (self.hwnd and self.added):
            self.error = self.error or "托盘图标注册失败"
            self.alive = False
            return False
        self._schedule_poll()
        return True

    def stop(self):
        """移除图标并结束托盘线程；在程序退出前调用。"""
        self.alive = False
        if self.hwnd:
            _user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        if self.thread is not None:
            self.thread.join(timeout=3)
        self.thread = None
        return None

    @property
    def is_alive(self):
        return bool(self.alive and self.hwnd and self.added)

    def set_texts(self, in_tip=None, in_menu_show=None, in_menu_exit=None):
        """语言切换后更新提示文字（右键菜单每次弹出时按当前文字重建）。"""
        if in_tip is not None:
            self.tip = str(in_tip)[:127]
        if in_menu_show is not None:
            self.menu_show = in_menu_show
        if in_menu_exit is not None:
            self.menu_exit = in_menu_exit
        if self.hwnd and self.added:
            _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid(NIF_TIP)))
        return None

    def notify(self, in_title, in_text):
        """弹出气泡提示（托盘不可用时静默忽略）。"""
        if not self.is_alive:
            return False
        nid = self._nid(NIF_INFO)
        nid.szInfoTitle = str(in_title)[:63]         # szInfoTitle 最大 63 字符
        nid.szInfo = str(in_text)[:255]              # szInfo 最大 255 字符
        nid.dwInfoFlags = NIIF_INFO
        return bool(_shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid)))

    # 托盘线程 =================================================================
    def _run(self):
        hinst = _kernel32.GetModuleHandleW(None)
        wnd_class = _WNDCLASSEXW()
        wnd_class.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wnd_class.lpfnWndProc = self.wnd_proc
        wnd_class.hInstance = hinst
        wnd_class.lpszClassName = self.CLASS_NAME
        if not _user32.RegisterClassExW(ctypes.byref(wnd_class)):
            self.error = "RegisterClassExW 失败（%d）" % ctypes.get_last_error()
            self.ready.set()
            return
        self.hwnd = _user32.CreateWindowExW(0, self.CLASS_NAME, self.CLASS_NAME,
                                            0, 0, 0, 0, 0, None, None, hinst, None)
        if not self.hwnd:
            self.error = "CreateWindowExW 失败（%d）" % ctypes.get_last_error()
            self.ready.set()
            return
        self.hicon = self._load_icon()
        if self.alive:
            self._add_icon()
        if not self.alive:
            # 等待期间已经被 stop()：立刻让消息循环退出
            _user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        self.ready.set()
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        # 消息循环结束后的清理（WM_DESTROY 里已经移除了图标）
        if self.hicon:
            _user32.DestroyIcon(self.hicon)
            self.hicon = 0
        _user32.UnregisterClassW(self.CLASS_NAME, hinst)
        self.hwnd = 0

    def _nid(self, in_flags):
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = in_flags
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self.hicon
        nid.szTip = self.tip
        return nid

    def _add_icon(self):
        """把图标加到通知区域；也被 TaskbarCreated 消息复用。"""
        nid = self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        self.added = bool(_shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        if not self.added:
            self.error = "Shell_NotifyIcon(NIM_ADD) 失败"
        return self.added

    def _load_icon(self):
        """按系统小图标尺寸（SM_CXSMICON）加载 ico，避免被缩放得糊。"""
        cx = _user32.GetSystemMetrics(SM_CXSMICON)
        cy = _user32.GetSystemMetrics(SM_CYSMICON)
        handle = _user32.LoadImageW(None, self.icon_path, IMAGE_ICON, cx, cy,
                                    LR_LOADFROMFILE)
        if not handle:
            # 找不到 ico（例如工作目录不对）时退回系统默认图标，别让托盘空着
            handle = _user32.LoadIconW(None, IDI_APPLICATION)
        return handle

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == _TASKBAR_CREATED:
            # 任务栏（explorer）重启后通知区域被清空：重新添加图标
            self.added = False
            self._add_icon()
            return 0
        if msg == WM_TRAYICON:
            code = lparam & 0xFFFF
            if code in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self.actions.put(ACTION_SHOW)
            elif code == WM_RBUTTONUP:
                self._popup_menu(hwnd)
            return 0
        if msg == WM_COMMAND:
            command = wparam & 0xFFFF
            if command == MENU_SHOW:
                self.actions.put(ACTION_SHOW)
            elif command == MENU_EXIT:
                self.actions.put(ACTION_EXIT)
            return 0
        if msg == WM_CLOSE:
            _user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            if self.added:
                _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid(0)))
                self.added = False
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _popup_menu(self, hwnd):
        """弹出右键菜单；用 TPM_RETURNCMD 直接取回选中项，避免异步 WM_COMMAND。"""
        menu = _user32.CreatePopupMenu()
        if not menu:
            return
        command = 0
        try:
            _user32.AppendMenuW(menu, MF_STRING, MENU_SHOW, self.menu_show)
            _user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            _user32.AppendMenuW(menu, MF_STRING, MENU_EXIT, self.menu_exit)
            point = _POINT()
            _user32.GetCursorPos(ctypes.byref(point))
            # 菜单属于隐藏窗口：先置前台，否则点到菜单以外时菜单不会收起
            _user32.SetForegroundWindow(hwnd)
            command = _user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                             point.x, point.y, 0, hwnd, None)
            _user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        finally:
            _user32.DestroyMenu(menu)
        if command == MENU_SHOW:
            self.actions.put(ACTION_SHOW)
        elif command == MENU_EXIT:
            self.actions.put(ACTION_EXIT)
        return None

    # Tk 线程 ==================================================================
    def _schedule_poll(self):
        if not self.alive:
            return None
        try:
            self.root.after(self.POLL_MS, self._poll)
        except Exception:
            # 主窗口已销毁：托盘也该结束了
            self.alive = False
        return None

    def _poll(self):
        if not self.alive:
            return None
        while True:
            try:
                action = self.actions.get_nowait()
            except queue.Empty:
                break
            if action == ACTION_SHOW and self.on_show is not None:
                self.on_show()
            elif action == ACTION_EXIT and self.on_exit is not None:
                self.on_exit()
        self._schedule_poll()
        return None
