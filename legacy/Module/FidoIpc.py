# -*- coding: utf-8 -*-
"""命名管道 IPC 服务：接收 Fido/fido-go.exe 转发的 CTAP2 请求。

协议（与 ``Fido/src/fido-go/ipc.go`` 一一对应）::

    请求：[Magic(4B,BE)='PK11'][Cmd(4B,BE)][Len(4B,BE)][JSON]
    响应：[Magic(4B,BE)='PK11'][Cmd(4B,BE)][Len(4B,BE)][JSON]

JSON 载荷：

* ``{"cbor_req": "<base64>"}`` —— MakeCredential / GetAssertion 的 CBOR 参数；
* ``{"card_uuid": "...", "pin": "..."}`` —— 登录（0x0304）；
* 响应统一为 ``{"rv": N, "data": {...}}``。**``rv`` 直接使用 CTAP2 状态码**
  （0 成功、0x36 需要 PIN、0x2E 无凭据……），这样 NO_CREDENTIALS 之类的
  语义不会被压缩成笼统的 0x7F。

为什么用命名管道而不是 HTTP：fido-go 在浏览器发起 WebAuthn 请求的**同步路径**上，
HTTP 往返＋端口占用都不合适；管道是参考项目验证过的形态，且只监听本机。
"""

import ctypes
import json
import os
import struct
import threading
import time

# ---- Win32 常量 ----------------------------------------------------------- #
PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
PIPE_UNLIMITED_INSTANCES = 255

ERROR_ACCESS_DENIED = 5
ERROR_INVALID_HANDLE = 6
ERROR_PIPE_CONNECTED = 535
ERROR_BROKEN_PIPE = 109
ERROR_PIPE_NOT_CONNECTED = 233
ERROR_NO_DATA = 232
ERROR_SEM_TIMEOUT = 121
ERROR_OPERATION_ABORTED = 995

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

IPC_MAGIC = 0x504B3131          # "PK11"
IPC_HEADER_SIZE = 12
IPC_MAX_PAYLOAD = 4 * 1024 * 1024

# 命令码
CMD_GET_INFO = 0x0300
CMD_MAKE_CREDENTIAL = 0x0301
CMD_GET_ASSERTION = 0x0302
CMD_CANCEL = 0x0303
CMD_LOGIN = 0x0304          # 内置 UV 模式：fido-go 弹框后调它登录
CMD_CLIENT_PIN = 0x0305     # clientPIN 模式：平台把 0x06 命令原样转发过来

DEFAULT_PIPE_NAME = r"\\.\pipe\TPMFIDO"


class IpcError(Exception):
    """IPC 层的可预期错误。"""


_KERNEL32 = None


def _kernel32():
    """kernel32 句柄（带完整函数原型；不声明 argtypes 时宽字符参数会被当成窄字符）。"""
    global _KERNEL32
    if _KERNEL32 is not None:
        return _KERNEL32
    kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    kernel32.CreateNamedPipeW.restype = ctypes.c_void_p
    kernel32.CreateNamedPipeW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel32.ConnectNamedPipe.restype = ctypes.c_int
    kernel32.ConnectNamedPipe.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.DisconnectNamedPipe.restype = ctypes.c_int
    kernel32.DisconnectNamedPipe.argtypes = [ctypes.c_void_p]
    kernel32.ReadFile.restype = ctypes.c_int
    kernel32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                                  ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p]
    kernel32.WriteFile.restype = ctypes.c_int
    kernel32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                                   ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.FlushFileBuffers.restype = ctypes.c_int
    kernel32.FlushFileBuffers.argtypes = [ctypes.c_void_p]
    kernel32.WaitNamedPipeW.restype = ctypes.c_int
    kernel32.WaitNamedPipeW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                     ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                     ctypes.c_void_p]
    _KERNEL32 = kernel32
    return kernel32


def read_exact(handle, length):
    """从管道句柄精确读 ``length`` 字节；对端已断开返回 ``None``。"""
    kernel32 = _kernel32()
    buffer = ctypes.create_string_buffer(length)
    read = ctypes.c_ulong(0)
    got = 0
    while got < length:
        ok = kernel32.ReadFile(handle, ctypes.byref(buffer, got),
                               length - got, ctypes.byref(read), None)
        if not ok:
            code = ctypes.get_last_error()
            if code in (ERROR_BROKEN_PIPE, ERROR_PIPE_NOT_CONNECTED,
                        ERROR_NO_DATA, ERROR_OPERATION_ABORTED):
                return None
            raise IpcError("读取管道失败（错误码 %d）" % code)
        if read.value == 0:
            return None
        got += read.value
    return buffer.raw[:length]


