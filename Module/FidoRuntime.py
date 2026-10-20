# -*- coding: utf-8 -*-
"""FIDO2 运行环境：USB/IP 虚拟总线驱动 + 虚拟设备进程（Fido/fido-go.exe）。

分工
----
* **驱动**（``usbip_vhci_ude`` / ``usbip_vhci``，随程序分发的 ``Fido/usbip/``）：
  内核态的 USB/IP 虚拟主机控制器，只需要装一次。它把「一个 USB 设备」暴露给
  Windows，WebAuthn 通过 HID Usage Page ``0xF1D0`` 认出这是 FIDO 认证器。
* **设备端进程**（``Fido/fido-go.exe``）：用户态程序，模拟 USB HID 设备，
  把 CTAP2 报文经命名管道转给本进程的 Python 后端（:mod:`Module.FidoIpc`）。

安装/启动顺序（本模块负责）::

    装驱动 → 建 ROOT\\vhci_ude 设备节点 → 启动 fido-go.exe
          → fido-go 自己 usbip attach → 设备出现在设备管理器
          → 后端管道就绪 → 浏览器可以用 passkey

排障要点
--------
USB/IP 的驱动是**内核态**驱动，Windows 10/11 在开启 Secure Boot 时要求驱动包
带微软签名；本项目分发的是第三方签名的包，若安装失败（错误码 0xE0000247 /
"无法验证此文件的数字签名"），需要：
  * 把发布者证书装进「受信任的根证书颁发机构 + 受信任的发布者」，或
  * 在测试机上临时开启测试签名（``bcdedit /set testsigning on`` + 重启）。
:func:`signature_report` 会把这三项状态一起报出来，供界面提示与反馈定位。
"""

import ctypes
import os
import re
import socket
import subprocess
import time
import uuid

from Module import Paths

# 运行目录（随程序分发）
RUNTIME_DIR = Paths.resource("Fido")
FIDO_EXE = os.path.join(RUNTIME_DIR, "fido-go.exe")
USBIP_DIR = os.path.join(RUNTIME_DIR, "usbip")
USBIP_EXE = os.path.join(USBIP_DIR, "usbip.exe")

# USB/IP 服务端口（与 Fido/src/fido-go/main.go 的 usbipPort 一致）
USBIP_PORT = 3240
# 与 fido-go 约定的命名管道
PIPE_NAME = r"\\.\pipe\TPMFIDO"
# 虚拟设备在 USB/IP 里的 busid（virtual-fido 固定 2-2）
DEVICE_BUSID = "2-2"
# 设备挂上后 Windows 侧出现的设备节点
VIRTUAL_USB_KEY = r"USB\VID_0000&PID_0000"

# 设备类：USB 控制器（{36FC9E60-C465-11CF-8056-444553540000}，与 INF 的 ClassGuid 一致）
DEVICE_CLASS_USB = "{36FC9E60-C465-11CF-8056-444553540000}"

# 候选驱动（新版 ude 优先，失败再退老的 vhci）
# hwid/instance 必须与各自 INF 里的 DeviceID 对应（见 Fido/usbip/*.inf）：
#   usbip_vhci_ude.inf -> ROOT\VHCI_ude  -> 实例 ROOT\VHCI_UDE\0000
#   usbip_vhci.inf     -> USBIPWIN\vhci  -> 实例 USBIPWIN\VHCI\0000
DRIVERS = (
    {"name": "usbip_vhci_ude", "inf": "usbip_vhci_ude.inf",
     "hwid": "ROOT\\VHCI_ude", "instance": "ROOT\\VHCI_UDE\\0000",
     "class": DEVICE_CLASS_USB},
    {"name": "usbip_vhci", "inf": "usbip_vhci.inf",
     "hwid": "USBIPWIN\\vhci", "instance": "USBIPWIN\\VHCI\\0000",
     "class": DEVICE_CLASS_USB},
)

LOG_NAME = "fido.log"

