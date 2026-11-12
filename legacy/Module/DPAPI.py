# -*- coding: utf-8 -*-
"""DPAPI 加解密（含借用 SYSTEM / LOCAL SERVICE 令牌）。

为什么需要它
============
虚拟智能卡 store 里的 ``keymaps`` / ``pinmaps`` / ``pinpolicy`` / ``blobs\\*``
**不是明文**，而是 DPAPI blob::

    01 00 00 00 D0 8C 9D DF 01 15 D1 11 8C 7A 00 C0 4F C2 97 EB   <- blob 头
    ... master key GUID ...   dwFlags=0（用户作用域）
    0E 00 00 00 "T P M V S C"                                       <- 描述 "TPMVSC"

（只有卡的文件系统 ``fs\\*`` 是明文。）

DPAPI 的主密钥保存在**创建这份数据的那台系统**的账户存储里
（``...\\Microsoft\\Protect\\<SID>[\\User]\\<主密钥 GUID>``）。换系统后目标机没有这把
主密钥，驱动就读不出卡上的密钥与 PIN 映射，表现为：**读卡器在、卡片"可用"，但
``certutil -scinfo`` 报「找不到储存的密钥集」，证书与私钥都列不出来**。

解决办法不是搬主密钥（主密钥跨 OS 安装通常不可用；若是机器级主密钥还会连带解密该机
其它受保护数据，泄露面不可接受），而是：

* **备份时（源机）**：在这些 blob 上调用 ``CryptUnprotectData``，把**明文**收进备份包；
* **还原时（目标机）**：调用 ``CryptProtectData`` 重新封装后写回 store，
  数据即绑定到目标机自己的 DPAPI 主密钥。

实测（Win10 19044，同机换系统的两台克隆 VM）
==========================================
* 管理员进程**无权**解密 SYSTEM 用户作用域的数据（``err=0x8009000B``）；
* 在进程内**借用一次 SYSTEM 令牌**后即可正常加解密（``SetThreadToken``）；
* 计划任务以 ``NT AUTHORITY\\LocalService`` 运行会失败（``Last Result=-196608``），
  因此不依赖计划任务，直接在进程内借令牌。

因此本模块对外只暴露 ``protect`` / ``unprotect`` / ``blob_info`` / ``master_key_owner``：
调用方不需要关心令牌细节。
"""

from __future__ import annotations

import ctypes
import os
import re
import uuid

# DPAPI blob 头：dwVersion(4) + guidProvider(16) + dwMasterKeyVersion(4) + guidMasterKey(16)
BLOB_HEADER_SIZE = 40
# DPAPI 默认 provider GUID（每个 CryptProtectData 输出都以它开头）
PROVIDER_GUID = uuid.UUID("{DF9D8CD0-1501-11D1-8C7A-00C04FC297EB}")
# PROTECT 时的默认描述：驱动用的就是它（blob 里可读出来）
DEFAULT_DESCRIPTION = "TPMVSC"
# CRYPTPROTECT_LOCAL_MACHINE：机器作用域（否则是调用者账户的用户作用域）
FLAG_MACHINE = 0x4
FLAG_UI_FORBIDDEN = 0x1

# 令牌相关常量
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_DUPLICATE = 0x0002
TOKEN_IMPERSONATE = 0x0004
SecurityImpersonation = 2      # SECURITY_IMPERSONATION_LEVEL
TokenImpersonation = 2         # TOKEN_TYPE
SECURITY_IMPERSONATION = SecurityImpersonation
TOKEN_IMPERSONATION = TokenImpersonation
TokenUser = 1                  # TOKEN_INFORMATION_CLASS

# 常见服务账户：驱动（UMDF 宿主）与相关组件可能以其中某个身份运行。
SYSTEM_SID = "S-1-5-18"
ACCOUNT_SIDS = {
    "SYSTEM": SYSTEM_SID,
    "LOCAL SERVICE": "S-1-5-19",
    "NETWORK SERVICE": "S-1-5-20",
}
# 备份时按这个顺序尝试解密（先本进程身份，再借服务账户令牌）
DEFAULT_ACCOUNTS = (None, "SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE")