def write_all(handle, data):
    """把 ``data`` 全部写进管道句柄。"""
    kernel32 = _kernel32()
    offset = 0
    while offset < len(data):
        chunk = data[offset:]
        written = ctypes.c_ulong(0)
        ok = kernel32.WriteFile(handle, chunk, len(chunk),
                               ctypes.byref(written), None)
        if not ok:
            raise IpcError("写入管道失败（错误码 %d）" % ctypes.get_last_error())
        if written.value == 0:
            raise IpcError("写入管道返回 0 字节")
        offset += written.value


class PipeServer:
    """最小的 Windows 命名管道服务端（字节模式，多实例，逐连接一个线程）。"""

    def __init__(self, handler, name=DEFAULT_PIPE_NAME, logger=None):
        """
        :param handler: ``handler(cmd:int, payload:bytes) -> dict``
        :param name: 管道全名（``\\\\.\\pipe\\xxx``）
        """
        self.handler = handler
        self.name = name
        self.logger = logger or (lambda text: None)
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()       # 串行化 CTAP 处理（会话状态是共享的）
        self._handles = []
        self._handles_lock = threading.Lock()
        self._external = False              # 管道由本进程外的另一个实例提供
        self.error = ""

    # ---- 生命周期 -------------------------------------------------------- #
    @property
    def running(self):
        if self._external:
            return self._probe()
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def start(self):
        """启动管道服务；管道已由其它实例提供时也算成功（``owned`` 为 False）。"""
        if self.running:
            return True
        self._stop.clear()
        self._external = False
        self.error = ""
        self._thread = threading.Thread(target=self._serve, name="FidoPipeServer",
                                        daemon=True)
        self._thread.start()
        # 等第一个实例真正建出来，避免调用方立刻连接时管道还不存在
        for _ in range(50):
            if self.running and self._probe():
                return True
            if self._external:
                return self._probe()
            if self.error:                  # 建不了管道（权限/参数），别干等
                return False
            time.sleep(0.02)
        if not self.error:
            self.error = "管道未能启动"
        return self.running

    @property
    def owned(self):
        """管道是否由本实例创建（False = 另一个进程已经在提供服务）。"""
        return not self._external

    def stop(self, timeout=3.0):
        """停止服务。

        唤醒阻塞在 ``ConnectNamedPipe`` 的服务线程只能靠**一次客户端连接**：
        实测在另一个线程里 ``CloseHandle`` 那个正挂着 ConnectNamedPipe 的句柄，
        CloseHandle 本身会一起卡住（两个线程互相等待）。所以这里连一次、
        让 ConnectNamedPipe 返回，服务线程看到 ``_stop`` 后自己关句柄并退出。
        """
        self._stop.set()
        kernel32 = _kernel32()
        thread = self._thread
        self._thread = None
        deadline = time.time() + 1.5
        while thread is not None and thread.is_alive() and time.time() < deadline:
            client = None
            try:
                client = self._connect_once(timeout=0.2)
            except Exception:
                pass
            if client:
                try:
                    kernel32.CloseHandle(client)
                except Exception:
                    pass
            thread.join(0.2)
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        self._external = False
        return True

    # ---- 内部 ------------------------------------------------------------ #
    def _probe(self):
        try:
            client = self._connect_once(timeout=0.2)
        except Exception:
            return False
        try:
            _kernel32().CloseHandle(client)
        except Exception:
            pass
        return True

    def _connect_once(self, timeout=0.5):
        """用一个客户端句柄试连（用于探测/唤醒）。

        必须先 ``WaitNamedPipe`` 且检查返回值：管道实例全被占用时，
        ``CreateFile(PIPE_WAIT)`` 会**无限期阻塞**（这正是之前 stop 卡死的原因）。
        """
        kernel32 = _kernel32()
        kernel32.CreateFileW.restype = ctypes.c_void_p
        if not kernel32.WaitNamedPipeW(self.name, max(1, int(timeout * 1000))):
            raise IpcError("没有可用的管道实例（错误码 %d）" % ctypes.get_last_error())
        handle = kernel32.CreateFileW(self.name, 0x80000000 | 0x40000000,
                                      0, None, 3, 0, None)
        if handle == INVALID_HANDLE_VALUE or handle is None:
            raise IpcError("连接管道失败（错误码 %d）" % ctypes.get_last_error())
        return handle

    def _register(self, handle):
        with self._handles_lock:
            self._handles.append(handle)

    def _unregister(self, handle):
        with self._handles_lock:
            if handle in self._handles:
                self._handles.remove(handle)
        try:
            _kernel32().CloseHandle(handle)
        except Exception:
            pass

    def _serve(self):
        kernel32 = _kernel32()
        kernel32.CreateNamedPipeW.restype = ctypes.c_void_p
        kernel32.ConnectNamedPipe.restype = ctypes.c_int
        # 注意：PIPE_REJECT_REMOTE_CLIENTS 属于 dwPipeMode（不是 dwOpenMode），
        # 放错位置会得到 ERROR_INVALID_PARAMETER(87)。
        flags = PIPE_ACCESS_DUPLEX
        mode = (PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT
                | PIPE_REJECT_REMOTE_CLIENTS)
        first = True
        while not self._stop.is_set():
            # 第一个实例带 FILE_FLAG_FIRST_PIPE_INSTANCE：如果已经有别的进程
            # （例如 --fido-daemon 常驻的那个）在同一名字上服务，
            # CreateNamedPipe 会失败，我们据此让出，避免两个进程各管一半会话。
            handle = kernel32.CreateNamedPipeW(
                self.name, flags | (FILE_FLAG_FIRST_PIPE_INSTANCE if first else 0),
                mode, PIPE_UNLIMITED_INSTANCES,
                IPC_MAX_PAYLOAD, IPC_MAX_PAYLOAD, 0, None)
            if handle == INVALID_HANDLE_VALUE or handle is None:
                code = ctypes.get_last_error()
                # ERROR_ACCESS_DENIED 有两种可能：①已有别的进程在服务（我们可
                # 以当客户端）；②管道存在但安全描述符不允许本进程访问（典型是
                # 管理员进程建的服务 + 普通用户进程来连）。只有能连上才算 ①。
                if first and code == ERROR_ACCESS_DENIED and self._probe():
                    self._external = True
                    self.logger("命名管道已由另一个进程提供，本实例只做客户端")
                    return
                hint = ""
                if code == ERROR_ACCESS_DENIED:
                    hint = ("（权限不足：该管道由管理员进程创建，本进程没有访问权限）")
                self.error = "创建命名管道失败（错误码 %d）%s" % (code, hint)
                self.logger(self.error)
                return
            first = False
            self._register(handle)
            connected = kernel32.ConnectNamedPipe(handle, None)
            if not connected:
                code = ctypes.get_last_error()
                if code != ERROR_PIPE_CONNECTED:
                    self._unregister(handle)
                    if self._stop.is_set():
                        return
                    self.logger("等待管道连接失败（错误码 %d）" % code)
                    continue
            if self._stop.is_set():
                self._unregister(handle)
                return
            threading.Thread(target=self._handle_connection, args=(handle,),
                             name="FidoPipeConn", daemon=True).start()

    def _handle_connection(self, handle):
        try:
            with self._lock:
                self._process(handle)
        except Exception as err:                      # 单次请求失败不影响服务
            self.logger("处理 FIDO 请求失败: %s" % err)
        finally:
            try:
                _kernel32().FlushFileBuffers(handle)
                _kernel32().DisconnectNamedPipe(handle)
            except Exception:
                pass
            self._unregister(handle)

    def _process(self, handle):
        header = read_exact(handle, IPC_HEADER_SIZE)
        if header is None:
            return
        magic, cmd, length = struct.unpack(">III", header[:12])
        if magic != IPC_MAGIC:
            self.logger("收到非法请求（魔数 0x%08X）" % magic)
            return
        if length > IPC_MAX_PAYLOAD:
            self.logger("请求体过大: %d 字节" % length)
            return
        payload = b""
        if length:
            payload = read_exact(handle, length)
            if payload is None:
                return
        response = self.handler(cmd, payload)
        body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        frame = struct.pack(">III", IPC_MAGIC, cmd, len(body)) + body
        write_all(handle, frame)
        # fido-go 每次请求只读一帧，写完即可断开（由调用方 DisconnectNamedPipe）


def call_pipe(cmd, payload_json, name=DEFAULT_PIPE_NAME, timeout=5.0):
    """客户端侧调用（自检脚本 / 排障用）。"""
    kernel32 = _kernel32()
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.WaitNamedPipeW(name, int(timeout * 1000))
    handle = kernel32.CreateFileW(name, 0x80000000 | 0x40000000, 0, None, 3, 0, None)
    if handle == INVALID_HANDLE_VALUE or handle is None:
        raise IpcError("连接管道失败: %s" % name)
    try:
        body = json.dumps(payload_json or {}).encode("utf-8")
        frame = struct.pack(">III", IPC_MAGIC, cmd, len(body)) + body
        write_all(handle, frame)
        header = read_exact(handle, IPC_HEADER_SIZE)
        if header is None:
            raise IpcError("服务端没有响应")
        _magic, _cmd, length = struct.unpack(">III", header[:12])
        data = read_exact(handle, length) if length else b""
        return json.loads((data or b"{}").decode("utf-8"))
    finally:
        kernel32.CloseHandle(handle)


if __name__ == "__main__":
    print("进程 PID: %d，python: %s" % (os.getpid(), os.sys.version.split()[0]))
    print("默认管道: %s" % DEFAULT_PIPE_NAME)