# 驱动安装失败的常见错误码 → 处理建议（界面直接展示）
ERROR_HINTS = {
    0xE0000247: "驱动包签名不被系统接受。请在「系统设置 - FIDO2」里查看签名诊断，"
                "按提示安装发布者证书，或在测试机上临时开启测试签名后重试。",
    0xE000024B: "驱动包签名不被系统接受（同上）。",
    0xE0000235: "驱动包缺少有效的目录文件（.cat）。请确认 Fido/usbip 目录完整。",
    5: "需要管理员权限：请以管理员身份运行本程序。",
    0x20: "驱动文件被占用，请先停止 FIDO2 服务并重试。",
}

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def log_dir():
    folder = Paths.data_path("logs")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        pass
    return folder


def log_path():
    return os.path.join(log_dir(), LOG_NAME)


# --------------------------------------------------------------------------- #
# 环境自检
# --------------------------------------------------------------------------- #
def arch_supported():
    """FIDO2 只提供 x64 版设备端程序与 x64 内核驱动。

    ARM64 上无法加载 x64 内核驱动，32 位系统也装不了（INF 只有 NTAMD64）。
    """
    import platform
    machine = (platform.machine() or "").upper()
    if "ARM" in machine:
        return False, "FIDO2/通行密钥暂不支持 ARM64（虚拟总线驱动只有 x64 版）"
    try:
        from Module import WinPlatform
        if not WinPlatform.is_64bit_os():
            return False, "FIDO2/通行密钥需要 64 位 Windows"
    except Exception:
        pass
    return True, ""


def runtime_ready():
    """随包的设备端程序与 usbip 工具是否齐全。"""
    ok, text = arch_supported()
    if not ok:
        return False, text
    missing = []
    for path, label in ((FIDO_EXE, "fido-go.exe"),
                        (USBIP_EXE, os.path.join("usbip", "usbip.exe")),
                        (os.path.join(USBIP_DIR, "attacher.exe"), "usbip\\attacher.exe")):
        if not os.path.isfile(path):
            missing.append(label)
    if missing:
        return False, "缺少运行文件: %s（请重新安装本程序）" % "、".join(missing)
    return True, "运行文件齐全"


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _devnode_state(instance_id):
    """设备节点状态：``started`` / ``present`` / ``missing`` / ``unknown``。"""
    try:
        cfgmgr32 = ctypes.WinDLL("cfgmgr32.dll")
    except Exception as err:
        return "unknown", "cfgmgr32 不可用: %s" % err
    node = ctypes.c_uint32(0)
    if cfgmgr32.CM_Locate_DevNodeW(ctypes.byref(node), instance_id, 0) != 0:
        return "missing", "设备树里没有 %s" % instance_id
    status = ctypes.c_uint32(0)
    problem = ctypes.c_uint32(0)
    if cfgmgr32.CM_Get_DevNode_Status(ctypes.byref(status), ctypes.byref(problem),
                                      node, 0) != 0:
        return "present", "设备节点存在，状态查询失败"
    if status.value & 0x00000008:            # DN_STARTED
        return "started", "设备已启动"
    return "present", "设备存在但未启动（问题码 %d）" % problem.value


def driver_state():
    """返回 ``(state, text, driver)``，state ∈ ok / missing / stopped。"""
    for driver in DRIVERS:
        state, text = _devnode_state(driver["instance"])
        if state == "started":
            return "ok", "USB/IP 虚拟总线已就绪（%s）" % driver["name"], driver
        if state in ("present", "unknown"):
            return "stopped", "驱动已安装但设备未启动：%s" % text, driver
    return "missing", "未安装 USB/IP 虚拟总线驱动（虚拟 FIDO 设备无法出现）", None


