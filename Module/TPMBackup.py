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
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess

from Module.Version import VERSION

# 备份包格式版本（后续结构变化时递增，还原时校验）
BACKUP_FORMAT = 1
# 备份清单文件名
MANIFEST_NAME = "tpmvsc-backup.json"
# 备份包内子目录
FILES_DIR = "files"
REGISTRY_DIR = "registry"

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
    """在卡片数据目录中定位属于某张卡的条目（文件或目录名）。

    目录内部布局未在公开资料中定义，因此这里按「条目名包含实例编号或卡片名称」
    做自适应匹配；匹配不到时返回空列表，由调用方决定退化为整目录备份。
    需要管理员权限，权限不足时抛 BackupError。
    """
    try:
        entries = sorted(os.listdir(VSC_STORE_DIR))
    except PermissionError as err:
        raise BackupError("读取卡片数据目录失败（需要管理员权限）: %s" % err)
    except OSError as err:
        raise BackupError("读取卡片数据目录失败: %s" % err)
    target_uid = instance_id(uid)
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


def _collect_files(source_root):
    """遍历 source_root，返回 [(相对路径, 绝对路径, 大小, sha256)]。"""
    results = []
    for root, dirs, files in os.walk(source_root):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, source_root)
            try:
                size = os.path.getsize(full)
                sha = _sha256(full)
            except OSError as err:
                raise BackupError("读取文件失败: %s (%s)" % (full, err))
            results.append((rel.replace("\\", "/"), full, size, sha))
    return results