# 借用令牌时优先挑这些进程：长期存在的系统服务进程，令牌干净、可复制。
#
# **不要按 pid 顺序扫**：实测（Win10 19044）低 pid 的 `Secure System` / `Registry` /
# `smss.exe` 都是**受保护进程**，`OpenProcessToken` 直接返回 `ACCESS_DENIED(5)`；
# 而真正好用的服务进程 pid 往往很大（`services.exe`=736、`winlogon.exe`=692、
# `lsass.exe`=760），只扫 1..399 会一个都借不到 —— 现象就是备份时 SYSTEM 身份
# 解密报 `err=5`。名单里没有的进程作为兜底候选（仍会做 SID 校验）。
ACCOUNT_PROCESS_NAMES = {
    "SYSTEM": ("services.exe", "winlogon.exe", "lsass.exe", "wininit.exe", "svchost.exe"),
    "LOCAL SERVICE": ("svchost.exe", "searchindexer.exe"),
    "NETWORK SERVICE": ("svchost.exe", "msdtc.exe"),
}
# 枚举进程 pid 时的上限（够用即可，避免极端情况下分配过大）
MAX_PROCESS_COUNT = 8192

# 各种受保护数据的主密钥存放位置（还原 / 诊断时用）
PROTECT_DIRS = (
    os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "ServiceProfiles",
                 "LocalService", "AppData", "Roaming", "Microsoft", "Protect"),
    os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "ServiceProfiles",
                 "NetworkService", "AppData", "Roaming", "Microsoft", "Protect"),
    os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32",
                 "Microsoft", "Protect"),
)

_TOKEN_CACHE = {}


def available():
    """当前是否具备 DPAPI 能力（Windows + crypt32）。

    :return: ``(ok, text)``
    """
    if os.name != "nt":
        return False, "非 Windows 环境，DPAPI 不可用"
    try:
        ctypes.WinDLL("crypt32.dll")
    except OSError as err:
        return False, "crypt32.dll 不可用: %s" % err
    return True, "可用"


def blob_info(data):
    """判断一段数据是不是 DPAPI blob，是则返回头部信息。

    :return: ``{"master_key": "…", "master_key_version": n, "flags": n}``；不是 blob
        或数据太短时返回 ``None``
    """
    data = bytes(data or b"")
    if len(data) < BLOB_HEADER_SIZE:
        return None
    if int.from_bytes(data[0:4], "little") != 1:
        return None
    if uuid.UUID(bytes_le=data[4:20]) != PROVIDER_GUID:
        return None
    return {
        "master_key": str(uuid.UUID(bytes_le=data[24:40])),
        "master_key_version": int.from_bytes(data[20:24], "little"),
        "flags": int.from_bytes(data[40:44], "little"),
    }


def blob_description(data):
    """读出 blob 里的描述（``DwDescriptionLen`` 以字节计，UTF-16LE）。"""
    data = bytes(data or b"")
    if len(data) < BLOB_HEADER_SIZE + 4:
        return ""
    size = int.from_bytes(data[44:48], "little")
    if size <= 0 or size > 512 or len(data) < BLOB_HEADER_SIZE + 4 + size:
        return ""
    try:
        return data[48:48 + size].decode("utf-16-le").rstrip("\0")
    except UnicodeDecodeError:
        return ""