def device_attached():
    """虚拟设备是否已经挂到 Windows 上（以 ``usbip port`` 的挂载列表为准）。

    不用注册表里的 ``USB\\VID_0000&PID_0000`` 判断：Windows 会给很多"未知设备"
    建同名键，用它判断必然误报。
    """
    if not os.path.isfile(USBIP_EXE):
        return False
    try:
        result = subprocess.run([USBIP_EXE, "port"], cwd=USBIP_DIR,
                                capture_output=True, timeout=10,
                                creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    text = (result.stdout or b"").decode("mbcs", "replace") + \
           (result.stderr or b"").decode("mbcs", "replace")
    return DEVICE_BUSID in text


def port_open(port=USBIP_PORT, timeout=0.4):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# 进程管理（fido-go.exe）
# --------------------------------------------------------------------------- #
def _iter_processes(name="fido-go.exe"):
    """用 Toolhelp32 枚举同名进程，返回 [(pid, exe 路径)]。"""
    kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_uint32),
                    ("cntUsage", ctypes.c_uint32),
                    ("th32ProcessID", ctypes.c_uint32),
                    ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", ctypes.c_uint32),
                    ("cntThreads", ctypes.c_uint32),
                    ("th32ParentProcessID", ctypes.c_uint32),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_uint32),
                    ("szExeFile", ctypes.c_wchar * 260)]

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)   # TH32CS_SNAPPROCESS
    if snapshot in (None, ctypes.c_void_p(-1).value):
        return []
    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
    found = []
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if str(entry.szExeFile).lower() == name.lower():
                found.append((int(entry.th32ProcessID), ""))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def service_pid():
    """正在运行的设备端进程 PID（没有则 0）。"""
    for pid, _path in _iter_processes():
        return pid
    return 0


def service_running():
    return service_pid() != 0


def _kill_pid(pid):
    if not pid:
        return False
    kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    process = kernel32.OpenProcess(0x0001, False, pid)      # PROCESS_TERMINATE
    if not process:
        return False
    try:
        return bool(kernel32.TerminateProcess(process, 1))
    finally:
        kernel32.CloseHandle(process)