def create_backup(dest_dir, name="", uid=""):
    """把一张 TPM 虚拟智能卡的「文件 + 注册表」备份到 ``dest_dir``。

    :param dest_dir: 备份保存目录（不存在会自动创建）
    :param name: 卡片名称（界面选中的名称）
    :param uid: 卡片实例编号（如 ``0000``），为空时按名称匹配
    :return: 报告字典 ``{"dir", "card", "scope", "file_count", "size", "reg_count", "log"}``
    :raises BackupError: 权限不足 / 卡片未找到 / 目录不可写等
    """
    if not is_admin():
        raise BackupError("需要管理员权限：请以管理员身份运行本工具后再备份")

    card = find_card(name=name, uid=uid)
    if card is None:
        raise BackupError("未在注册表中找到该虚拟智能卡，请确认卡片名称或实例编号")
    card_name = card["name"] or name or ("卡 %s" % card["instance"])

    dest_dir = os.path.abspath(dest_dir)
    package = os.path.join(dest_dir, "%s-%s" % (normalize_name(card_name), card["instance"]))
    files_root = os.path.join(package, FILES_DIR)
    reg_root = os.path.join(package, REGISTRY_DIR)
    log = []

    try:
        os.makedirs(files_root, exist_ok=True)
        os.makedirs(reg_root, exist_ok=True)
    except OSError as err:
        raise BackupError("创建备份目录失败: %s" % err)

    # ---- 1. 卡片数据目录 -------------------------------------------------- #
    scope = "none"
    entries = []
    warning = ""
    copied = []
    state = store_state()
    if state == "denied":
        raise BackupError("无权访问卡片数据目录，请以管理员身份运行本工具: %s" % VSC_STORE_DIR)
    if state == "ok":
        entries = locate_card_entries(card_name, card["instance"])
        try:
            if entries:
                # 命中与当前卡相关的条目：按条目逐个备份
                scope = "card"
                for entry in entries:
                    source = os.path.join(VSC_STORE_DIR, entry)
                    target = os.path.join(files_root, entry)
                    if os.path.isdir(source):
                        shutil.copytree(source, target, dirs_exist_ok=True)
                    else:
                        shutil.copy2(source, target)
                    log.append("已备份卡片数据条目: %s" % entry)
            else:
                # 无法定位到具体条目：退化为整目录备份（还原时会覆盖整个数据目录）
                scope = "store"
                shutil.copytree(VSC_STORE_DIR, files_root, dirs_exist_ok=True)
                warning = ("未能在数据目录中按名称定位到本卡条目，已整目录备份；"
                           "还原时会覆盖整个卡片数据目录，请仅在本机所有卡片均来自"
                           "同一份备份时还原")
                log.append("未能按名称定位到具体条目，已整目录备份: %s" % VSC_STORE_DIR)
        except PermissionError as err:
            raise BackupError("复制卡片数据失败（需要管理员权限）: %s" % err)
        except OSError as err:
            raise BackupError("复制卡片数据失败: %s" % err)
        copied = _collect_files(files_root)
    else:
        log.append("卡片数据目录不存在，跳过文件备份: %s" % VSC_STORE_DIR)

    # 数据目录清单（诊断用，便于确认目录内部布局）
    index_lines = store_index()
    try:
        with open(os.path.join(package, "store-index.txt"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(index_lines))
    except OSError as err:
        log.append("写入数据目录清单失败（已跳过）: %s" % err)

    # ---- 2. 注册表 -------------------------------------------------------- #
    registry = []
    keys = [("SMARTCARDREADER-%s" % card["instance"], "%s\\%s" % (VSC_ENUM_KEY, card["instance"]))]
    reader_key = "%s\\Microsoft Virtual Smart Card %d" % (VSC_READER_KEY, int(card["instance"]))
    code, _ = run_command(["reg", "query", reader_key])
    if code == 0:
        keys.append(("CalaisReader-%s" % card["instance"], reader_key))
    for tag, key in keys:
        reg_file = os.path.join(reg_root, "%s.reg" % tag)
        code, output = run_command(["reg", "export", key, reg_file, "/y"])
        if code != 0:
            log.append("导出注册表失败（已跳过）: %s" % key)
            if os.path.isfile(reg_file):
                os.remove(reg_file)
            continue
        registry.append({"key": key, "file": "%s/%s.reg" % (REGISTRY_DIR, tag)})
        log.append("已导出注册表: %s" % key)
    if not registry:
        raise BackupError("注册表导出失败：未拿到任何卡片设备节点，请确认卡片存在且以管理员运行")

    # ---- 3. 清单 ---------------------------------------------------------- #
    total = sum(item[2] for item in copied)
    manifest = {
        "format": BACKUP_FORMAT,
        "tool": "TPMSmartCard",
        "tool_version": VERSION,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "computer": socket.gethostname(),
        "card": {
            "name": card_name,
            "instance": card["instance"],
            "enum_key": "%s\\%s" % (VSC_ENUM_KEY, card["instance"]),
        },
        "store": {
            "dir": VSC_STORE_DIR,
            "scope": scope,
            "entries": entries,
            "index": "store-index.txt",
        },
        "registry": registry,
        "files": [{"path": "%s/%s" % (FILES_DIR, rel), "size": size, "sha256": sha}
                  for rel, _, size, sha in copied],
        "notes": [
            "卡片私钥由 TPM 保护，磁盘上只有 TPM 封装后的数据，本备份仅在"
            "同一台电脑且同一 TPM（未清除）上可以还原。",
            "换机或清除 TPM 后无法还原，请同时保留卡片名称、PIN、PUK 与管理密码。",
        ] + ([warning] if warning else []),
    }
    manifest_path = os.path.join(package, MANIFEST_NAME)
    try:
        with open(manifest_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest, ensure_ascii=False, indent=2))
    except OSError as err:
        raise BackupError("写入备份清单失败: %s" % err)

    print("\n".join(log))
    return {
        "dir": package,
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
def read_manifest(package_dir):
    """读取备份清单并做基本校验。"""
    path = os.path.join(package_dir, MANIFEST_NAME)
    if not os.path.isfile(path):
        raise BackupError("该目录不是本工具的备份：缺少 %s" % MANIFEST_NAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            manifest = json.loads(handle.read())
    except (OSError, ValueError) as err:
        raise BackupError("备份清单无法解析: %s" % err)
    if not isinstance(manifest, dict) or "card" not in manifest:
        raise BackupError("备份清单内容不完整")
    if int(manifest.get("format", 0)) > BACKUP_FORMAT:
        raise BackupError("备份包版本高于当前程序，请升级本工具后再还原")
    return manifest


def _restart_service():
    """尽力重启智能卡服务，让还原后的卡片重新被枚举。"""
    log = []
    code, output = run_command(["sc", "stop", CARD_SERVICE])
    log.append("停止服务 %s: %s" % (CARD_SERVICE, output.splitlines()[0] if output else code))
    code, output = run_command(["sc", "start", CARD_SERVICE])
    log.append("启动服务 %s: %s" % (CARD_SERVICE, output.splitlines()[0] if output else code))
    return log


def restore_backup(package_dir):
    """从备份目录还原一张 TPM 虚拟智能卡（文件 + 注册表）。

    :return: 报告字典 ``{"card", "instance", "file_count", "reg_count", "log", "stale"}``
    :raises BackupError: 权限不足 / 备份无效 / 写入失败
    """
    if not is_admin():
        raise BackupError("需要管理员权限：请以管理员身份运行本工具后再还原")

    package_dir = os.path.abspath(package_dir)
    manifest = read_manifest(package_dir)
    card = manifest.get("card") or {}
    card_name = card.get("name") or ""
    uid = instance_id(card.get("instance"))
    log = []

    # ---- 1. 校验备份文件并回写 -------------------------------------------- #
    # 备份包内 files/ 的相对结构就是卡片数据目录（Tpm）的相对结构，
    # 因此固定还原到本机数据目录，避免备份记录的是别的机器路径。
    source_root = os.path.join(package_dir, FILES_DIR)
    stale = []
    file_count = 0
    if os.path.isdir(source_root):
        if store_state() == "denied":
            raise BackupError("无权访问卡片数据目录，请以管理员身份运行本工具: %s" % VSC_STORE_DIR)
        for item in manifest.get("files") or []:
            rel = str(item.get("path") or "").replace("\\", "/")
            if not rel.startswith(FILES_DIR + "/"):
                continue
            inner = rel[len(FILES_DIR) + 1:]
            source = os.path.join(package_dir, *rel.split("/"))
            if not os.path.isfile(source):
                raise BackupError("备份文件缺失: %s" % rel)
            expect = str(item.get("sha256") or "")
            if expect and _sha256(source) != expect:
                stale.append(inner)
            target = os.path.join(VSC_STORE_DIR, *inner.split("/"))
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)
            except PermissionError as err:
                raise BackupError("写入卡片数据失败（需要管理员权限，且建议先删除同名卡片）: %s" % err)
            except OSError as err:
                raise BackupError("写入卡片数据失败: %s\n请先删除同名卡片或重启系统后重试" % err)
            file_count += 1
        log.append("已还原卡片数据文件: %d 个" % file_count)
    else:
        log.append("备份中没有卡片数据文件，仅还原注册表")

    # ---- 2. 还原注册表 ---------------------------------------------------- #
    reg_count = 0
    for item in manifest.get("registry") or []:
        reg_file = os.path.join(package_dir, *(str(item.get("file") or "").replace("\\", "/").split("/")))
        if not os.path.isfile(reg_file):
            log.append("注册表备份缺失，已跳过: %s" % item.get("file"))
            continue
        code, output = run_command(["reg", "import", reg_file])
        if code != 0:
            log.append("导入注册表失败: %s (%s)" % (item.get("key"), output))
            continue
        reg_count += 1
        log.append("已导入注册表: %s" % item.get("key"))

    # ---- 3. 重启服务，让卡片重新枚举 -------------------------------------- #
    log.extend(_restart_service())

    print("\n".join(log))
    return {
        "card": card_name,
        "instance": uid,
        "file_count": file_count,
        "reg_count": reg_count,
        "stale": stale,
        "log": log,
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
