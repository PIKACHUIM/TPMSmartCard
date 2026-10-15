# -*- coding: utf-8 -*-
"""TPM 虚拟智能卡：备份（备份文件 + 注册表）与还原。

虚拟 TPM 卡的数据落盘位置（研究结论）
=====================================
1. 卡片数据目录（权威依据：Windows 升级迁移清单
   ``%SystemRoot%\\System32\\migwiz\\replacementmanifests\\tpmvsc-repl.man``，
   组件名 ``Microsoft-Windows-SmartCard-TPM-VCard-Module``，scope=Upgrade）::

       %SystemRoot%\\ServiceProfiles\\LocalService\\AppData\\Local\\Microsoft\\Windows\\SmartCard\\Tpm\\

   * 该目录由 ``tpmvsc.dll``（TPM 卡模拟的卡片操作实现）读写，内部含 ``blobs\\``
     子目录（字符串直接见于 ``tpmvsc.dll``），保存卡片文件系统、PIN 映射 / PIN 策略、
     密钥映射以及经 TPM 封装后的密钥 blob。
   * 目录位于 LocalService 服务账户的配置文件下，默认 ACL 只允许 SYSTEM 与管理员访问；
     因此备份 / 还原**必须以管理员权限运行**（打包配置 BuildPackage.py 中
     ``uac_admin=True``，正常安装后即满足）。

2. 注册表（每张卡一个根枚举设备节点）::

       HKLM\\SYSTEM\\CurrentControlSet\\Enum\\ROOT\\SMARTCARDREADER\\<0000|0001|...>

   * ``FriendlyName`` 即创建时填写的卡片名称；
   * 固定值 ``HardwareID=VirtualSmartcardReader\\reader``、``Service=WUDFRd``、
     ``ClassGUID={50dd5230-ba8a-11d1-bf5d-0000f805f530}``；
   * 子键 ``Device Parameters``（含 ``WUDF\\DriverList=SmartcardSimulator``）
     与 ``Properties``，后者 ACL 受保护，普通权限读不到。
   * 读卡器注册项 ``HKLM\\SOFTWARE\\Microsoft\\Cryptography\\Calais\\Readers\\
     Microsoft Virtual Smart Card <n>`` 由 ``tpmvsc.inf`` 的 AddReg 生成，
     不含卡片数据，仅作可选备份。

3. TPM 侧（无法备份）：卡片私钥由 TPM 保护，明文永不离开 TPM；磁盘上只有 TPM 封装
   后的 blob，而 TPM 自身的密钥层级（SRK / AIK）不在文件系统内。
   **因此备份只在「同一台电脑 + 同一 TPM（未 clear）」上可以还原**，
   换机或清除 TPM 后无法恢复——这与 ``tpmvscmgr destroy`` 官方的
   “虚拟智能卡一旦删除，将无法恢复”一致。

``tpmvscmgr`` 本身不提供任何备份 / 还原命令（仅有 ``create`` / ``destroy``），
本模块即在上述文件与注册表位置之上实现等价能力。

备份文件格式（``.tsb``）
========================
备份是**一个 zip 压缩包**，只改后缀为 ``.tsb``（便于在资源管理器里双击识别），
内部结构::

    tpmvsc-backup.json      清单：卡片信息、文件 sha256、注册表项、TPM 指纹、注意事项
    store-index.txt         备份时的数据目录清单（诊断用）
    files/<Tpm 数据目录内相对结构>    卡片数据文件
    registry/<SMARTCARDREADER-xxxx>.reg  设备节点注册表导出
    registry/<CalaisReader-xxxx>.reg     读卡器注册表导出

还原时只需选中这个 ``.tsb`` 文件。

还原后的设备重新枚举（重要）
============================
``reg import`` 只是把 ``Enum\\ROOT\\SMARTCARDREADER\\<uid>`` 写回了磁盘，
PnP 的**内存设备树**里并没有这个节点，因此卡片不会自己出现。还原流程写完
注册表后会再调用 ``CM_Reenumerate_DevNode``（等价于设备管理器里的
「扫描检测硬件改动」）让 PnP 重新枚举 ROOT 总线上的设备并启动驱动，从而无需
重启即可看到卡片；若系统拒绝重新枚举，则只能重启系统后才可见。

「卡片没有出现」的五种原因（还原日志里逐条给出结论）
====================================================
1. 注册表没真正写进去（``reg import`` 失败只在日志里可见，界面原先看不到）；
2. PnP 没把设备节点建出来——``reg import`` 返回成功**不等于**设备存在，
   用 ``devnode_state()``（``CM_Locate_DevNode``）作为硬判据；且实测
   ``CM_Reenumerate_DevNode`` / ``pnputil /scan-devices`` 都建不出只存在于
   注册表里的 ROOT 设备，必须用 ``register_card_device()``（SetupDi 注册）；
3. **设备属性（卡片身份）没写回**：``Enum\\...\\<实例>\\Properties`` 里的
   ``{2BEED4A8-...}`` 存着卡片名与**卡片 GUID**、``{2065F23D-...}`` 存着 store
   路径与模块路径。该子键 ACL 受保护（``reg export`` 读不到），注册表备份带不回来。
   实测缺了它设备节点照样启动、store 也绑定成功，但驱动不建设备接口、
   不向 PC/SC 发布读卡器 —— 表现为"还原成功但卡片没出现"；
4. TPM 密钥索引（PCPKSP 下的 ``*.PCPKEY``）没写回：换系统 / 重装后驱动找不到
   卡片私钥对应的 TPM 对象；
5. 卡片数据与 TPM 密钥不匹配（换机 / 清过 TPM 时私钥无法恢复）。

注意 ``CM_Set_DevNode_Property`` 写字符串属性时缓冲区长度**必须含结尾 NUL**，
否则会被判 ``CR_INVALID_DATA``（写不进去）。

还原日志同时落盘到 ``%APPDATA%\\TPMSmartCard\\logs\\restore-<时间戳>.log``，
并在界面弹窗里给出路径与逐条结论，用户反馈问题时可直接提供现场信息。
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import time
import uuid
import zipfile

from Module import Paths
from Module.Version import VERSION

# 备份包格式版本（后续结构变化时递增，还原时校验）
BACKUP_FORMAT = 1
# 备份清单文件名
MANIFEST_NAME = "tpmvsc-backup.json"
# 备份包内子目录
FILES_DIR = "files"
REGISTRY_DIR = "registry"
# 备份文件后缀（zip 压缩包，注册为智能卡备份文件）
BACKUP_SUFFIX = ".tsb"

# tpmvsc.dll 自己的设备属性集；PID=2 是卡片 store 目录路径（含 store GUID）。
# 这是「设备实例 ↔ store 目录」的唯一绑定，位于 Enum 下受 ACL 保护的 Properties
# 子键里（管理员用 reg export 也读不到），但可以通过 PnP 属性接口读到。
VSC_DEVPROP_SET = "{2065F23D-D989-4F8F-B769-4A3D779FAF0B}"
VSC_DEVPROP_STORE_PID = 2
# 卡片私钥所在的 TPM 密钥存储提供程序（KSP）
_PCP_NAME = "Microsoft Platform Crypto Provider"
# DEVPROP_TYPE_STRING
DEVPROP_TYPE_STRING = 0x00000012
# CONFIGRET: 缓冲区太小（先问长度）
CR_BUFFER_SMALL = 0x1A

SYSTEM_ROOT = os.environ.get("SystemRoot") or r"C:\Windows"

# 卡片数据根目录（SmartCard）与卡片数据目录（Tpm）
VSC_ROOT_DIR = os.path.join(SYSTEM_ROOT, "ServiceProfiles", "LocalService", "AppData",
                            "Local", "Microsoft", "Windows", "SmartCard")
VSC_STORE_DIR = os.path.join(VSC_ROOT_DIR, "Tpm")

# 卡片设备节点注册表位置
VSC_ENUM_KEY = r"HKLM\SYSTEM\CurrentControlSet\Enum\ROOT\SMARTCARDREADER"
# 读卡器注册表位置（tpmvsc.inf AddReg 生成）
VSC_READER_KEY = r"HKLM\SOFTWARE\Microsoft\Cryptography\Calais\Readers"

# TPM 卡所在服务
CARD_SERVICE = "SCardSvr"

# 重新创建设备节点所需参数：智能卡读卡器设备类 + 虚拟读卡器硬件 ID + 驱动 INF。
# ROOT\SMARTCARDREADER 下的设备是 SetupDi 注册出来的（devcon install 的那套），
# 光把 Enum 注册表项写回磁盘并不会让 PnP 创建它。
VSC_READER_CLASS_GUID = "{50DD5230-BA8A-11D1-BF5D-0000F805F530}"
VSC_READER_HARDWARE_ID = "VirtualSmartcardReader\\reader"
VSC_READER_INF = os.path.join(SYSTEM_ROOT, "inf", "tpmvsc.inf")

# setupapi / newdev 常量
DIF_REGISTERDEVICE = 0x00000019
SPDRP_HARDWAREID = 0x00000001
SPDRP_FRIENDLYNAME = 0x0000000C
INSTALLFLAG_FORCE = 0x00000001

# TPM 密钥索引（PCP 密钥元数据，``*.PCPKEY``）的候选目录。
#
# 卡片私钥是 TPM 里的持久对象；而「KSP 密钥名 → TPM 对象」的映射**在操作系统侧**，
# 既不在 store 目录里，也不在设备注册表里。少了这部分，换系统 / 重装后即使设备
# 节点被建出来、store 也写回去了，驱动仍然打不开卡片密钥 —— 读卡器根本不会被
# 发布到 PC/SC（``SCardListReaders`` 返回 SCARD_E_NO_READERS_AVAILABLE），
# 系统还会顺手把 ``Calais\\Readers`` 里的读卡器条目清空。
#
# 实测（Win10 19044，同一台 VM 换系统还原）：卡片 ``keymaps`` 里记着 KSP 密钥名
# （固定为 ``TPMVSC``），但本机 LocalService 的 PCPKSP 目录根本不存在，卡片起不来。
VSC_PCP_DIRS = (
    os.path.join(SYSTEM_ROOT, "ServiceProfiles", "LocalService", "AppData", "Local",
                 "Microsoft", "Crypto", "PCPKSP"),
    os.path.join(SYSTEM_ROOT, "System32", "config", "systemprofile", "AppData", "Local",
                 "Microsoft", "Crypto", "PCPKSP"),
    os.path.join(os.environ.get("ProgramData") or r"C:\ProgramData",
                 "Microsoft", "Crypto", "PCPKSP"),
)
# 备份包内 TPM 密钥索引的目录名（``pcp/<索引>/<原相对路径>``）
PCP_DIR = "pcp"

# 厂商设备属性集（存在 ``Enum\...\<实例>\Properties`` 里，ACL 受保护，``reg export``
# 读不到，但 PnP 属性接口可以读写）：
#   * ``tpmvsc.dll`` 的集合：store 目录路径、tpmvsc.dll 路径
#   * ``smartcardsimulator.dll``（读卡器 UMDF 驱动）的集合：驱动路径、**卡片名**、
#     标志位、**卡片 GUID**
# 实测（Win10 19044 换系统还原）：设备节点已启动、store 也已绑定，但缺了
# ``{2BEED4A8-...}`` 这组卡片身份属性时，驱动不会向 PC/SC 发布读卡器
# （``SCardListReaders`` 里看不到这张卡）；补齐后设备接口与读卡器立刻出现。
# 卡片 GUID 就是驱动用来找 TPM 密钥的标识，所以这份属性必须跟着备份走。
VSC_PROP_SET_TPMVSC = "{2065F23D-D989-4F8F-B769-4A3D779FAF0B}"
VSC_PROP_SET_SIMULATOR = "{2BEED4A8-5721-4C27-AF9A-82EC36181B4D}"
# DEVPROPKEY 占用 20 字节（16 字节 GUID + 4 字节 PID）
DEVPROPKEY_SIZE = 20
# DEVPROP_TYPE_STRING / DEVPROP_TYPE_STRING_LIST
DEVPROP_TYPE_STRING_LIST = 0x00002012

# reg.exe 输出里提取 FriendlyName
_FRIENDLY_RE = re.compile(r"^\s*FriendlyName\s+REG_SZ\s+(.*?)\s*$", re.MULTILINE)
# 文件名非法字符
_BAD_NAME_RE = re.compile(r'[\\/:*?"<>|]')


class BackupError(Exception):
    """备份 / 还原中的可预期错误，界面直接把 message 展示给用户。"""


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def is_admin():
    """当前进程是否以管理员权限运行（读取卡片数据目录的前提）。"""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as err:
        print("IsAdmin Check Error:", err)
        return False


# 取本机 TPM 身份的 PowerShell：EK 公钥的 SHA-256（十六进制）+ 厂商证书信息
_TPM_QUERY = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$ek=Get-TpmEndorsementKeyInfo -HashAlgorithm Sha256;"
    "if($ek -and $ek.PublicKey -and $ek.PublicKey.RawData -and $ek.PublicKey.RawData.Length -gt 0){"
    "$sha=[System.Security.Cryptography.SHA256]::Create().ComputeHash([byte[]]$ek.PublicKey.RawData);"
    "Write-Output ('EK=' + [System.BitConverter]::ToString($sha).Replace('-',''))}"
    "elseif($ek -and $ek.PublicKeyHash -and $ek.PublicKeyHash.Length -gt 0){"
    "Write-Output ('EK=' + [System.BitConverter]::ToString([byte[]]$ek.PublicKeyHash).Replace('-',''))};"
    "if($ek -and $ek.ManufacturerCertificates -and $ek.ManufacturerCertificates.Count -gt 0){"
    "$c=$ek.ManufacturerCertificates[0];"
    "Write-Output ('INFO=' + $c.Subject + ' | ' + $c.Thumbprint)}"
)


def tpm_identity():
    """取本机 TPM 身份：``{"ek": EK 公钥 SHA-256, "info": 厂商/型号信息}``。

    用途：判断一份备份是不是本机产生的。换机、清除 TPM（Clear-Tpm）、更换 TPM
    固件都会让指纹变化，而 VSC 的密钥只认原来那颗 TPM。
    读取指纹需要管理员权限，失败时两个字段为空字符串（不影响备份 / 还原本身）。
    """
    identity = {"ek": "", "info": ""}
    code, output = run_command(["powershell", "-NoProfile", "-NonInteractive",
                                "-Command", _TPM_QUERY], timeout=120)
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("EK="):
            identity["ek"] = line[3:].strip()
        elif line.startswith("INFO="):
            identity["info"] = line[5:].strip()
    if not identity["ek"]:
        print("读取 TPM 指纹失败（需管理员权限）: %s"
              % (output.splitlines()[0] if output else code))
    return identity


def check_tpm(manifest):
    """校验备份里记录的 TPM 指纹与本机是否一致。

    :return: ``(state, text)``，state 取值：

        ``match``    指纹一致（同一台机器的同一颗 TPM）
        ``mismatch`` 指纹不同（换机 / 清除过 TPM / 更换了 TPM 固件）
        ``unknown``  备份里没有指纹（旧版备份）或本机读不到指纹
    """
    saved = manifest.get("tpm") or {}
    saved_ek = str(saved.get("ek") or "").strip().lower()
    if not saved_ek:
        return "unknown", "备份里没有 TPM 指纹（旧版备份无法校验）"
    now = tpm_identity()
    if not now["ek"]:
        return "unknown", "本机 TPM 指纹读取失败（需要管理员权限）"
    if now["ek"].lower() != saved_ek:
        return "mismatch", "备份来自其它 TPM：%s；本机 TPM：%s" % (
            str(saved.get("info") or "型号未知"), now["info"] or "型号未知")
    return "match", "TPM 指纹一致（%s）" % (now["info"] or "型号未知")


def _classify_key_error(hresult, message):
    """把"打开 TPM 密钥失败"的信息归类：``missing``（这个名字下确实没有）/ ``unknown``。"""
    hr = str(hresult or "").upper()
    if "80090016" in hr or "8009000D" in hr:            # NTE_BAD_KEYSET / NTE_NOT_FOUND
        return "missing"
    text = "%s %s" % (hr, message or "")
    for token in ("keyset", "密钥集", "cannot find the file", "找不到"):
        if token.lower() in text.lower():
            return "missing"
    return "unknown"


def _cng_open_key(guid):
    """直接以 ``guid`` 为名打开 TPM（KSP）里的机器级持久密钥。

    :return: ``(state, detail)``，state 取 ``exists`` / ``missing`` / ``unknown``
    """
    script = (
        "$ErrorActionPreference='Stop';"
        "try{"
        "$p=New-Object System.Security.Cryptography.CngProvider('%s');"
        "$k=[System.Security.Cryptography.CngKey]::Open('%s',$p,"
        "[System.Security.Cryptography.CngKeyOpenOptions]::MachineKey);"
        "$k.Dispose();Write-Output 'KEY=exists'"
        "}catch{"
        "$ex=$_.Exception; while($ex.InnerException){$ex=$ex.InnerException};"
        "$h='{0:X8}' -f ($ex.HResult -band 0xFFFFFFFF);"
        "Write-Output ('KEY=error hr=0x'+$h+' msg='+$ex.Message)"
        "}"
    ) % (_PCP_NAME, guid)
    code, output = run_command(["powershell", "-NoProfile", "-NonInteractive",
                                "-Command", script], timeout=90)
    detail = " ".join(line.strip() for line in output.splitlines() if line.strip())
    if "KEY=exists" in detail:
        return "exists", "能以该 GUID 为名直接打开 TPM 密钥"
    if "KEY=error" in detail:
        rest = detail.split("KEY=error", 1)[1].strip()
        hr, _, msg = rest.partition("msg=")
        state = _classify_key_error(hr, msg)
        return state, "%s %s" % (hr.strip(), msg.strip())
    return "unknown", detail or ("PowerShell 调用失败(%s)" % code)


def tpm_key_names():
    """列出 TPM（Microsoft Platform Crypto Provider）里 GUID 形式的机器级密钥名。

    :return: ``(names, raw)``：``names is None`` 表示列不出来（通常是没有管理员权限）；
             ``names == []`` 表示列出来了但里面没有 GUID 形式的密钥名。
    """
    code, output = run_command(["certutil", "-csp", _PCP_NAME, "-key"], timeout=120)
    if code != 0 and not output:
        return None, output
    names = []
    for line in output.splitlines():
        text = line.strip()
        if not text or text.endswith(":"):
            continue
        compact = text.replace(" ", "")
        if re.match(r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                     compact):
            names.append(compact)
    return names, output


def tpm_key_report(guid):
    """探测该卡在 TPM 里的持久密钥，返回 ``(state, text)``。

    **只有能确认"存在"时才给 ``exists``，其余一律 ``unknown``**，原因：

    * VSC 的 TPM 密钥并不以 store GUID 命名在机器作用域里——实测：两张能正常
      签名的卡片，用 store GUID 直接 ``CngKey.Open(..., MachineKey)`` 同样返回
      ``0x80090016 密钥集不存在``（驱动以 LocalService 身份创建，作用域/命名与
      我们看到的 GUID 不一致）；
    * 所以"私钥到底还能不能用"的可靠判定方式是**用 PIN 做一次真实签名**
      （``OpenSC\\pkcs15-crypt.exe --sign``，见开发文档），软件侧不做负面断言。
    """
    guid = str(guid or "").strip()
    if not guid:
        return "unknown", "备份里没有 store GUID，跳过 TPM 密钥探测"
    state, detail = _cng_open_key(guid)
    if state == "exists":
        return "exists", "已能以该 GUID 为名直接打开 TPM 密钥"
    names, _ = tpm_key_names()
    if names:
        norm = guid.replace("-", "").lower()
        if any(n.replace("-", "").lower() == norm for n in names):
            return "exists", "TPM 机器级密钥列表里找到该 GUID"
    return "unknown", ("无法由软件判定（TPM 密钥的作用域/命名与 store GUID 不一致）: %s；"
                       "要确认私钥是否可用，请用 PIN 做一次签名验证" % detail)


def tpm_key_state(guid):
    """兼容接口：等价于 ``tpm_key_report(guid)[0]``，只返回 ``exists`` / ``unknown``。"""
    return tpm_key_report(guid)[0]


def run_command(command, timeout=120):
    """执行外部命令，返回 (returncode, 合并后的输出)。"""
    try:
        process = subprocess.run(command, capture_output=True, text=True,
                                 errors="replace", timeout=timeout)
    except FileNotFoundError as err:
        return 1, "命令不存在: %s" % err
    except subprocess.TimeoutExpired:
        return 1, "命令执行超时"
    except Exception as err:
        return 1, "命令执行失败: %s" % err
    output = "%s\n%s" % (process.stdout or "", process.stderr or "")
    return process.returncode, output.strip()


def human_size(size):
    """把字节数格式化成便于阅读的字符串。"""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return "%d B" % value if unit == "B" else "%.1f %s" % (value, unit)
        value /= 1024
    return "%d B" % size


def instance_id(raw):
    """把各种写法的实例编号统一成 4 位数字（如 ``ROOT\\SMARTCARDREADER\\0000`` -> ``0000``）。"""
    text = str(raw or "").strip().replace("/", "\\").rstrip("\\")
    if not text:
        return ""
    tail = text.split("\\")[-1]
    if not tail.isdigit():
        return ""
    return "%04d" % int(tail)


def normalize_name(raw):
    """把卡片名称 / 实例编号清洗成可用作文件名的形式。"""
    text = _BAD_NAME_RE.sub("_", str(raw or "").strip())
    return text[:60] or "card"


# --------------------------------------------------------------------------- #
# 卡片枚举与信息
# --------------------------------------------------------------------------- #
def read_card_info(uid):
    """读取某个 ``ROOT\\SMARTCARDREADER\\<uid>`` 设备节点的信息。

    注意：该分支下除了 TPM 虚拟智能卡，还可能存在物理读卡器设备
    （``HardwareID`` 形如 ``Rockey\\R6Smc``），因此用 ``HardwareID`` 区分。
    """
    uid = instance_id(uid)
    if not uid:
        return None
    code, output = run_command(["reg", "query", "%s\\%s" % (VSC_ENUM_KEY, uid)])
    if code != 0:
        return None
    matched = _FRIENDLY_RE.search(output)
    hardware = re.search(r"^\s*HardwareID\s+REG_MULTI_SZ\s+(.*?)\s*$", output, re.MULTILINE)
    hardware_id = hardware.group(1).strip() if hardware else ""
    return {
        "instance": uid,
        "name": matched.group(1).strip() if matched else "",
        "hardware": hardware_id,
        # tpmvsc.inf 安装的虚拟读卡器硬件 ID
        "is_vsc": "virtualsmartcardreader" in hardware_id.lower(),
    }


def read_card_name(uid):
    """读取指定实例编号的卡片名称（``FriendlyName``）。"""
    info = read_card_info(uid)
    return info["name"] if info else ""


def device_store_path(uid=""):
    """读取该卡片设备属性里的 store 目录路径（``...\\SmartCard\\Tpm\\<GUID>\\``）。

    这是「设备实例 ↔ store 目录」的唯一绑定，由 ``tpmvsc.dll`` 写入设备属性
    ``{2065F23D-D989-4F8F-B769-4A3D779FAF0B},2``。该属性存在 ``Enum`` 下受 ACL
    保护的 ``Properties`` 子键里，直接读注册表（包括管理员 ``reg export``）都拿不到，
    但可以通过 PnP 属性接口读到。读不到时返回空字符串。
    """
    uid = instance_id(uid)
    if not uid:
        return ""
    try:
        import ctypes
        cfgmgr32 = ctypes.WinDLL("cfgmgr32.dll")
    except Exception as err:
        print("Get Device Property Error:", err)
        return ""
    node = ctypes.c_uint32(0)
    if cfgmgr32.CM_Locate_DevNodeW(ctypes.byref(node),
                                   "ROOT\\SMARTCARDREADER\\%s" % uid, 0) != 0:
        return ""
    # DEVPROPKEY = { GUID fmtid; ULONG pid; }
    raw = uuid.UUID(VSC_DEVPROP_SET).bytes_le + VSC_DEVPROP_STORE_PID.to_bytes(4, "little")
    prop = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    prop_type = ctypes.c_uint32(0)
    size = ctypes.c_uint32(0)
    code = cfgmgr32.CM_Get_DevNode_PropertyW(node, ctypes.byref(prop),
                                             ctypes.byref(prop_type), None,
                                             ctypes.byref(size), 0)
    if code not in (0, CR_BUFFER_SMALL) or size.value <= 0:
        return ""
    buffer = ctypes.create_string_buffer(size.value)
    code = cfgmgr32.CM_Get_DevNode_PropertyW(node, ctypes.byref(prop),
                                             ctypes.byref(prop_type), buffer,
                                             ctypes.byref(size), 0)
    if code != 0:
        return ""
    if prop_type.value != DEVPROP_TYPE_STRING:
        print("设备属性类型不是字符串: 0x%X" % prop_type.value)
    return buffer.raw[:size.value].decode("utf-16-le", "replace").rstrip("\x00").strip()


def card_store_guid(uid=""):
    """取该卡 store 目录名（GUID）；读不到（如设备节点还没建出来）返回空字符串。"""
    tail = device_store_path(uid).replace("/", "\\").rstrip("\\").split("\\")[-1]
    return tail if re.match(r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-", tail) else ""


def devnode_state(uid=""):
    """读取卡片设备节点在 PnP 里的真实状态，返回 ``(state, text)``。

    state 取值：

        ``missing``  设备节点不存在（``reg import`` 只写了磁盘，PnP 还没创建它）
        ``started``  设备节点已创建且驱动已启动（DN_STARTED）
        ``present``  设备节点存在但驱动未启动
        ``problem``  设备节点存在但报错（附问题码）
        ``unknown``  查询失败（cfgmgr32 不可用等）

    这是判断「注册表写回去了、设备到底有没有被创建出来」的硬判据，也是区分
    「读卡器根本没出现」与「读卡器在、但卡片没加载」的前提。
    """
    uid = instance_id(uid)
    if not uid:
        return "unknown", "没有实例编号，无法查询设备节点"
    try:
        import ctypes
        cfgmgr32 = ctypes.WinDLL("cfgmgr32.dll")
    except Exception as err:
        return "unknown", "cfgmgr32 不可用: %s" % err
    node = ctypes.c_uint32(0)
    if cfgmgr32.CM_Locate_DevNodeW(ctypes.byref(node),
                                   "ROOT\\SMARTCARDREADER\\%s" % uid, 0) != 0:
        return "missing", ("PnP 设备树里没有 ROOT\\SMARTCARDREADER\\%s "
                           "（注册表项存在不代表设备已被创建）" % uid)
    status = ctypes.c_uint32(0)
    problem = ctypes.c_uint32(0)
    if cfgmgr32.CM_Get_DevNode_Status(ctypes.byref(status), ctypes.byref(problem),
                                      node, 0) != 0:
        return "present", "设备节点存在，但状态查询失败"
    # DN_STARTED = 0x8
    if status.value & 0x00000008:
        return "started", "设备节点已创建且驱动已启动"
    if problem.value:
        return "problem", "设备节点存在但报错（问题码 0x%X）" % problem.value
    return "present", "设备节点存在但驱动未启动"


def set_device_store_path(uid="", store_path=""):
    """把卡片的 store 路径写回设备属性，修复「设备实例 → store 目录」的绑定。

    走 PnP 属性接口（``CM_Set_DevNode_PropertyW``），无需改动 ``Enum`` 下受 ACL
    保护的 ``Properties`` 子键。设备节点不存在时（例如系统重装后尚未重启）写不进去，
    调用方应提示用户重启系统后再执行一次还原。

    :return: ``(ok, text)``：是否写入成功，以及可直接放进日志的说明
    """
    uid = instance_id(uid)
    store_path = str(store_path or "")
    if not uid or not store_path:
        return False, "缺少实例编号或 store 路径，未写回设备属性"
    try:
        import ctypes
        cfgmgr32 = ctypes.WinDLL("cfgmgr32.dll")
    except Exception as err:
        return False, "cfgmgr32 不可用: %s" % err
    node = ctypes.c_uint32(0)
    if cfgmgr32.CM_Locate_DevNodeW(ctypes.byref(node),
                                   "ROOT\\SMARTCARDREADER\\%s" % uid, 0) != 0:
        return False, ("设备节点 ROOT\\SMARTCARDREADER\\%s 还没有被 PnP 创建出来，"
                       "现在写不进设备属性" % uid)
    if not store_path.endswith("\\"):
        store_path += "\\"
    raw = uuid.UUID(VSC_DEVPROP_SET).bytes_le + VSC_DEVPROP_STORE_PID.to_bytes(4, "little")
    prop = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    encoded = store_path.encode("utf-16-le")
    buffer = ctypes.create_string_buffer(encoded + b"\x00\x00")
    # DEVPROP_TYPE_STRING 的缓冲区长度必须**含结尾的 NUL**：少 2 字节会被判为
    # CR_INVALID_DATA(0x1F) 而写入失败；即使侥幸写进去，没有终止符的字符串也会
    # 被驱动读成乱码路径，卡片依然起不来。
    code = cfgmgr32.CM_Set_DevNode_PropertyW(node, ctypes.byref(prop),
                                             DEVPROP_TYPE_STRING, buffer,
                                             ctypes.c_uint32(len(encoded) + 2), 0)
    if code != 0:
        return False, ("写回设备属性失败: CONFIGRET=%s"
                       "（0x1F=数据无效、0x33=权限不足）" % code)
    # 回读校验：写入接口返回成功不等于驱动能读到正确路径
    back = device_store_path(uid)
    if back.replace("/", "\\").rstrip("\\").lower() != store_path.rstrip("\\").lower():
        return False, "设备属性写入后回读不一致（读到 %r），绑定可能未生效" % back
    return True, "属性回读校验通过"


def list_cards():
    """读取注册表中已存在的 TPM 虚拟智能卡（已过滤掉物理读卡器设备）。

    返回 ``[{"instance": "0000", "name": "卡片名称", "hardware", "is_vsc"}]``；
    读取失败返回空列表。
    """
    code, output = run_command(["reg", "query", VSC_ENUM_KEY])
    if code != 0:
        return []
    cards = []
    for line in output.splitlines():
        line = line.strip()
        if not line.upper().startswith("HKEY_"):
            continue
        tail = line.rstrip("\\").split("\\")[-1]
        if not tail.isdigit():
            continue
        info = read_card_info("%04d" % int(tail))
        if info and info["is_vsc"]:
            cards.append(info)
    cards.sort(key=lambda item: item["instance"])
    return cards


def find_card(name="", uid=""):
    """按实例编号（优先）或卡片名称定位卡片，返回卡片字典；找不到返回 None。"""
    target_uid = instance_id(uid)
    target_name = str(name or "").strip().lower()
    for card in list_cards():
        if target_uid and card["instance"] == target_uid:
            return card
        if target_name and card["name"].strip().lower() == target_name:
            return card
    return None


# --------------------------------------------------------------------------- #
# 卡片数据目录
# --------------------------------------------------------------------------- #
def store_exists():
    return os.path.isdir(VSC_STORE_DIR)


def store_state():
    """卡片数据目录的状态：``ok`` / ``missing`` / ``denied``。

    非管理员时目录会被 ACL 拒绝，此时 ``os.path.isdir`` 也会返回 False，
    因此这里显式区分「不存在」与「无权访问」。
    """
    if os.path.isdir(VSC_STORE_DIR):
        return "ok"
    if not is_admin():
        return "denied"
    return "missing"


def locate_card_entries(name="", uid=""):
    """在卡片数据目录中定位属于某张卡的条目（通常是 ``<GUID>`` 目录）。

    优先用设备属性里的 store 路径精确定位（``device_store_path``，即
    ``Tpm\\<GUID>``）；拿不到时退化为「条目名包含实例编号或卡片名称」的模糊匹配，
    再匹配不到就返回空列表，由调用方决定整目录备份。
    需要管理员权限，权限不足时抛 BackupError。
    """
    try:
        entries = sorted(os.listdir(VSC_STORE_DIR))
    except PermissionError as err:
        raise BackupError("读取卡片数据目录失败（需要管理员权限）: %s" % err)
    except OSError as err:
        raise BackupError("读取卡片数据目录失败: %s" % err)
    target_uid = instance_id(uid)
    guid = card_store_guid(target_uid)
    if guid:
        for entry in entries:
            if entry.lower() == guid.lower():
                return [entry]
    target_name = str(name or "").strip().lower()
    hits = []
    for entry in entries:
        lowered = entry.lower()
        if target_uid and target_uid in lowered:
            hits.append(entry)
            continue
        if target_name and target_name in lowered:
            hits.append(entry)
    return hits


def store_index():
    """列出卡片数据目录下的全部条目（相对路径 + 大小 + 修改时间），用于诊断。"""
    lines = ["# 卡片数据目录: %s" % VSC_STORE_DIR]
    state = store_state()
    if state != "ok":
        lines.append("(目录%s)" % ("不存在" if state == "missing" else "无法访问，需要管理员权限"))
        return lines
    try:
        for root, dirs, files in os.walk(VSC_STORE_DIR):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(root, name)
                try:
                    stat = os.stat(full)
                except OSError:
                    continue
                rel = os.path.relpath(full, VSC_STORE_DIR)
                stamp = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                lines.append("%-70s %10d  %s" % (rel, stat.st_size, stamp))
    except OSError as err:
        lines.append("(遍历失败: %s)" % err)
    if len(lines) == 1:
        lines.append("(目录为空)")
    return lines


# --------------------------------------------------------------------------- #
# 备份
# --------------------------------------------------------------------------- #
def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _collect_files(source_root, prefix=""):
    """遍历 source_root，返回 [(包内相对路径, 绝对路径, 大小, sha256)]。

    ``prefix`` 会拼到相对路径前面（如 ``files/<条目名>/x.dat``），
    为空时按备份包根目录计。
    """
    results = []
    for root, dirs, files in os.walk(source_root):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, source_root).replace("\\", "/")
            if prefix:
                rel = "%s/%s" % (prefix.strip("/"), rel)
            results.append(_file_entry(full, rel))
    return results


def _file_entry(path, arcname):
    """把单个文件收集成备份条目 (包内相对路径, 绝对路径, 大小, sha256)。"""
    try:
        size = os.path.getsize(path)
        sha = _sha256(path)
    except OSError as err:
        raise BackupError("读取文件失败: %s (%s)" % (path, err))
    return arcname.replace("\\", "/"), path, size, sha


def _backup_path(dest_path, card_name, instance):
    """按用户选择的路径给出 ``.tsb`` 备份文件路径（给目录时自动命名）。"""
    raw = str(dest_path or "").strip()
    if not raw:
        raise BackupError("未指定备份文件的保存路径")
    dir_like = raw.endswith(("\\", "/")) or os.path.isdir(raw)
    dest = os.path.abspath(raw)
    if dir_like:
        return os.path.join(dest, "%s-%s%s" % (normalize_name(card_name), instance, BACKUP_SUFFIX))
    if not dest.lower().endswith(BACKUP_SUFFIX):
        dest += BACKUP_SUFFIX
    return dest


def _discard(path):
    """删除写失败留下的半成品文件（不存在或删不掉时忽略）。"""
    try:
        if os.path.lexists(path):
            os.remove(path)
    except OSError:
        pass


def create_backup(dest_path, name="", uid=""):
    """把一张 TPM 虚拟智能卡的「文件 + 注册表」备份成 ``.tsb`` 压缩包。

    :param dest_path: 备份文件保存路径（``.tsb``）；给目录时按
        ``卡片名-实例编号.tsb`` 自动命名
    :param name: 卡片名称（界面选中的名称）
    :param uid: 卡片实例编号（如 ``0000``），为空时按名称匹配
    :return: 报告字典 ``{"file", "card", "instance", "scope", "warning",
             "file_count", "size", "reg_count", "log"}``
    :raises BackupError: 权限不足 / 卡片未找到 / 文件不可写等
    """
    if not is_admin():
        raise BackupError("需要管理员权限：请以管理员身份运行本工具后再备份")

    card = find_card(name=name, uid=uid)
    if card is None:
        raise BackupError("未在注册表中找到该虚拟智能卡，请确认卡片名称或实例编号")
    card_name = card["name"] or name or ("卡 %s" % card["instance"])
    tsb_path = _backup_path(dest_path, card_name, card["instance"])
    log = []

    # ---- 1. 收集卡片数据文件（只读取，压缩时再写进包） -------------------- #
    scope = "none"
    entries = []
    warning = ""
    copied = []
    guid = ""
    state = store_state()
    if state == "denied":
        raise BackupError("无权访问卡片数据目录，请以管理员身份运行本工具: %s" % VSC_STORE_DIR)
    if state == "ok":
        guid = card_store_guid(card["instance"])
        if guid:
            log.append("卡片 store 目录: %s" % guid)
        else:
            log.append("未读到卡片 store 目录（设备属性不可用），按名称/实例模糊匹配")
        entries = locate_card_entries(card_name, card["instance"])
        try:
            if entries:
                # 命中与当前卡相关的条目：按条目逐个备份
                scope = "card"
                for entry in entries:
                    source = os.path.join(VSC_STORE_DIR, entry)
                    arcname = "%s/%s" % (FILES_DIR, entry)
                    if os.path.isdir(source):
                        copied.extend(_collect_files(source, arcname))
                    else:
                        copied.append(_file_entry(source, arcname))
                    log.append("已备份卡片数据条目: %s" % entry)
            else:
                # 无法定位到具体条目：退化为整目录备份（还原时会覆盖整个数据目录）
                scope = "store"
                copied = _collect_files(VSC_STORE_DIR, FILES_DIR)
                warning = ("未能在数据目录中按名称定位到本卡条目，已整目录备份；"
                           "还原时会覆盖整个卡片数据目录，请仅在本机所有卡片均来自"
                           "同一份备份时还原")
                log.append("未能按名称定位到具体条目，已整目录备份: %s" % VSC_STORE_DIR)
        except PermissionError as err:
            raise BackupError("读取卡片数据失败（需要管理员权限）: %s" % err)
        except OSError as err:
            raise BackupError("读取卡片数据失败: %s" % err)
    else:
        log.append("卡片数据目录不存在，跳过文件备份: %s" % VSC_STORE_DIR)

    # ---- 1b. TPM 密钥索引（PCP 密钥元数据）-------------------------------- #
    # 换系统 / 重装后卡片能不能起来，取决于这份「KSP 密钥名 → TPM 对象」的索引；
    # 它不在 store 目录里，必须单独收进备份。
    pcp = []
    for index, folder in enumerate(VSC_PCP_DIRS):
        if not os.path.isdir(folder):
            log.append("TPM 密钥索引目录不存在（跳过）: %s" % folder)
            continue
        try:
            picked = _collect_files(folder, "%s/%d" % (PCP_DIR, index))
        except (PermissionError, OSError) as err:
            log.append("读取 TPM 密钥索引目录失败（跳过）: %s (%s)" % (folder, err))
            continue
        copied.extend(picked)
        pcp.append({"index": index, "dir": folder, "files": len(picked)})
        log.append("已备份 TPM 密钥索引: %s（%d 个文件）" % (folder, len(picked)))
    if not pcp:
        log.append("警告: 没有备份到任何 TPM 密钥索引，换系统 / 重装后卡片将无法启动")

    # ---- 1c. 设备属性（卡片身份）----------------------------------------- #
    # tpmvsc 把「卡片名 / 卡片 GUID / store 目录」放在设备属性里（Enum 下受 ACL
    # 保护的 Properties 子键），注册表导出带不回来；实测缺了它，设备节点即使启动，
    # 驱动也不会向 PC/SC 发布读卡器，卡片自然就"没有出现"。
    properties = read_device_properties(card["instance"])
    vendor_props = vendor_property_count(properties)
    log.append("已备份设备属性: %d 项（其中厂商卡片身份 %d 项）"
               % (len(properties), vendor_props))
    if not vendor_props:
        log.append("警告: 没读到厂商卡片身份属性，还原后读卡器很可能不会出现")

    # 数据目录清单（诊断用，便于确认目录内部布局）
    index_lines = store_index()

    # ---- 2. 写进 .tsb 压缩包 ---------------------------------------------- #
    # 先写 .part 再改名：中途失败不会留下一个损坏的备份文件
    part_path = "%s.part" % tsb_path
    registry = []
    try:
        with zipfile.ZipFile(part_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for rel, full, _, _ in copied:
                try:
                    archive.write(full, rel)
                except OSError as err:
                    raise BackupError("写入备份文件失败: %s (%s)" % (rel, err))
            archive.writestr("store-index.txt", "\n".join(index_lines))

            # ---- 3. 注册表：导出到临时文件后收进压缩包 -------------------- #
            keys = [("SMARTCARDREADER-%s" % card["instance"],
                     "%s\\%s" % (VSC_ENUM_KEY, card["instance"]))]
            reader_key = "%s\\Microsoft Virtual Smart Card %d" % (VSC_READER_KEY,
                                                                 int(card["instance"]))
            code, _ = run_command(["reg", "query", reader_key])
            if code == 0:
                keys.append(("CalaisReader-%s" % card["instance"], reader_key))
            with tempfile.TemporaryDirectory(prefix="tpmvsc-reg-") as reg_dir:
                for tag, key in keys:
                    reg_file = os.path.join(reg_dir, "%s.reg" % tag)
                    code, output = run_command(["reg", "export", key, reg_file, "/y"])
                    if code != 0:
                        log.append("导出注册表失败（已跳过）: %s" % key)
                        continue
                    archive.write(reg_file, "%s/%s.reg" % (REGISTRY_DIR, tag))
                    registry.append({"key": key, "file": "%s/%s.reg" % (REGISTRY_DIR, tag)})
                    log.append("已导出注册表: %s" % key)
            if not registry:
                raise BackupError("注册表导出失败：未拿到任何卡片设备节点，请确认卡片存在且以管理员运行")

            # ---- 4. 清单 -------------------------------------------------- #
            tpm = tpm_identity()
            log.append("本机 TPM 指纹: %s" % (tpm["ek"] or "读取失败（需管理员权限）"))
            if tpm["info"]:
                log.append("本机 TPM: %s" % tpm["info"])
            manifest = {
                "format": BACKUP_FORMAT,
                "tool": "TPMSmartCard",
                "tool_version": VERSION,
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "computer": socket.gethostname(),
                "tpm": tpm,
                "card": {
                    "name": card_name,
                    "instance": card["instance"],
                    "enum_key": "%s\\%s" % (VSC_ENUM_KEY, card["instance"]),
                },
                "store": {
                    "dir": VSC_STORE_DIR,
                    "scope": scope,
                    "guid": guid,
                    "entries": entries,
                    "index": "store-index.txt",
                },
                "registry": registry,
                "pcp": pcp,
                "system_root": SYSTEM_ROOT,
                "device_properties": properties,
                "files": [{"path": rel, "size": size, "sha256": sha}
                          for rel, _, size, sha in copied],
                "notes": [
                    "备份包含四部分：卡片数据目录（Tpm）、设备注册表、TPM 密钥索引"
                    "（PCPKSP 下的 *.PCPKEY）、设备属性（卡片身份：卡片名与卡片 GUID）；"
                    "不含 TPM 内部的密钥材料。",
                    "设备属性存在 Enum 下受 ACL 保护的 Properties 子键里，注册表导出"
                    "带不回来，必须单独备份——少了它驱动不会向 PC/SC 发布读卡器。",
                    "卡片私钥由 TPM 保护，磁盘上只有 TPM 封装后的数据；"
                    "TPM 密钥索引只记录「KSP 密钥名 → TPM 对象」的映射，"
                    "少了它换系统 / 重装后卡片起不来（读卡器都不会出现）。",
                    "仅在「同一台电脑 + 同一 TPM（未清除）」上可以还原；换机、清除 TPM、"
                    "删除卡片后再还原都可能无法恢复私钥，请同时保留卡片名称、PIN、PUK 与管理密码。",
                ] + ([warning] if warning else []),
            }
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))

        os.replace(part_path, tsb_path)
    except OSError as err:
        raise BackupError("写入备份文件失败: %s" % err)
    finally:
        _discard(part_path)

    total = sum(item[2] for item in copied)
    log.append("已生成备份文件: %s" % tsb_path)
    print("\n".join(log))
    return {
        "file": tsb_path,
        "card": card_name,
        "instance": card["instance"],
        "scope": scope,
        "warning": warning,
        "file_count": len(copied),
        "size": total,
        "reg_count": len(registry),
        "log": log,
    }


# --------------------------------------------------------------------------- #
# 还原
# --------------------------------------------------------------------------- #
class _PackageReader:
    """``.tsb`` 备份包读取器（``.tsb`` 就是 zip 压缩包，按包内相对路径读取）。"""

    def __init__(self, package):
        self.path = os.path.abspath(str(package or "").strip('"').strip())
        if not os.path.isfile(self.path):
            raise BackupError("找不到备份文件: %s" % self.path)
        if not self.path.lower().endswith(BACKUP_SUFFIX):
            raise BackupError("请选择 %s 备份文件: %s" % (BACKUP_SUFFIX, self.path))
        if not zipfile.is_zipfile(self.path):
            raise BackupError("该文件不是有效的 %s 备份文件: %s" % (BACKUP_SUFFIX, self.path))
        try:
            self.zip = zipfile.ZipFile(self.path, "r")
        except (OSError, zipfile.BadZipFile) as err:
            raise BackupError("备份文件无法打开: %s" % err)

    def close(self):
        if self.zip is not None:
            self.zip.close()
            self.zip = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def exists(self, rel):
        return str(rel or "").replace("\\", "/") in self.zip.namelist()

    def read(self, rel):
        rel = str(rel or "").replace("\\", "/")
        try:
            return self.zip.read(rel)
        except (KeyError, OSError, zipfile.BadZipFile) as err:
            raise BackupError("读取备份文件失败: %s (%s)" % (rel, err))


def read_manifest(package, reader=None):
    """读取备份清单并做基本校验。

    ``package`` 是 ``.tsb`` 备份文件；``reader`` 用于复用已经打开的备份包，
    避免同一次还原里重复打开压缩包。
    """
    if reader is None:
        with _PackageReader(package) as opened:
            return read_manifest(package, opened)
    if not reader.exists(MANIFEST_NAME):
        raise BackupError("不是本工具的备份：缺少 %s" % MANIFEST_NAME)
    try:
        manifest = json.loads(reader.read(MANIFEST_NAME).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as err:
        raise BackupError("备份清单无法解析: %s" % err)
    if not isinstance(manifest, dict) or "card" not in manifest:
        raise BackupError("备份清单内容不完整")
    if int(manifest.get("format", 0)) > BACKUP_FORMAT:
        raise BackupError("备份包版本高于当前程序，请升级本工具后再还原")
    return manifest


def _clear_readonly(path):
    """清除只读属性：Windows 上覆盖写入只读文件会直接报 errno 13。"""
    if not os.path.lexists(path):
        return
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass


def _remove_entry(path):
    """移除目标位置的同名条目（只读文件 / 同名目录），失败时忽略后续再报错。"""
    _clear_readonly(path)
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.lexists(path):
            os.remove(path)
    except OSError:
        pass


def _take_control(directory):
    """对目录及其内容取得所有权并授予管理员完全控制，返回日志行。

    卡片数据目录位于 LocalService 配置文件下，其中部分条目（如 ``keymaps``）
    的 ACL 只授予 SYSTEM，导致即使以管理员身份运行，写入仍被拒绝（errno 13）。
    """
    log = []
    if not directory or not os.path.isdir(directory):
        return log
    commands = (
        ["takeown", "/f", directory, "/r", "/d", "y", "/a"],
        ["icacls", directory, "/grant", "*S-1-5-32-544:(OI)(CI)F", "/t", "/c", "/q"],
    )
    for command in commands:
        code, output = run_command(command)
        detail = "成功" if code == 0 else (output.splitlines()[0] if output else str(code))
        log.append("修复访问控制 %s %s: %s" % (command[0], directory, detail))
    return log


def _write_data(data, target, log):
    """把备份包里的数据写入卡片数据目录，自动绕开常见的写入受阻情况。

    实测 ``Tpm\\<GUID>\\keymaps`` 这类条目会直接报
    ``[Errno 13] Permission denied``，原因是：目标带只读属性、
    目标被同名目录占位，或被 ACL 限制为仅 SYSTEM 可写。
    这里按「清除只读属性 -> 清理占位条目 -> 修复 ACL」的顺序处理后重试。
    """
    parent = os.path.dirname(target)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError:
        log.extend(_take_control(parent))
        if os.path.lexists(parent) and not os.path.isdir(parent):
            # 目标父级被同名文件占位（备份里是目录、本机是文件）
            log.append("目标父级被同名文件占用，已移除后重建: %s" % parent)
            _remove_entry(parent)
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as err:
            raise BackupError("创建卡片数据目录失败: %s\n请先删除同名卡片或重启系统后重试。" % err)

    for attempt in (0, 1):
        try:
            _clear_readonly(target)
            with open(target, "wb") as handle:
                handle.write(data)
            return
        except PermissionError as err:
            if attempt:
                raise BackupError(
                    "写入卡片数据失败: %s\n"
                    "目标可能只允许 SYSTEM 访问，或被智能卡服务占用。\n"
                    "请确认以管理员身份运行、先删除同名卡片，或重启系统后重试。" % err)
            if os.path.isdir(target):
                log.append("目标被同名目录占用，已移除后重写: %s" % target)
            _remove_entry(target)
            log.extend(_take_control(parent))
        except OSError as err:
            raise BackupError("写入卡片数据失败: %s\n请先删除同名卡片或重启系统后重试" % err)


def _service(action):
    """启动 / 停止智能卡服务，返回一行日志。"""
    code, output = run_command(["sc", action, CARD_SERVICE])
    detail = output.splitlines()[0] if output else str(code)
    return "智能卡服务 %s %s: %s" % (CARD_SERVICE, action, detail)


def _wide_multi(text):
    """REG_MULTI_SZ 形态的 UTF-16LE 缓冲区（以双 NUL 结尾）。"""
    return (str(text) + "\0\0").encode("utf-16-le")


def drop_orphan_enum_key(uid=""):
    """删掉「只存在于注册表、没有设备节点」的孤儿 Enum 项（先导出留底）。

    重建之前必须先删：``SetupDiCreateDeviceInfo`` 遇到已存在的实例会返回
    ``SPAPI_E_DEVINST_ALREADY_EXISTS(0xE0000205)``。项里除了设备描述之外都是
    INF 能重新生成的，卡片数据在 store 目录里，不受影响。

    :return: ``(ok, text)``
    """
    uid = instance_id(uid)
    if not uid:
        return False, "缺少实例编号，无法清理孤儿注册表项"
    key = "%s\\%s" % (VSC_ENUM_KEY, uid)
    code, _ = run_command(["reg", "query", key])
    if code != 0:
        return True, "Enum 项 %s 不存在，无需清理" % key
    keep = os.path.join(log_dir(), "enum-orphan-%s.reg" % uid)
    run_command(["reg", "export", key, keep, "/y"])
    code, output = run_command(["reg", "delete", key, "/f"])
    if code != 0:
        return False, ("删除孤儿 Enum 项失败（%s）: %s"
                       % (key, output.strip().splitlines()[0] if output.strip() else code))
    return True, "已删除没有设备节点的 Enum 项 %s（原内容留底 %s）" % (key, keep)


def register_card_device(uid="", friendly_name=""):
    """用 Windows 自己的设备注册接口把 ``ROOT\\SMARTCARDREADER\\<uid>`` 设备节点建出来。

    为什么必须走到这里：``reg import`` 只是把 Enum 项写回了磁盘，PnP 的**内存设备树**
    里并没有这个节点。实测（Win10 19044，同机换系统还原的场景）仅靠
    ``CM_Reenumerate_DevNode`` 或 ``pnputil /scan-devices`` 都**不会**把它创建出来，
    于是读卡器永远不出现。创建 ROOT 设备的正规做法就是 ``devcon install`` 用的那套：

    1. ``SetupDiCreateDeviceInfo``（显式指定实例号，保证读卡器名 ``Microsoft Virtual
       Smart Card <n>`` 与备份里的实例一致）
    2. ``SetupDiSetDeviceRegistryProperty`` 写 HardwareID（可选 FriendlyName）
    3. ``SetupDiCallClassInstaller(DIF_REGISTERDEVICE)``
    4. ``UpdateDriverForPlugAndPlayDevices`` 用 ``%SystemRoot%\\inf\\tpmvsc.inf`` 装驱动

    这样会顺带生成 ``Driver``、``Device Parameters\\WUDF\\DriverList``、``Properties``
    等键（``reg import`` 带不回来的那部分），驱动起来后即可用 ``set_device_store_path``
    把 store 绑定写回。

    :return: ``(ok, text)``
    """
    uid = instance_id(uid)
    if not uid:
        return False, "缺少实例编号，无法注册设备"
    try:
        import ctypes
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

    def failed(message):
        return "%s（错误码 %s）" % (message, ctypes.get_last_error())

    setupapi.SetupDiCreateDeviceInfoList.restype = ctypes.c_void_p
    class_guid = guid_of(VSC_READER_CLASS_GUID)
    device_name = "ROOT\\SMARTCARDREADER\\%s" % uid
    info = setupapi.SetupDiCreateDeviceInfoList(ctypes.byref(class_guid), None)
    if not info or info == ctypes.c_void_p(-1).value:
        return False, failed("SetupDiCreateDeviceInfoList 失败")
    # HDEVINFO 是 64 位句柄：不声明 argtypes 时 ctypes 会把 Python int 当 C int（32 位）
    # 转换，句柄值超过 2^31 就抛 OverflowError: int too long to convert，
    # 所以这里统一用 c_void_p 包一层再传给其它 API。
    handle = ctypes.c_void_p(info)
    try:
        data = _SP_DEVINFO_DATA()
        data.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
        if not setupapi.SetupDiCreateDeviceInfoW(handle, device_name, ctypes.byref(class_guid),
                                                 friendly_name or None, None, 0,
                                                 ctypes.byref(data)):
            return False, failed("SetupDiCreateDeviceInfoW(%s) 失败" % device_name)
        hardware = _wide_multi(VSC_READER_HARDWARE_ID)
        if not setupapi.SetupDiSetDeviceRegistryPropertyW(
                handle, ctypes.byref(data), SPDRP_HARDWAREID, hardware, len(hardware)):
            return False, failed("写入 HardwareID 失败")
        if friendly_name:
            label = _wide_multi(friendly_name)
            setupapi.SetupDiSetDeviceRegistryPropertyW(
                handle, ctypes.byref(data), SPDRP_FRIENDLYNAME, label, len(label))
        if not setupapi.SetupDiCallClassInstaller(DIF_REGISTERDEVICE, handle, ctypes.byref(data)):
            return False, failed("DIF_REGISTERDEVICE 失败")
        reboot = ctypes.c_int(0)
        if not newdev.UpdateDriverForPlugAndPlayDevicesW(None, VSC_READER_HARDWARE_ID,
                                                         VSC_READER_INF, INSTALLFLAG_FORCE,
                                                         ctypes.byref(reboot)):
            return False, failed("UpdateDriverForPlugAndPlayDevices 失败")
        # SPDRP_FRIENDLYNAME 写的是 PnP 属性存储，不会生成老式 FriendlyName 的
        # REG_SZ；卡片名要能被 read_card_info / 界面读出来，得显式补一个
        if friendly_name:
            run_command(["reg", "add", "%s\\%s" % (VSC_ENUM_KEY, uid),
                         "/v", "FriendlyName", "/t", "REG_SZ", "/d", friendly_name, "/f"])
        return True, "已用 SetupDi 注册设备 %s（需要重启=%s）" % (device_name, bool(reboot.value))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(handle)


def _guid_raw(text):
    """GUID 字符串 → ``DEVPROPKEY.fmtid`` 需要的 16 字节小端内存布局。"""
    return uuid.UUID(str(text).strip("{}")).bytes_le


def _setupapi_props():
    """准备 setupapi 的设备属性接口，返回 ``(setupapi, SP_DEVINFO_DATA, DEVPROPKEY)``。

    用 SetupAPI 而不是直接读注册表：``Properties`` 子键的 ACL 连管理员都不给读，
    但 PnP 属性接口可以正常读写。
    """
    import ctypes
    setupapi = ctypes.WinDLL("setupapi.dll", use_last_error=True)
    setupapi.SetupDiCreateDeviceInfoList.restype = ctypes.c_void_p

    class _DevInfo(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint32), ("ClassGuid", ctypes.c_byte * 16),
                    ("DevInst", ctypes.c_uint32), ("Reserved", ctypes.c_void_p)]

    class _PropKey(ctypes.Structure):
        _fields_ = [("fmtid", ctypes.c_byte * 16), ("pid", ctypes.c_uint32)]

    return setupapi, _DevInfo, _PropKey


def _open_device(setupapi, devinfo, uid):
    """打开设备实例，返回 ``(设备信息集句柄, 设备信息结构)``；失败返回 ``(None, None)``。

    句柄用 ``ctypes.c_void_p`` 包一层再传：``HDEVINFO`` 是 64 位句柄，不声明
    ``argtypes`` 时 ctypes 会把 Python int 当 C ``int``（32 位）转换，句柄值超过
    2^31 就抛 ``OverflowError: int too long to convert``（备份时必现，因为每张卡都
    要走这里读设备属性）。
    """
    import ctypes
    info = setupapi.SetupDiCreateDeviceInfoList(None, None)
    if not info or info == ctypes.c_void_p(-1).value:
        return None, None
    handle = ctypes.c_void_p(info)
    data = devinfo()
    data.cbSize = ctypes.sizeof(devinfo)
    if not setupapi.SetupDiOpenDeviceInfoW(handle, "ROOT\\SMARTCARDREADER\\%s" % instance_id(uid),
                                          None, 0, ctypes.byref(data)):
        setupapi.SetupDiDestroyDeviceInfoList(handle)
        return None, None
    return handle, data


def _property_entries(setupapi, devinfo, propkey, info, data):
    """枚举设备上的 PnP 属性，返回 ``[(键, 类型, 原始字节)]``。"""
    import ctypes
    needed = ctypes.c_uint32(0)
    setupapi.SetupDiGetDevicePropertyKeys(info, ctypes.byref(data), None, 0,
                                          ctypes.byref(needed), 0)
    if needed.value <= 0:
        return []
    buffer = ctypes.create_string_buffer(needed.value * DEVPROPKEY_SIZE)
    if not setupapi.SetupDiGetDevicePropertyKeys(info, ctypes.byref(data), buffer,
                                                 needed.value, ctypes.byref(needed), 0):
        return []
    results = []
    for index in range(needed.value):
        raw = buffer.raw[index * DEVPROPKEY_SIZE:(index + 1) * DEVPROPKEY_SIZE]
        if len(raw) < DEVPROPKEY_SIZE:
            break
        key = propkey.from_buffer_copy(raw)
        ptype = ctypes.c_uint32(0)
        required = ctypes.c_uint32(0)
        setupapi.SetupDiGetDevicePropertyW(info, ctypes.byref(data), ctypes.byref(key),
                                           ctypes.byref(ptype), None, 0,
                                           ctypes.byref(required), 0)
        size = required.value
        if size <= 0 or size > 65536:
            continue
        blob = ctypes.create_string_buffer(size)
        if not setupapi.SetupDiGetDevicePropertyW(info, ctypes.byref(data), ctypes.byref(key),
                                                  ctypes.byref(ptype), blob, size,
                                                  ctypes.byref(required), 0):
            continue
        results.append((key, ptype.value, blob.raw[:required.value]))
    return results


def read_device_properties(uid=""):
    """读设备的全部 PnP 属性（含 ACL 受保护、``reg export`` 读不到的 ``Properties``）。

    :return: ``[{"fmtid", "pid", "type", "data"}]``，``data`` 是 base64；读不到返回空表
    """
    uid = instance_id(uid)
    if not uid:
        return []
    try:
        setupapi, devinfo, propkey = _setupapi_props()
    except Exception as err:
        print("Load setupapi Error:", err)
        return []
    info, data = _open_device(setupapi, devinfo, uid)
    if info is None:
        return []
    try:
        return [{"fmtid": str(uuid.UUID(bytes_le=bytes(key.fmtid))),
                 "pid": key.pid,
                 "type": ptype,
                 "data": base64.b64encode(blob).decode("ascii")}
                for key, ptype, blob in _property_entries(setupapi, devinfo, propkey, info, data)]
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(info)


def _rewrite_system_root(blob, ptype, source_root):
    """把属性里的备份机器 ``%SystemRoot%`` 前缀换成本机的。

    厂商属性里有三处绝对路径（store 目录、``tpmvsc.dll``、``smartcardsimulator.dll``），
    换系统后盘符/系统目录可能不同，照搬旧值驱动会找不到路径。
    """
    if ptype not in (DEVPROP_TYPE_STRING, DEVPROP_TYPE_STRING_LIST):
        return blob
    source = str(source_root or "").rstrip("\\")
    if not source or source.lower() == SYSTEM_ROOT.lower():
        return blob
    try:
        text = blob.decode("utf-16-le")
    except UnicodeDecodeError:
        return blob
    if source.lower() not in text.lower():
        return blob
    return re.sub(re.escape(source), lambda match: SYSTEM_ROOT,
                  text, flags=re.IGNORECASE).encode("utf-16-le")


def write_device_properties(uid="", properties=None, source_root=""):
    """把备份里的 PnP 设备属性写回本机设备。

    只写「本机设备上还没有的」属性：PnP 自己生成的安装信息（``DEVPKEY_Device_*``）
    本机已经有了，同机还原时属性本来也在，都不动；只有真正缺失的厂商属性会被补齐。

    :param properties: ``read_device_properties()`` 的结果
    :param source_root: 备份机器的 ``%SystemRoot%``，用于改写属性里的绝对路径
    :return: 日志行列表
    """
    records = properties or []
    if not records:
        return ["备份里没有设备属性（老版本备份），跳过补充卡片身份属性"]
    try:
        import ctypes
        setupapi, devinfo, propkey = _setupapi_props()
    except Exception as err:
        return ["setupapi 不可用，跳过写回设备属性: %s" % err]
    info, data = _open_device(setupapi, devinfo, uid)
    if info is None or data is None:
        return ["设备节点不存在，跳过写回设备属性（卡片身份属性是驱动认出卡片的关键）"]
    written = 0
    skipped = 0
    failed = []
    try:
        existing = set()
        for key, _, _ in _property_entries(setupapi, devinfo, propkey, info, data):
            existing.add((str(uuid.UUID(bytes_le=bytes(key.fmtid))).lower(), key.pid))
        for record in records:
            fmtid = str(record.get("fmtid") or "").strip().lower()
            if not fmtid:
                continue
            pid = int(record.get("pid") or 0)
            if (fmtid, pid) in existing:
                skipped += 1
                continue
            try:
                blob = base64.b64decode(str(record.get("data") or ""))
                key = propkey.from_buffer_copy(_guid_raw(fmtid) + pid.to_bytes(4, "little"))
            except (ValueError, TypeError, OverflowError):
                continue
            ptype = int(record.get("type") or 0)
            if not blob or not ptype:
                continue
            blob = _rewrite_system_root(blob, ptype, source_root)
            if setupapi.SetupDiSetDevicePropertyW(info, ctypes.byref(data), ctypes.byref(key),
                                                  ptype, blob, len(blob), 0):
                written += 1
            else:
                failed.append("%s,%d" % (fmtid, pid))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(info)
    lines = ["已写回设备属性: %d 项（本机已有 %d 项未改动）" % (written, skipped)]
    if failed:
        lines.append("以下设备属性写入失败（不影响其它项）: %s" % ", ".join(failed[:6]))
    return lines


def vendor_property_count(properties=None):
    """数一下记录里有几项厂商卡片身份属性（用于备份时的自检提示）。"""
    wanted = (VSC_PROP_SET_TPMVSC, VSC_PROP_SET_SIMULATOR)
    return sum(1 for item in (properties or [])
               if str(item.get("fmtid") or "").upper() in wanted)


def _rescan_devices(uid="", attempts=3):
    """让 PnP 重新枚举设备，使还原后的虚拟智能卡无需重启即可出现。

    还原只是把 ``Enum\\ROOT\\SMARTCARDREADER\\<uid>`` 注册表项写了回去，
    PnP 的内存设备树上并没有这个设备节点；必须重新枚举才会真正创建并启动
    这张卡（等价于设备管理器里的「扫描检测硬件改动」），否则要重启系统才能在
    读卡器列表里看到它。

    依次做三件事，并且**每一步之后都复核设备节点是否真的出现了**（``reg import``
    返回成功并不代表设备已被创建）：

    1. ``CM_Reenumerate_DevNode(设备树根节点)``，最多重试 ``attempts`` 次；
    2. 第一次重试后仍没节点时，用 ``pnputil /scan-devices`` 兜底（部分环境下
       上一条不会重新创建仅存在于注册表里的 ROOT 设备）；
    3. 节点出现后，再强制重新枚举该节点一次，让驱动重新加载并重新读取卡片数据
       （否则驱动里可能还停留在「卡片已被删除」的旧状态，读卡器会显示无卡）。

    返回日志行列表。
    """
    import ctypes

    uid = instance_id(uid)
    try:
        cfgmgr32 = ctypes.WinDLL("cfgmgr32.dll")
    except Exception as err:
        return ["设备重新枚举不可用: %s" % err]

    # DN_STARTED = 0x8：设备节点已启动
    dn_started = 0x00000008
    # CM_REENUMERATE_SYNCHRONOUS = 0x1：同步重新枚举（返回时枚举已完成）
    sync = 0x00000001

    def locate(name=None):
        """按设备实例 ID 取设备节点；name 为 None 时取设备树根节点。"""
        node = ctypes.c_uint32(0)
        code = cfgmgr32.CM_Locate_DevNodeW(ctypes.byref(node), name, 0)
        return node.value if code == 0 else None

    def started(node):
        status = ctypes.c_uint32(0)
        problem = ctypes.c_uint32(0)
        code = cfgmgr32.CM_Get_DevNode_Status(ctypes.byref(status), ctypes.byref(problem), node, 0)
        return code == 0 and bool(status.value & dn_started)

    def wait_started(node, seconds):
        """驱动加载是异步的，等设备节点进入已启动状态（最多等 seconds 秒）。"""
        deadline = time.time() + seconds
        while True:
            if started(node):
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.5)

    root = locate()
    if root is None:
        return ["定位设备树根节点失败，已跳过设备重新枚举"]

    log = []
    node = None
    for attempt in range(1, attempts + 1):
        code = cfgmgr32.CM_Reenumerate_DevNode(root, sync)
        log.append("第 %d 次重新枚举设备（等效于「扫描检测硬件改动」）: %s" %
                   (attempt, "成功" if code == 0 else "失败(code=%s)" % code))
        if not uid:
            return log
        node = locate("ROOT\\SMARTCARDREADER\\%s" % uid)
        if node is not None:
            break
        if attempt == 1:
            # 兜底扫描：Win10 1903+ 的 pnputil 与上面这条 API 走的不是同一条路径
            code, output = run_command(["pnputil", "/scan-devices"], timeout=120)
            detail = "成功" if code == 0 else (output.splitlines()[0] if output else str(code))
            log.append("pnputil /scan-devices 兜底扫描: %s" % detail)
        time.sleep(1)

    if node is None:
        log.append("PnP 仍未创建 ROOT\\SMARTCARDREADER\\%s：设备节点建不出来时，"
                   "只能等重启系统后由系统重新枚举，重启后再执行一次还原即可完成绑定"
                   % uid)
        return log
    # 设备节点已存在也要重新枚举一次：让驱动重新加载并重新读取卡片数据，
    # 否则驱动里可能还停留在「卡片已被删除」的旧状态，读卡器会显示无卡。
    cfgmgr32.CM_Reenumerate_DevNode(node, sync)
    if wait_started(node, 8):
        log.append("卡片设备已就绪: ROOT\\SMARTCARDREADER\\%s" % uid)
    else:
        state, text = devnode_state(uid)
        log.append("卡片设备状态: %s（%s）" % (state, text))
    return log


def _opensc_tool(name):
    """定位随包分发的 OpenSC 工具（按程序根目录解析，见 ``Module.Paths``）。"""
    path = Paths.resource("OpenSC", name)
    return path if os.path.isfile(path) else ""


def _reader_index(uid=""):
    """用 OpenSC 的读卡器列表解析该卡对应的 pcsc 编号；找不到返回 -1。"""
    uid = instance_id(uid)
    tool = _opensc_tool("opensc-tool.exe")
    if not uid or not tool:
        return -1
    code, output = run_command([tool, "--list-readers"], timeout=60)
    name = "Microsoft Virtual Smart Card %d" % int(uid)
    for line in output.splitlines():
        text = line.strip()
        matched = re.match(r"^(\d+)\s", text)
        if not matched:
            continue
        if re.search(re.escape(name) + r"(?!\d)", text):
            return int(matched.group(1))
    return -1


def _card_key_objects(uid=""):
    """数据层自检：用 OpenSC 列出卡片上的密钥对象（不需要 PIN）。

    能列出私钥对象说明 store 里的卡文件系统（PKCS#15）已正确加载；
    「这把私钥能不能用」仍需用户用 PIN 做一次签名（见文档）。
    """
    index = _reader_index(uid)
    if index < 0:
        return "卡片私钥对象: 未找到读卡器，跳过"
    tool = _opensc_tool("pkcs15-tool.exe")
    if not tool:
        return "卡片私钥对象: 未找到 OpenSC\\pkcs15-tool.exe，跳过"
    code, output = run_command([tool, "--reader", str(index), "--list-keys"], timeout=60)
    keys = [line.strip() for line in output.splitlines() if line.strip().startswith("Private")]
    if not keys:
        detail = output.strip().splitlines()[0] if output.strip() else "退出码 %s" % code
        return "卡片私钥对象: 未发现（卡片数据可能不完整）: %s" % detail
    return "卡片私钥对象: %s" % "; ".join(keys[:3])


def reader_state(uid=""):
    """报告读卡器 / 卡片当前是否已被系统识别，返回 ``(state, text)``。

    与界面读卡器列表同一来源（OpenSC），因此需要智能卡服务在运行。state 取值：

        ``card``        读卡器已出现且卡片可识别（Card=Yes）
        ``reader_only`` 读卡器已出现但没有卡片（Card=No）
        ``absent``      读卡器尚未出现
        ``unknown``     无法判定（缺 OpenSC 或命令调用失败）

    用于区分「设备没建出来」「设备在、但卡片没加载」两种情况。
    """
    uid = instance_id(uid)
    if not uid:
        return "unknown", "读卡器状态未知：备份里没有实例编号"
    tool = _opensc_tool("opensc-tool.exe")
    if not tool:
        return "unknown", "读卡器状态未知：未找到 OpenSC\\opensc-tool.exe"
    code, output = run_command([tool, "--list-readers"], timeout=60)
    if code != 0 and not output:
        return "unknown", "读卡器状态未知：调用 %s 失败(%s)" % (tool, code)
    name = "Microsoft Virtual Smart Card %d" % int(uid)
    pattern = re.compile(re.escape(name) + r"(?!\d)")
    for line in output.splitlines():
        matched = pattern.search(line)
        if not matched:
            continue
        # pcsc 输出中卡片列固定为 Yes / No，位于读卡器名之前
        flag = line[:matched.start()].rstrip().lower()
        if flag.endswith("yes"):
            return "card", "读卡器已出现且卡片可识别: %s" % name
        if flag.endswith("no"):
            return "reader_only", "读卡器已出现但没有卡片: %s（设备或卡片数据未正确加载）" % name
        return "reader_only", "读卡器已出现: %s（无法确认卡片是否加载）" % name
    return "absent", "读卡器尚未出现: %s" % name


def _reader_state(uid=""):
    """兼容接口：等价于 ``reader_state(uid)[1]``，只返回文本。"""
    return reader_state(uid)[1]


def pcp_dir_of(rel):
    """``pcp/<索引>/...`` → 本机对应的 TPM 密钥索引目录；越界或格式不对返回空串。"""
    parts = str(rel or "").replace("\\", "/").split("/")
    if len(parts) < 3 or parts[0] != PCP_DIR:
        return ""
    try:
        index = int(parts[1])
    except ValueError:
        return ""
    if not 0 <= index < len(VSC_PCP_DIRS):
        return ""
    return VSC_PCP_DIRS[index]


def _restore_pcp_entry(reader, rel, item, log):
    """还原一个 TPM 密钥索引文件；已存在的同名文件不覆盖。

    换系统 / 重装场景下这张卡在**本机**根本没有索引，所以正常是"新建"；一旦同名
    文件已存在，说明本机已有同名 TPM 密钥索引，贸然覆盖可能弄坏本机其它 TPM 密钥
    （例如 Windows AIK），因此保留原样并记录。

    :return: 1 表示写入成功，0 表示跳过
    """
    folder = pcp_dir_of(rel)
    if not folder:
        log.append("跳过无法识别的 TPM 密钥索引条目: %s" % rel)
        return 0
    inner = "/".join(rel.replace("\\", "/").split("/")[2:])
    if not inner:
        return 0
    target = os.path.join(folder, *inner.split("/"))
    if os.path.exists(target):
        log.append("TPM 密钥索引已存在，按原样保留（未覆盖）: %s" % target)
        return 0
    try:
        data = reader.read(rel)
    except (KeyError, OSError) as err:
        log.append("读取备份里的 TPM 密钥索引失败，已跳过: %s (%s)" % (rel, err))
        return 0
    expect = str(item.get("sha256") or "")
    if expect and hashlib.sha256(data).hexdigest() != expect:
        log.append("TPM 密钥索引校验不通过，已跳过: %s" % rel)
        return 0
    try:
        # 复用卡片数据目录那套写入逻辑：创建父目录、去只读、必要时接管 ACL
        _write_data(data, target, log)
    except BackupError as err:
        log.append("写入 TPM 密钥索引失败，已跳过: %s (%s)" % (target, err))
        return 0
    log.append("已还原 TPM 密钥索引: %s" % target)
    return 1


def pcp_index_lines():
    """列出本机各候选目录下的 TPM 密钥索引文件（诊断用）。"""
    lines = []
    for index, folder in enumerate(VSC_PCP_DIRS):
        if not os.path.isdir(folder):
            lines.append("TPM 密钥索引目录[%d] 不存在: %s" % (index, folder))
            continue
        names = []
        for root, _, files in os.walk(folder):
            for name in sorted(files):
                if name.upper().endswith(".PCPKEY"):
                    names.append(os.path.relpath(os.path.join(root, name), folder))
        lines.append("TPM 密钥索引目录[%d] %s: %d 个 .PCPKEY %s"
                     % (index, folder, len(names), ", ".join(names[:6])))
    return lines


def _binding_ok(bound, guid):
    """判断设备当前的 store 绑定是否可用：绑定的目录必须真实存在，且（已知 GUID 时）
    必须就是备份里这张卡的 GUID。

    换系统（双系统 / 重装）后，注册表里可能残留旧的 store 路径（例如指向另一个
    系统盘的 ``...\\SmartCard\\Tpm\\<旧GUID>``），这时不能认为"已绑定"就跳过修复。
    """
    bound = str(bound or "")
    if not bound:
        return False
    tail = bound.replace("/", "\\").rstrip("\\").split("\\")[-1].lower()
    if guid and tail != str(guid).lower():
        return False
    return os.path.isdir(bound)


def _service_state(name=CARD_SERVICE):
    """读服务当前状态（``sc query``），失败返回空串。"""
    code, output = run_command(["sc", "query", name])
    matched = re.search(r"^\s*STATE\s*:\s*\d+\s+(\S+)", output, re.MULTILINE)
    return matched.group(1) if matched else ""


def log_dir():
    """还原 / 备份日志目录：``%APPDATA%\\TPMSmartCard\\logs``（与语言设置同一处）。

    装在 Program Files 下的程序目录通常不可写，用户目录才是稳妥位置。
    """
    base = os.environ.get("APPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "TPMSmartCard", "logs")


def save_log(lines, tag="restore"):
    """把日志行写入 ``%APPDATA%\\TPMSmartCard\\logs\\<tag>-<时间戳>.log``。

    GUI 程序没有控制台，``print`` 出来的还原 / 备份日志用户根本看不到，
    出问题时无法定位是「注册表没写进去」「设备没建出来」还是「绑定没写回」。
    落盘后界面把路径一并给出，用户可以直接把文件发出来。
    返回文件路径；写入失败返回空串。
    """
    try:
        folder = log_dir()
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(folder, "%s-%s.log" % (tag, stamp))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(str(item) for item in lines))
            handle.write("\n")
        return path
    except OSError as err:
        print("Save Log Error:", err)
        return ""


def _diagnostics(uid="", guid=""):
    """还原后的现场诊断：注册表项、数据目录、服务状态与目录清单。

    只做只读查询，任何一步失败都输出结论而不是抛异常——诊断本身不能打断还原。
    """
    uid = instance_id(uid)
    lines = ["---- 现场诊断 ----"]
    if uid:
        enum_key = "%s\\%s" % (VSC_ENUM_KEY, uid)
        code, _ = run_command(["reg", "query", enum_key])
        lines.append("设备枚举注册表项 %s: %s" % (enum_key, "存在" if code == 0 else "不存在"))
        reader_key = "%s\\Microsoft Virtual Smart Card %d" % (VSC_READER_KEY, int(uid))
        code, _ = run_command(["reg", "query", reader_key])
        lines.append("读卡器注册项 %s: %s" % (reader_key, "存在" if code == 0 else "不存在"))
    else:
        lines.append("备份里没有实例编号，跳过注册表项检查")
    lines.append("卡片数据目录 %s: %s"
                 % (VSC_STORE_DIR, {"ok": "可访问", "missing": "不存在",
                                    "denied": "无法访问（需要管理员权限）"}[store_state()]))
    if guid:
        target = os.path.join(VSC_STORE_DIR, guid)
        if os.path.isdir(target):
            names = sorted(os.listdir(target))
            lines.append("卡片数据目录 %s: 存在，含 %d 个条目 %s"
                         % (target, len(names), ", ".join(names[:8])))
        else:
            lines.append("卡片数据目录 %s: 不存在（备份未写进去）" % target)
    lines.append("智能卡服务 %s: %s" % (CARD_SERVICE, _service_state() or "查询失败"))
    state, text = devnode_state(uid)
    lines.append("设备节点 ROOT\\SMARTCARDREADER\\%s: %s（%s）" % (uid, state, text))
    lines.append("设备绑定的 store 路径: %s" % (device_store_path(uid) or "（空）"))
    props = read_device_properties(uid)
    vendor = vendor_property_count(props)
    lines.append("设备属性: %d 项，其中厂商卡片身份 %d 项%s"
                 % (len(props), vendor,
                    "" if vendor else "  ← 缺少卡片身份属性，读卡器不会被发布到 PC/SC"))
    lines.extend(pcp_index_lines())
    return lines


def _restore_verdict(dev_state, reader_code_, bound, guid):
    """把设备节点状态 / 读卡器状态 / store 绑定合成一句可执行的结论。"""
    if reader_code_ == "card":
        return "成功：读卡器已出现且卡片可识别，可以直接使用（建议用 PIN 做一次签名验证私钥）"
    if dev_state == "missing":
        return ("设备节点没能建出来：注册表已写回，但系统没有把它枚举成设备"
                "（工具已尝试用 SetupDi 重建，结果见日志）。请把日志发出来定位；"
                "重启系统后再执行一次还原也可能完成")
    if reader_code_ == "reader_only":
        if not _binding_ok(bound, guid):
            return ("读卡器已出现但卡片没加载：设备到 store 目录的绑定没有生效。"
                    "重启系统后再执行一次还原即可完成绑定")
        return ("读卡器已出现但卡片没加载：store 绑定正常，问题在卡片数据或 TPM 密钥。"
                "请确认备份与 TPM 均来自同一台机器（换机 / 清过 TPM 时私钥无法恢复）")
    if reader_code_ == "absent":
        return ("读卡器未出现（设备节点状态 %s）：设备建出来了但驱动没有向 PC/SC 发布读卡器。"
                "最常见原因是缺少该卡片的「卡片身份属性」或「TPM 密钥索引」——"
                "换系统 / 重装时需要备份里带上它们（见诊断里的「设备属性」「TPM 密钥索引目录」）。"
                "请把日志发出来定位" % dev_state)
    return "无法判定结果，请查看下方日志与诊断信息"


def restore_backup(package, force=False):
    """从 ``.tsb`` 备份文件还原一张 TPM 虚拟智能卡。

    :param package: ``.tsb`` 备份文件路径
    :param force: TPM 指纹与本机不一致时是否强制还原（界面确认后传 True）
    :return: 报告字典 ``{"card", "instance", "file_count", "reg_count", "stale",
             "tpm_state", "key_state", "dev_state", "reader_state", "bound",
             "verdict", "log_file", "log"}``。其中 ``log`` 是「结论 + 逐条日志 +
             现场诊断」的完整列表（界面直接展示），并已落盘到 ``log_file``。
    :raises BackupError: 权限不足 / 备份无效 / TPM 不一致且未强制 / 写入失败
    """
    if not is_admin():
        raise BackupError("需要管理员权限：请以管理员身份运行本工具后再还原")

    with _PackageReader(package) as reader:
        manifest = read_manifest(package, reader)
        card = manifest.get("card") or {}
        card_name = card.get("name") or ""
        uid = instance_id(card.get("instance"))
        tpm_state, tpm_text = check_tpm(manifest)
        log = ["TPM 校验: %s" % tpm_text]
        if tpm_state == "mismatch":
            if not force:
                raise BackupError("备份的 TPM 与本机不一致，已中止还原"
                                  "（确认风险后可强制还原）：%s" % tpm_text)
            log.append("已按用户确认强制还原（TPM 不一致）")

        # 写文件前先停掉智能卡服务：服务（LocalService）会打开卡片数据目录，
        # 此时覆盖写入会报 [Errno 13] Permission denied。
        log.append(_service("stop"))
        try:
            # ---- 1. 校验备份文件并回写 ------------------------------------ #
            # 备份包内 files/ 的相对结构就是卡片数据目录（Tpm）的相对结构，
            # 因此固定还原到本机数据目录，避免备份记录的是别的机器路径。
            stale = []
            file_count = 0
            pcp_count = 0
            entries = manifest.get("files") or []
            if entries:
                if store_state() == "denied":
                    raise BackupError("无权访问卡片数据目录，请以管理员身份运行本工具: %s"
                                      % VSC_STORE_DIR)
                for item in entries:
                    rel = str(item.get("path") or "").replace("\\", "/")
                    if rel.startswith(PCP_DIR + "/"):
                        # TPM 密钥索引：换系统 / 重装后卡片能不能起来靠它
                        pcp_count += _restore_pcp_entry(reader, rel, item, log)
                        continue
                    if not rel.startswith(FILES_DIR + "/"):
                        continue
                    inner = rel[len(FILES_DIR) + 1:]
                    if not reader.exists(rel):
                        raise BackupError("备份文件缺失: %s" % rel)
                    data = reader.read(rel)
                    expect = str(item.get("sha256") or "")
                    if expect and hashlib.sha256(data).hexdigest() != expect:
                        stale.append(inner)
                    target = os.path.join(VSC_STORE_DIR, *inner.split("/"))
                    _write_data(data, target, log)
                    file_count += 1
                log.append("已还原卡片数据文件: %d 个" % file_count)
                if pcp_count:
                    log.append("已还原 TPM 密钥索引文件: %d 个" % pcp_count)
            else:
                log.append("备份中没有卡片数据文件，仅还原注册表")

            # ---- 2. 还原注册表（reg import 需要一个真实的 .reg 文件） ------- #
            reg_count = 0
            with tempfile.TemporaryDirectory(prefix="tpmvsc-reg-") as reg_dir:
                for item in manifest.get("registry") or []:
                    rel = str(item.get("file") or "").replace("\\", "/")
                    if not reader.exists(rel):
                        log.append("注册表备份缺失，已跳过: %s" % item.get("file"))
                        continue
                    reg_file = os.path.join(reg_dir, os.path.basename(rel) or "restore.reg")
                    try:
                        with open(reg_file, "wb") as handle:
                            handle.write(reader.read(rel))
                    except OSError as err:
                        log.append("写入临时注册表文件失败，已跳过: %s (%s)" % (rel, err))
                        continue
                    code, output = run_command(["reg", "import", reg_file])
                    if code != 0:
                        log.append("导入注册表失败: %s (%s)" % (item.get("key"), output))
                        continue
                    reg_count += 1
                    log.append("已导入注册表: %s" % item.get("key"))
        finally:
            # ---- 3. 启动服务，读卡器列表需要智能卡服务在运行 -------------- #
            log.append(_service("start"))

    # ---- 4. 让 PnP 重新枚举设备：注册表项只是写回了磁盘，PnP 的内存设备树上
    # 还没有这个节点，必须先重新枚举（扫描检测硬件改动） -------------------- #
    log.extend(_rescan_devices(uid))

    # ---- 4b. 重新枚举建不出来就自己建：实测（同机换系统还原）光有 Enum 项，
    # CM_Reenumerate_DevNode / pnputil /scan-devices 都不会创建该设备节点，
    # 读卡器于是永远不出现；改用 SetupDi 设备注册接口重建（devcon install 那套）-- #
    dev_state, dev_text = devnode_state(uid)
    if dev_state == "missing":
        log.append("PnP 没有创建 ROOT\\SMARTCARDREADER\\%s 设备节点（%s），"
                   "改用 SetupDi 设备注册接口重建" % (uid, dev_text))
        cleaned, text = drop_orphan_enum_key(uid)
        log.append(text)
        if cleaned:
            made, text = register_card_device(uid, card_name)
            log.append(text)
            if made:
                log.extend(_rescan_devices(uid))
                dev_state, dev_text = devnode_state(uid)
                log.append("重建后设备节点状态: %s（%s）" % (dev_state, dev_text))
    else:
        log.append("设备节点状态: %s（%s）" % (dev_state, dev_text))

    # ---- 4c. 写回厂商设备属性（卡片身份：卡片名 + 卡片 GUID）-------------- #
    # 这些属性在 Enum 下受 ACL 保护的 Properties 子键里，reg import 带不回来；
    # 实测缺了它们，驱动虽然启动了却不会向 PC/SC 发布读卡器（设备接口都不建），
    # 表现就是"还原成功但卡片没出现"。写完再重新枚举一次让驱动重新读取。
    if dev_state != "missing":
        props = write_device_properties(uid, manifest.get("device_properties"),
                                        source_root=manifest.get("system_root") or "")
        log.extend(props)
        log.extend(_rescan_devices(uid))

    # ---- 5. 设备就绪后再重启一次服务，刷新读卡器列表 ---------------------- #
    log.append(_service("stop"))
    log.append(_service("start"))

    # ---- 6. 报告读卡器 / 卡片的真实状态（与界面同一来源） ------------------ #
    reader_code, reader_text = reader_state(uid)
    log.append(reader_text)

    # ---- 7. 修复「设备实例 → store 目录」绑定 ------------------------------ #
    # 该绑定是设备属性（存在 Enum 下受 ACL 保护的 Properties 子键里），注册表备份
    # 里通常没有它；设备节点已存在时可以用 PnP 属性接口直接写回，写完让驱动重新加载。
    guid = str((manifest.get("store") or {}).get("guid") or "") or card_store_guid(uid)
    bound = device_store_path(uid)
    if _binding_ok(bound, guid):
        log.append("设备已绑定 store: %s" % bound)
    elif not guid:
        log.append("备份里没有 store GUID，跳过设备绑定修复")
    else:
        target = os.path.join(VSC_STORE_DIR, guid) + os.sep
        if bound:
            # 换系统后注册表里可能残留旧路径，绑定到别的系统盘或别的卡时必须纠正
            log.append("设备当前绑定的 store 不是备份里的这张卡（%s），按备份写回: %s"
                       % (bound, target))
        ok, text = set_device_store_path(uid, target)
        if ok:
            log.append("已写回设备属性（store 路径）: %s（%s）" % (target, text))
            log.extend(_rescan_devices(uid))
            reader_code, reader_text = reader_state(uid)
            log.append(reader_text)
        else:
            log.append("未能写回设备属性（store 路径）: %s" % text)
    bound = device_store_path(uid)

    # ---- 8. 自检：卡片上的私钥对象（数据层）+ TPM 密钥（信息，不下负面断言） -- #
    log.append(_card_key_objects(uid))
    key_state, key_text = tpm_key_report(guid)
    log.append("TPM 密钥自检: %s" % key_text)

    # ---- 9. 结论 + 现场诊断 + 日志落盘 ------------------------------------ #
    # 界面是 GUI，没有控制台；只弹一句「已完成」的话，用户完全不知道失败在哪一步
    # （注册表没写进去 / 设备没建出来 / 绑定没写回 / 卡片没加载），因此这里把结论、
    # 逐条日志与诊断信息一起返回，并落盘成文件。
    dev_state, dev_text = devnode_state(uid)
    log.append("设备节点状态: %s（%s）" % (dev_state, dev_text))
    verdict = _restore_verdict(dev_state, reader_code, bound, guid)
    report_log = ["还原结论: %s" % verdict, "备份文件: %s" % os.path.abspath(str(package))]
    report_log.extend(log)
    report_log.extend(_diagnostics(uid, guid))
    log_file = save_log(report_log, tag="restore")
    report_log.append("还原日志文件: %s" % (log_file or "（写入失败）"))

    print("\n".join(report_log))
    return {
        "card": card_name,
        "instance": uid,
        "file_count": file_count,
        "reg_count": reg_count,
        "stale": stale,
        "tpm_state": tpm_state,
        "key_state": key_state,
        "dev_state": dev_state,
        "reader_state": reader_code,
        "bound": bound,
        "verdict": verdict,
        "log_file": log_file,
        "log": report_log,
    }


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
def _main():
    state_text = {"ok": "可访问", "missing": "不存在", "denied": "无法访问（需要管理员权限）"}
    print("管理员权限: %s" % is_admin())
    print("卡片数据目录: %s (%s)" % (VSC_STORE_DIR, state_text[store_state()]))
    cards = list_cards()
    print("已注册虚拟智能卡: %d" % len(cards))
    for card in cards:
        print("  [%s] %s" % (card["instance"], card["name"] or "(未命名)"))
    for line in store_index():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