def start_service(pin_strings=None, verbose=False, wait=8.0):
    """启动 Fido/fido-go.exe；返回 ``(ok, text)``。

    ``pin_strings`` 是 PIN 弹窗文案（按当前界面语言），键：title/card/pin/ok/
    cancel/wrong。
    """
    ok, text = runtime_ready()
    if not ok:
        return False, text
    pid = service_pid()
    if pid and port_open():
        return True, "FIDO2 设备服务已在运行（PID %d）" % pid
    if pid:
        # 有进程但没监听端口（上次异常退出/版本升级残留），先清掉再起
        print("发现残留的 FIDO2 设备端进程（PID %d）未监听端口，先结束它" % pid)
        _kill_pid(pid)
        for _ in range(20):
            if not service_pid():
                break
            time.sleep(0.1)
        detach_device()
    if port_open():
        return False, ("端口 %d 已被其它程序占用（不是本程序的设备服务），"
                       "请先结束占用该端口的进程" % USBIP_PORT)
    strings = pin_strings or {}
    command = [FIDO_EXE,
               "-pipe", PIPE_NAME,
               "-log", log_path(),
               "-usbip-dir", USBIP_DIR,
               "-pin-title", strings.get("title", "TPM 智能卡"),
               "-pin-card", strings.get("card", "选择智能卡(&C):"),
               "-pin-label", strings.get("pin", "PIN 码(&P):"),
               "-pin-ok", strings.get("ok", "确定"),
               "-pin-cancel", strings.get("cancel", "取消"),
               "-pin-wrong", strings.get("wrong", "PIN 不正确，请重试")]
    if verbose:
        command.append("-v")
    try:
        subprocess.Popen(command, cwd=RUNTIME_DIR, close_fds=True,
                         creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
    except OSError as err:
        return False, "启动设备服务失败: %s" % err
    deadline = time.time() + wait
    while time.time() < deadline:
        if port_open() and service_pid():
            # 端口就绪后再等设备挂上（fido-go 里 attach 有 400ms 延迟）
            for _ in range(20):
                if device_attached():
                    return True, "FIDO2 设备已就绪"
                time.sleep(0.25)
            return True, "FIDO2 设备服务已启动，但虚拟设备还没挂上（可稍后刷新状态）"
        time.sleep(0.2)
    if service_pid():
        return False, "设备服务已启动但没有监听 %d 端口，请查看日志: %s" % (USBIP_PORT, log_path())
    return False, "设备服务启动失败，请查看日志: %s" % log_path()


def stop_service():
    """停止设备端进程并断开虚拟设备；返回 ``(ok, text)``。"""
    pid = service_pid()
    detached = detach_device()
    if not pid:
        return True, ("已断开虚拟设备" if detached else "设备服务未在运行")
    _kill_pid(pid)
    for _ in range(20):
        if not service_pid():
            break
        time.sleep(0.1)
    if service_pid():
        return False, "无法结束设备服务进程（PID %d），请手动结束" % pid
    return True, "已停止设备服务"


def detach_device():
    if not os.path.isfile(USBIP_EXE):
        return False
    try:
        subprocess.run([USBIP_EXE, "detach", "-p", "0"], cwd=USBIP_DIR,
                       capture_output=True, timeout=10,
                       creationflags=CREATE_NO_WINDOW)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def attach_device():
    if not os.path.isfile(USBIP_EXE):
        return False, "找不到 usbip.exe"
    try:
        result = subprocess.run([USBIP_EXE, "attach", "-r", "127.0.0.1",
                                 "-b", DEVICE_BUSID],
                                cwd=USBIP_DIR, capture_output=True, timeout=15,
                                creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as err:
        return False, "挂载虚拟设备失败: %s" % err
    text = (result.stdout or b"").decode("mbcs", "replace") + \
           (result.stderr or b"").decode("mbcs", "replace")
    if result.returncode != 0:
        return False, "挂载虚拟设备失败: %s" % (text.strip() or result.returncode)
    return True, "虚拟设备已挂载"


# --------------------------------------------------------------------------- #
# 驱动安装 / 卸载
# --------------------------------------------------------------------------- #
def _run(command, timeout=180, cwd=None):
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout,
                                cwd=cwd, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as err:
        return 1, str(err)
    text = (result.stdout or b"").decode("mbcs", "replace") + \
           (result.stderr or b"").decode("mbcs", "replace")
    return result.returncode, text.strip()


def _install_device_node(inf_path, hwid, instance_id, class_guid):
    """用 SetupAPI/newdev 注册根枚举设备（等价 ``devcon install``）。

    步骤与 ``Module/TPMBackup.register_card_device`` 一致（那条路已在换系统
    还原场景实测过）：建空设备信息 → 指定实例 ID → 写 HardwareID →
    DIF_REGISTERDEVICE → UpdateDriverForPlugAndPlayDevices 装驱动。
    """
    try:
        setupapi = ctypes.WinDLL("setupapi.dll", use_last_error=True)
        newdev = ctypes.WinDLL("newdev.dll", use_last_error=True)
    except Exception as err:
        return False, "setupapi/newdev 不可用: %s" % err

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                    ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    class _SP_DEVINFO_DATA(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint32), ("ClassGuid", _GUID),
                    ("DevInst", ctypes.c_uint32), ("Reserved", ctypes.c_void_p)]

    def guid_of(text):
        value = uuid.UUID(str(text).strip("{}"))
        guid = _GUID()
        guid.Data1 = value.time_low
        guid.Data2 = value.time_mid
        guid.Data3 = value.time_hi_version
        for index, byte in enumerate(value.bytes[8:]):
            guid.Data4[index] = byte
        return guid

    def wide_multi(text):
        """REG_MULTI_SZ 用的字节串（以两个 NUL 结尾），返回 (缓冲, 长度)。"""
        raw = (text + "\0\0").encode("utf-16-le")
        return ctypes.create_string_buffer(raw, len(raw)), len(raw)

    # 声明原型：这些 API 的参数里既有指针又有 DWORD，不声明 argtypes 时
    # 64 位下容易把句柄/指针截断。
    setupapi.SetupDiCreateDeviceInfoList.restype = ctypes.c_void_p
    setupapi.SetupDiCreateDeviceInfoList.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    setupapi.SetupDiCreateDeviceInfoW.restype = ctypes.c_int
    setupapi.SetupDiCreateDeviceInfoW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_wchar_p,
        ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_SP_DEVINFO_DATA)]
    setupapi.SetupDiSetDeviceRegistryPropertyW.restype = ctypes.c_int
    setupapi.SetupDiSetDeviceRegistryPropertyW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_SP_DEVINFO_DATA), ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_uint32]
    setupapi.SetupDiCallClassInstaller.restype = ctypes.c_int
    setupapi.SetupDiCallClassInstaller.argtypes = [
        ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(_SP_DEVINFO_DATA)]
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    newdev.UpdateDriverForPlugAndPlayDevicesW.restype = ctypes.c_int
    newdev.UpdateDriverForPlugAndPlayDevicesW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_int)]

    class_id = guid_of(class_guid)
    info = setupapi.SetupDiCreateDeviceInfoList(ctypes.byref(class_id), None)
    if not info or info == ctypes.c_void_p(-1).value:
        return False, "SetupDiCreateDeviceInfoList 失败（错误码 %d）" % ctypes.get_last_error()
    handle = ctypes.c_void_p(info)
    device = _SP_DEVINFO_DATA()
    device.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
    try:
        if not setupapi.SetupDiCreateDeviceInfoW(
                handle, instance_id, ctypes.byref(class_id), None, None, 0,
                ctypes.byref(device)):
            return False, "创建设备信息失败（错误码 %d）" % ctypes.get_last_error()
        buffer, length = wide_multi(hwid)
        if not setupapi.SetupDiSetDeviceRegistryPropertyW(
                handle, ctypes.byref(device), 0x00000001,     # SPDRP_HARDWAREID
                ctypes.cast(buffer, ctypes.c_void_p), length):
            return False, "写 HardwareID 失败（错误码 %d）" % ctypes.get_last_error()
        if not setupapi.SetupDiCallClassInstaller(
                0x00000019,                                   # DIF_REGISTERDEVICE
                handle, ctypes.byref(device)):
            return False, "注册设备失败（错误码 %d）" % ctypes.get_last_error()
        reboot = ctypes.c_int(0)
        if not newdev.UpdateDriverForPlugAndPlayDevicesW(
                None, hwid, inf_path, 0x00000001, ctypes.byref(reboot)):
            error = ctypes.get_last_error()
            hint = ERROR_HINTS.get(error, "")
            return False, "安装驱动失败（错误码 %d / 0x%X）%s%s" % (
                error, error & 0xFFFFFFFF, "：" if hint else "", hint)
        return True, "设备节点已创建%s" % ("（需要重启系统）" if reboot.value else "")
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(handle)


