# -*- coding: utf-8 -*-
"""FIDO2 凭据与 ``.tsb`` 备份的衔接。

需求是「凭据存在系统里，但备份卡片时要一起备份、一起还原」：

* 备份：把本机该卡的凭据库导出成一份 JSON 放进 ``.tsb`` 的 ``fido/`` 目录。
  导出时会**剥掉**仅本机可用的 DPAPI 外层（换系统后那层必然失效），
  留下仍然需要「卡片 PIN」才能解开的内层密文；
* 还原：读回 JSON，用**目标机**的 DPAPI 重新封装外层写进本机凭据库。
  凭据内层（``tempKeyEnc`` / ``inner``）原样保留，所以还原后输同一个 PIN
  就能继续用这些 passkey。

安全提示：备份包因此包含「用 PIN 封装的 FIDO 私钥」，与包里已有的卡片
keymaps / PIN 映射明文属于同一敏感级别——这一点会写进备份清单的 notes。
"""

import json
import os

from Module import FidoStore

# 备份包内的目录名（与 files/ registry/ pcp/ dpapi/ 同级）
FIDO_DIR = "fido"


def _store_of_card(guid="", name=""):
    """在已有凭据库里找出属于这张卡的那一份。"""
    candidates = []
    for store in FidoStore.FidoStore.list_all():
        card = store.card
        if guid and str(card.get("guid") or "").lower() == str(guid).lower():
            candidates.append(store)
            continue
        if name and str(card.get("name") or "") == str(name):
            candidates.append(store)
    if not candidates:
        return None
    # 万一多条命中（换过 GUID 的残留），取凭据最多的那条
    candidates.sort(key=lambda item: len(item.credentials), reverse=True)
    return candidates[0]


def collect(guid="", name=""):
    """导出某张卡的 FIDO2 凭据。

    :return: ``(section, files, log)``；``section`` 为 ``None`` 表示该卡没有凭据。
        ``files`` 是 ``[(包内路径, 字节)]``，由调用方写进 zip。
    """
    log = []
    store = _store_of_card(guid, name)
    if store is None or not store.credentials:
        log.append("该卡片没有 FIDO2 凭据（跳过）")
        return None, [], log

    payload, warnings = store.export_for_backup()
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    arcname = "%s/%s.json" % (FIDO_DIR, store.key)
    section = {
        "key": store.key,
        "file": arcname,
        "count": len(store.credentials),
        "card": store.card,
        "exported_at": payload.get("exported_at"),
        "size": len(content),
    }
    log.append("已备份 FIDO2 凭据 %d 条（%s）" % (len(store.credentials), store.display_name))
    log.extend(warnings)
    return section, [(arcname, content)], log


def restore(reader, section, guid="", log=None):
    """把备份里的 FIDO2 凭据写回本机；返回 ``(新增条数, 跳过条数)``。"""
    log = log if log is not None else []
    if not section:
        log.append("备份里没有 FIDO2 凭据（跳过）")
        return 0, 0
    rel = str(section.get("file") or "").replace("\\", "/")
    if not rel or not reader.exists(rel):
        log.append("FIDO2 凭据文件在备份包里缺失（跳过）: %s" % rel)
        return 0, 0
    try:
        payload = json.loads(reader.read(rel).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as err:
        log.append("FIDO2 凭据文件无法解析（跳过）: %s (%s)" % (rel, err))
        return 0, 0

    card = payload.get("card") or {}
    target_guid = str(guid or card.get("guid") or "")
    # 用 resolve 而不是 open：还原后设备节点的 store GUID 可能已经变了，
    # 但凭据还在按旧 key 存的库里，按 serial / 读卡器名兜底找回同一份库
    store = FidoStore.FidoStore.resolve(target_guid, card.get("serial", ""),
                                        card.get("name", ""), create=True)
    try:
        added, skipped, warnings = store.import_from_backup(payload)
    except FidoStore.StoreError as err:
        log.append("FIDO2 凭据还原失败: %s" % err)
        return 0, 0
    log.append("已还原 FIDO2 凭据: 新增 %d 条，跳过 %d 条" % (added, skipped))
    log.extend(warnings)
    if added:
        log.append("提示：FIDO2 凭据仍由卡片 PIN 保护，第一次使用时需要用卡片 PIN 解锁；"
                   "若 PIN 已修改，改用新 PIN 即可")
        log.append("首次认证时会弹窗要求选择卡片并输入 PIN（还原后本机解锁材料需要重建一次）")
    # 正在跑的服务里可能还留着还原前的会话/卡片缓存：不刷新的话会出现
    # 「刚还原的凭据在认证时找不到」（内存副本覆盖磁盘视图）
    invalidate_service(log)
    return added, skipped


def invalidate_service(log=None):
    """让 FIDO2 服务丢掉会话与卡片缓存（还原 / 删卡之后调用）。"""
    log = log if log is not None else []
    try:
        from Module.FidoService import FidoService
        FidoService.get().invalidate()
    except Exception as err:                  # 服务还没起来 / 未启用 FIDO2：不影响还原
        log.append("FIDO2 服务未运行，跳过缓存刷新: %s" % err)
    return None


def summary_text(section):
    """给备份报告用的一句话摘要。"""
    if not section:
        return "无 FIDO2 凭据"
    return "FIDO2 凭据 %d 条（%s）" % (int(section.get("count") or 0),
                                     os.path.basename(str(section.get("file") or "")))