# --------------------------------------------------------------------------- #
# 令牌借用
# --------------------------------------------------------------------------- #
class _Structs(object):
    """集中构造 ctypes 结构体与函数原型（只构造一次）。"""

    def __init__(self):
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.c_void_p)]

        class SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32)]

        class TOKEN_USER(ctypes.Structure):
            _fields_ = [("User", SID_AND_ATTRIBUTES)]

        self.DATA_BLOB = DATA_BLOB
        self.TOKEN_USER = TOKEN_USER
        self.SID_AND_ATTRIBUTES = SID_AND_ATTRIBUTES

        crypt32 = ctypes.WinDLL("crypt32.dll", use_last_error=True)
        crypt32.CryptProtectData.restype = ctypes.c_bool
        crypt32.CryptUnprotectData.restype = ctypes.c_bool
        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.LocalFree.restype = ctypes.c_void_p
        advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)
        advapi32.OpenProcessToken.restype = ctypes.c_bool
        advapi32.DuplicateTokenEx.restype = ctypes.c_bool
        advapi32.SetThreadToken.restype = ctypes.c_bool
        advapi32.RevertToSelf.restype = ctypes.c_bool
        advapi32.GetTokenInformation.restype = ctypes.c_bool
        advapi32.ConvertSidToStringSidW.restype = ctypes.c_bool

        # 句柄一律声明成 ``c_void_p`` / ``POINTER(c_void_p)``。Windows 的句柄是
        # **64 位**：只设 restype、不声明 argtypes 时，ctypes 会把拿回来的 Python int
        # 当 C ``int``（32 位）转换，句柄值超过 2^31 就抛
        # ``OverflowError: int too long to convert``（SetupDi 那边已经踩过一次，
        # 见 devlog §12.6，这里把同类坑一次补齐）。
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        advapi32.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                             ctypes.POINTER(ctypes.c_void_p)]
        advapi32.DuplicateTokenEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                              ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                              ctypes.POINTER(ctypes.c_void_p)]
        advapi32.SetThreadToken.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        advapi32.GetTokenInformation.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                 ctypes.c_void_p, ctypes.c_uint32,
                                                 ctypes.POINTER(ctypes.c_uint32)]
        advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                                    ctypes.POINTER(ctypes.c_wchar_p)]
        advapi32.OpenThreadToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                             ctypes.POINTER(ctypes.c_void_p)]
        advapi32.OpenThreadToken.restype = ctypes.c_bool
        kernel32.GetCurrentThread.restype = ctypes.c_void_p
        # 进程枚举：K32EnumProcesses（Win7+ 在 kernel32）优先，psapi.EnumProcesses 兜底
        enum_args = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32,
                     ctypes.POINTER(ctypes.c_uint32)]
        kernel32.K32EnumProcesses.argtypes = enum_args
        kernel32.K32EnumProcesses.restype = ctypes.c_bool
        psapi = ctypes.WinDLL("psapi.dll", use_last_error=True)
        psapi.EnumProcesses.argtypes = enum_args
        psapi.EnumProcesses.restype = ctypes.c_bool
        kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                                        ctypes.c_wchar_p,
                                                        ctypes.POINTER(ctypes.c_uint32)]
        kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
        self.crypt32 = crypt32
        self.kernel32 = kernel32
        self.advapi32 = advapi32
        self.psapi = psapi

    def blob_of(self, data):
        """bytes → DATA_BLOB（调用方负责 free）。"""
        buffer = ctypes.create_string_buffer(bytes(data), len(data))
        blob = self.DATA_BLOB()
        blob.cbData = len(data)
        blob.pbData = ctypes.cast(buffer, ctypes.c_void_p)
        return blob, buffer

    def blob_bytes(self, blob):
        """DATA_BLOB → bytes。"""
        if not blob.pbData or not blob.cbData:
            return b""
        return ctypes.string_at(blob.pbData, blob.cbData)


_STRUCTS = None


def _structs():
    global _STRUCTS
    if _STRUCTS is None:
        _STRUCTS = _Structs()
    return _STRUCTS