def install_driver():
    """安装 USB/IP 虚拟总线驱动；返回 ``(ok, 日志行列表)``。

    优先用 ``usbip.exe install``：驱动包自带安装流程（找同目录的 inf/sys/cat、
    自己创建 ROOT 枚举设备节点、处理签名与重复安装），比我们手写 SetupAPI 可靠。
    它失败时才退到 ``pnputil + SetupAPI``（devcon install 那套）。
    """
    log = []
    if not is_admin():
        return False, ["需要管理员权限：请以管理员身份运行本程序后再安装驱动"]
    ok, text = runtime_ready()
    if not ok:
        return False, [text]

    state, text, _driver = driver_state()
    if state == "ok":
        return True, ["驱动已安装，无需重复安装：%s" % text]

    def settled():
        """等设备节点起来（驱动刚装完时可能需要一两秒）。"""
        for _ in range(15):
            current = driver_state()
            if current[0] == "ok":
                log.append(current[1])
                return True
            time.sleep(0.4)
        return False

    # ---- 方式一：驱动包自带的安装命令 ------------------------------------- #
    if os.path.isfile(USBIP_EXE):
        for flags, label in ((["-u"], "ude"), (["-w"], "wdm")):
            log.append("调用 usbip install %s -f（%s 版虚拟总线）" % (flags[0], label))
            code, output = _run([USBIP_EXE, "install"] + flags + ["-f"],
                                timeout=300, cwd=USBIP_DIR)
            if output:
                log.extend(output.splitlines()[:8])
            log.append("usbip install 返回 %s" % code)
            if settled():
                return True, log

    # ---- 方式二：pnputil + SetupAPI（devcon install 等价实现）-------------- #
    for candidate in DRIVERS:
        inf_path = os.path.join(USBIP_DIR, candidate["inf"])
        if not os.path.isfile(inf_path):
            log.append("缺少驱动包：%s" % inf_path)
            continue
        log.append("正在安装驱动包：%s" % candidate["name"])
        code, output = _run(["pnputil", "/add-driver", inf_path, "/install"])
        if output:
            log.extend(output.splitlines()[:6])
        if code not in (0, 3010):
            log.append("pnputil 返回 %s（继续尝试直接创建/更新设备节点）" % code)
        if settled():
            return True, log
        ok, text = _install_device_node(inf_path, candidate["hwid"],
                                        candidate["instance"], candidate["class"])
        log.append(text)
        if not ok:
            continue
        if settled():
            return True, log
        log.append("设备节点已创建但未启动，尝试重启设备节点")
        _run(["pnputil", "/restart-device", candidate["instance"]], timeout=60)
        if settled():
            return True, log

    log.append("驱动安装未成功。请查看「签名诊断」结果，再决定是安装发布者证书还是临时开启测试签名。")
    return False, log


def uninstall_driver():
    """卸载虚拟总线驱动（不会删除程序文件）。"""
    log = []
    if not is_admin():
        return False, ["需要管理员权限"]
    if os.path.isfile(USBIP_EXE):
        code, output = _run([USBIP_EXE, "uninstall"], timeout=180, cwd=USBIP_DIR)
        log.append("usbip uninstall 返回 %s" % code)
        if output:
            log.extend(output.splitlines()[:6])
    for candidate in DRIVERS:
        instance = candidate["instance"]
        if _devnode_state(instance)[0] != "missing":
            code, output = _run(["pnputil", "/remove-device", instance], timeout=120)
            log.append("移除设备 %s（返回 %s）" % (instance, code))
            if output:
                log.extend(output.splitlines()[:4])
    for name in ("usbip_vhci_ude.inf", "usbip_vhci.inf"):
        code, output = _run(["pnputil", "/delete-driver", name, "/uninstall", "/force"],
                            timeout=120)
        log.append("删除驱动包 %s（返回 %s）" % (name, code))
    log.append("如仍提示驱动被占用，重启后再试。")
    return True, log


def _trust_state(path):
    """用 WinVerifyTrust 判断「本机是否信任这个文件的签名」。

    不用 ``Get-AuthenticodeSignature``：在非交互/受限制的 PowerShell 环境里
    该 cmdlet 所属模块可能加载失败（实测在 Python 子进程里会报
    “找不到命令 … 但无法加载该模块”），而 WinVerifyTrust 是系统原生 API。
    """
    if not os.path.isfile(path):
        return "文件缺失"
    try:
        wintrust = ctypes.WinDLL("wintrust.dll", use_last_error=True)
    except Exception as err:
        return "无法检查（%s）" % err

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                    ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    class _WINTRUST_FILE_INFO(ctypes.Structure):
        _fields_ = [("cbStruct", ctypes.c_uint32),
                    ("pcwszFilePath", ctypes.c_wchar_p),
                    ("hFile", ctypes.c_void_p),
                    ("pgKnownSubject", ctypes.c_void_p)]

    class _WINTRUST_DATA(ctypes.Structure):
        _fields_ = [("cbStruct", ctypes.c_uint32),
                    ("pPolicyCallbackData", ctypes.c_void_p),
                    ("pSIPClientData", ctypes.c_void_p),
                    ("dwUIChoice", ctypes.c_uint32),
                    ("fdwRevocationChecks", ctypes.c_uint32),
                    ("dwUnionChoice", ctypes.c_uint32),
                    ("pFile", ctypes.POINTER(_WINTRUST_FILE_INFO)),
                    ("dwStateAction", ctypes.c_uint32),
                    ("hWVTStateData", ctypes.c_void_p),
                    ("pwszURLReference", ctypes.c_wchar_p),
                    ("dwProvFlags", ctypes.c_uint32),
                    ("dwUIContext", ctypes.c_uint32)]

    action = _GUID()
    action.Data1 = 0x00AAC56B
    action.Data2 = 0xCD44
    action.Data3 = 0x11D0
    for index, byte in enumerate(b"\x8c\xc2\x00\xc0\x4f\xc2\x95\xee"):
        action.Data4[index] = byte

    file_info = _WINTRUST_FILE_INFO()
    file_info.cbStruct = ctypes.sizeof(_WINTRUST_FILE_INFO)
    file_info.pcwszFilePath = path
    data = _WINTRUST_DATA()
    data.cbStruct = ctypes.sizeof(_WINTRUST_DATA)
    data.dwUIChoice = 2            # WTD_UI_NONE
    data.fdwRevocationChecks = 0   # WTD_REVOKE_NONE（离线时不因吊销检查失败）
    data.dwUnionChoice = 1         # WTD_CHOICE_FILE
    data.pFile = ctypes.pointer(file_info)
    data.dwStateAction = 1         # WTD_STATEACTION_VERIFY
    data.dwProvFlags = 0x00001000  # WTD_CACHE_ONLY_URL_RETRIEVAL

    code = wintrust.WinVerifyTrust(ctypes.c_void_p(-1), ctypes.byref(action),
                                  ctypes.byref(data))
    # 清理校验状态（否则会泄漏状态数据）
    data.dwStateAction = 2         # WTD_STATEACTION_CLOSE
    wintrust.WinVerifyTrust(ctypes.c_void_p(-1), ctypes.byref(action),
                            ctypes.byref(data))

    if code == 0:
        return "签名受信任"
    hints = {
        0x800B0100: "未签名（缺少签名或目录文件）",
        0x800B0109: "签名不受信任（根证书不在受信任列表）",
        0x800B010A: "证书链无法构建（缺少中间证书）",
        0x800B010C: "证书已被吊销",
        0x800B0110: "证书用途不匹配",
        0x80096010: "签名摘要不匹配（文件被修改）",
        0x800B0101: "证书已过期",
    }
    return hints.get(code & 0xFFFFFFFF, "签名校验失败（0x%08X）" % (code & 0xFFFFFFFF))