def _sid_of_token(token):
    """取令牌的用户 SID 字符串；失败返回空串。"""
    api = _structs()
    size = ctypes.c_uint32(0)
    api.advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
    if not size.value:
        return ""
    buffer = ctypes.create_string_buffer(size.value)
    if not api.advapi32.GetTokenInformation(token, 1, buffer, size.value, ctypes.byref(size)):
        return ""
    user = ctypes.cast(buffer, ctypes.POINTER(api.TOKEN_USER)).contents
    text = ctypes.c_wchar_p()
    if not api.advapi32.ConvertSidToStringSidW(user.User.Sid, ctypes.byref(text)):
        return ""
    try:
        return str(text.value or "")
    finally:
        api.kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def _process_ids():
    """枚举当前所有进程 pid（比逐个 pid 去试快得多）。"""
    api = _structs()
    buffer = (ctypes.c_uint32 * MAX_PROCESS_COUNT)()
    used = ctypes.c_uint32(0)
    try:
        ok = api.kernel32.K32EnumProcesses(buffer, ctypes.sizeof(buffer), ctypes.byref(used))
    except AttributeError:
        ok = api.psapi.EnumProcesses(buffer, ctypes.sizeof(buffer), ctypes.byref(used))
    if not ok:
        return []
    return [buffer[index] for index in range(used.value // 4)]


def _process_name(handle):
    """取进程镜像文件名（小写、不含路径）；失败返回空串。"""
    api = _structs()
    size = ctypes.c_uint32(260)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not api.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
        return ""
    return os.path.basename(buffer.value).lower()


def _token_candidates(account):
    """按「优先名单 → 其它进程」的顺序产出该账户可用的令牌副本 ``(句柄, 进程名)``。

    候选进程会先按 ``ACCOUNT_PROCESS_NAMES`` 排到前面，再按 pid 兜底；每个候选都要求
    令牌用户 SID 匹配 ``account``。这样既避开受保护进程（取令牌必 ACCESS_DENIED），
    也不受 pid 大小影响。
    """
    api = _structs()
    key = str(account or "").upper()
    want = ACCOUNT_SIDS.get(key)
    if not want:
        return
    preferred = tuple(ACCOUNT_PROCESS_NAMES.get(key, ()))
    ranked = []
    for pid in _process_ids():
        if pid <= 4:                     # 0=Idle、4=内核 System：没有可用的用户态令牌
            continue
        handle = api.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            continue
        try:
            name = _process_name(handle)
        finally:
            api.kernel32.CloseHandle(handle)
        # 没有镜像路径的进程（Registry / Memory Compression / Secure System 这类
        # 内核态或内存态进程）跳过：实测借它们的令牌后 DPAPI 会 ACCESS_DENIED。
        if not name:
            continue
        rank = preferred.index(name) if name in preferred else len(preferred)
        ranked.append((rank, pid, name))
    ranked.sort(key=lambda item: (item[0], item[1]))
    for _, pid, name in ranked:
        handle = api.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            continue
        try:
            token = ctypes.c_void_p()
            if not api.advapi32.OpenProcessToken(handle, TOKEN_QUERY | TOKEN_DUPLICATE,
                                                 ctypes.byref(token)):
                continue
            if not token.value:
                continue
            try:
                if _sid_of_token(token) != want:
                    continue
                dup = ctypes.c_void_p()
                if not api.advapi32.DuplicateTokenEx(token, TOKEN_QUERY | TOKEN_IMPERSONATE,
                                                     None, SECURITY_IMPERSONATION,
                                                     TOKEN_IMPERSONATION, ctypes.byref(dup)):
                    continue
                if not dup.value:
                    continue
                yield dup.value, name
            finally:
                api.kernel32.CloseHandle(token)
        finally:
            api.kernel32.CloseHandle(handle)


def _dpapi_probe():
    """在**当前线程身份下**做一次 DPAPI 往返，确认这个身份真的能做 DPAPI。

    只看令牌 SID 不够：实测借用 `Registry`（内存态进程、没有镜像路径）的令牌时，
    SID 确实是 SYSTEM，但用它调 DPAPI 仍然 `ACCESS_DENIED(5)` —— 所以借到令牌后必须
    **实打实试一次**，失败就换下一个候选进程。
    """
    api = _structs()
    sample = b"dpapi-probe"
    holder = ctypes.create_string_buffer(sample, len(sample))
    source = api.DATA_BLOB()
    source.cbData = len(sample)
    source.pbData = ctypes.cast(holder, ctypes.c_void_p)
    out = api.DATA_BLOB()
    if not api.crypt32.CryptProtectData(ctypes.byref(source), "probe", None, None, None, 0,
                                        ctypes.byref(out)):
        return False
    try:
        blob = api.blob_bytes(out)
    finally:
        api.kernel32.LocalFree(out.pbData)
    if not blob:
        return False
    holder2 = ctypes.create_string_buffer(blob, len(blob))
    back = api.DATA_BLOB()
    back.cbData = len(blob)
    back.pbData = ctypes.cast(holder2, ctypes.c_void_p)
    out2 = api.DATA_BLOB()
    if not api.crypt32.CryptUnprotectData(ctypes.byref(back), None, None, None, None, 0,
                                          ctypes.byref(out2)):
        return False
    try:
        return api.blob_bytes(out2) == sample
    finally:
        api.kernel32.LocalFree(out2.pbData)


def _thread_sid():
    """当前线程令牌的用户 SID（借用令牌后复核用）；失败返回空串。"""
    api = _structs()
    token = ctypes.c_void_p()
    if not api.advapi32.OpenThreadToken(api.kernel32.GetCurrentThread(), TOKEN_QUERY, 0,
                                        ctypes.byref(token)):
        return ""
    try:
        return _sid_of_token(token)
    finally:
        api.kernel32.CloseHandle(token)


def impersonate(account):
    """在**当前线程**上借用 ``account`` 的令牌（SYSTEM / LOCAL SERVICE / NETWORK SERVICE）。

    :return: ``(ok, text)``
    """
    if os.name != "nt":
        return False, "非 Windows 环境"
    api = _structs()
    account = str(account or "")
    want = ACCOUNT_SIDS.get(account.upper(), "")
    for token, name in _token_candidates(account):
        if not api.advapi32.SetThreadToken(None, ctypes.c_void_p(token)):
            api.kernel32.CloseHandle(ctypes.c_void_p(token))
            continue
        # 借用后复核两点：① 线程身份确实是目标账户；② 这个身份**真的能做 DPAPI**。
        # 只查 SID 不够——内存态进程（Registry 之类）的令牌 SID 也是 SYSTEM，
        # 但用它调 DPAPI 会 ACCESS_DENIED。
        if (want and _thread_sid() != want) or not _dpapi_probe():
            api.advapi32.RevertToSelf()
            api.kernel32.CloseHandle(ctypes.c_void_p(token))
            continue
        _TOKEN_CACHE["current"] = ctypes.c_void_p(token)
        return True, "已借用 %s 令牌（来自 %s）" % (account, name or "进程")
    return False, "没能借用到 %s 的令牌（未找到可用进程或权限不足）" % account


def revert():
    """结束令牌借用，恢复本进程身份。"""
    if os.name != "nt":
        return
    api = _structs()
    api.advapi32.RevertToSelf()
    token = _TOKEN_CACHE.pop("current", None)
    if token:
        api.kernel32.CloseHandle(token)


def current_user():
    """当前线程的用户名（借用令牌后应为被借用账户）。"""
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# 加解密
# --------------------------------------------------------------------------- #
def _crypt(data, protect, description, flags, account=None):
    """在（可选的）借用令牌下做一次加/解密。

    :return: ``(结果字节, 说明)``
    """
    api = _structs()
    borrowed = False
    text = ""
    if account:
        ok, tip = impersonate(account)
        if not ok:
            return None, tip
        borrowed = True
        text = tip
    try:
        holder = ctypes.create_string_buffer(bytes(data), len(data))
        source = api.DATA_BLOB()
        source.cbData = len(data)
        source.pbData = ctypes.cast(holder, ctypes.c_void_p)
        out = api.DATA_BLOB()
        if protect:
            ok = api.crypt32.CryptProtectData(ctypes.byref(source), description, None, None,
                                              None, flags, ctypes.byref(out))
        else:
            ok = api.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None,
                                                None, flags, ctypes.byref(out))
        if not ok:
            code = ctypes.get_last_error()
            return None, "%s 失败（err=%s 0x%X）" % ("加密" if protect else "解密", code,
                                                     code if code >= 0 else code + (1 << 32))
        try:
            return api.blob_bytes(out), text
        finally:
            api.kernel32.LocalFree(out.pbData)
    finally:
        if borrowed:
            revert()


def protect(data, account=None, description=DEFAULT_DESCRIPTION, flags=0, verify=True):
    """重新封装成 DPAPI blob。

    :param account: 用哪个账户身份加密（``None`` = 当前进程身份）。**必须与将来解密它
        的账户一致**：驱动以哪个身份运行，就用哪个身份加密（还原时按备份记录的账户）。
    :param description: 描述字符串，驱动用的是 ``"TPMVSC"``
    :param flags: ``0`` = 用户作用域（驱动用这个）；``0x4`` = 机器作用域
    :param verify: 是否立刻回验（解密一次确认可读）
    :return: ``(blob 字节或 None, 说明)``
    """
    blob, text = _crypt(data, True, description, flags, account)
    if blob is None:
        return None, text
    tip = "已加密（%s，%d 字节）" % (account or "当前身份", len(blob))
    if verify:
        back, note = _crypt(blob, False, description, flags, account)
        if back is None:
            return None, "%s；但回验失败，不可用：%s" % (tip, note)
        if bytes(back) != bytes(data):
            return None, "%s；但回验内容不一致，不可用" % tip
        tip += "，回验通过"
    return blob, tip


def unprotect(data, accounts=None, flags=None, expect=None):
    """解开 DPAPI blob：依次尝试若干账户身份与作用域，第一个成功的胜出。

    :param accounts: 账户身份序列，默认 ``(None, SYSTEM, LOCAL SERVICE, NETWORK SERVICE)``
    :param flags: 作用域序列，默认按 blob 头记录的 flags、用户作用域、机器作用域依次试
    :param expect: 校验解出的明文描述/内容（可传原始描述，仅作日志）
    :return: ``(明文或 None, 说明)``
    """
    data = bytes(data or b"")
    info = blob_info(data)
    if info is None:
        return None, "不是 DPAPI blob，无需解密"
    accounts = tuple(DEFAULT_ACCOUNTS if accounts is None else accounts)
    if flags is None:
        flags = (info["flags"], 0, FLAG_MACHINE)
    tried = []
    for account in accounts:
        for scope in flags:
            plain, note = _crypt(data, False, "", scope, account)
            if plain is not None:
                tip = "已解密（%s%s，%d 字节）" % (
                    account or "当前身份",
                    "，机器作用域" if scope & FLAG_MACHINE else "，用户作用域",
                    len(plain))
                if note:
                    tip = note + "，" + tip
                return plain, tip
            tried.append("%s/%s: %s" % (account or "当前身份", scope, note))
    return None, "解密失败（主密钥不在本机或账户不对）: " + "；".join(tried[:4])


def master_key_owner(master_key):
    """查某个主密钥属于哪个账户（用在备份时记录"该用谁的令牌还原"）。

    :return: ``(账户名, 文件路径)``；找不到返回 ``("", "")``
    """
    want = str(master_key or "").lower()
    if not want:
        return "", ""
    for root in PROTECT_DIRS:
        if not os.path.isdir(root):
            continue
        for current, _, files in os.walk(root):
            for name in files:
                if name.lower() != want:
                    continue
                parts = current.replace("/", "\\").split("\\")
                for part in reversed(parts):
                    for account, sid in ACCOUNT_SIDS.items():
                        if part.upper() == sid.upper():
                            return account, os.path.join(current, name)
                # 用户级主密钥位于 <SID>\User\ 之下，父目录即账户 SID
                return "", os.path.join(current, name)
    return "", ""