def signature_report():
    """驱动签名状况诊断（界面展示 / 反馈用）。"""
    report = {"testsigning": "未知", "files": {}}
    code, output = _run(["bcdedit", "/enum", "{current}"], timeout=30)
    if code == 0:
        # bcdedit 的标识符（testsigning）与取值（Yes/No）本身是英文，不随系统语言变化
        match = re.search(r"testsigning\s+(\w+)", output, re.IGNORECASE)
        report["testsigning"] = (match.group(1).capitalize() if match else "Off")
    for name in ("usbip_vhci_ude.sys", "usbip_vhci_ude.cat",
                 "usbip_vhci.sys", "usbip_vhci.cat"):
        report["files"][name] = _trust_state(os.path.join(USBIP_DIR, name))
    return report


# --------------------------------------------------------------------------- #
# 汇总状态（界面用）
# --------------------------------------------------------------------------- #
def status():
    """一次性收集安装/运行状态。"""
    ready, ready_text = runtime_ready()
    state, state_text, _driver = driver_state()
    pid = service_pid()
    return {
        "runtime": ready,
        "runtime_text": ready_text,
        "driver": state,
        "driver_text": state_text,
        "pid": pid,
        "process": bool(pid),
        "port": port_open(),
        "device": device_attached(),
        "admin": is_admin(),
        "log": log_path(),
        "runtime_dir": RUNTIME_DIR,
    }


def clear_old_log(max_bytes=2 * 1024 * 1024):
    """日志超过阈值时轮转一次（fido-go 以追加方式写）。"""
    path = log_path()
    try:
        if os.path.getsize(path) > max_bytes:
            os.replace(path, path + ".old")
    except OSError:
        pass
    return path


if __name__ == "__main__":
    import json
    print(json.dumps(status(), ensure_ascii=False, indent=2))
    print(json.dumps(signature_report(), ensure_ascii=False, indent=2))
