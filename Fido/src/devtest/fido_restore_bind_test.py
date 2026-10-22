# -*- coding: utf-8 -*-
"""「备份 → 删除凭据 → 还原卡片」之后 FIDO2 还能不能用的自检（不需要真卡）。

覆盖两个曾经的故障点：

1. 还原之后本机没有解锁材料（``guard`` / ``pin_verifier``）：clientPIN 的
   getPINToken 流程拿不到 PIN 原文，于是平台只会报「PIN 不可用 / 找不到凭据」。
   期望：后端主动要求用户「选卡 + 输 PIN」，输一次之后材料自动重建；
2. 多卡机器上不知道该用哪张卡：期望按「哪张卡上有这条凭据」自动挑卡，
   挑不出来（例如注册新凭据）才让用户选。

用法::

    python Fido/src/devtest/fido_restore_bind_test.py
"""
import base64
import hashlib
import json
import os
import secrets
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from Module import FidoBackup                                          # noqa: E402
from Module import FidoCbor                                            # noqa: E402
from Module import FidoCtap                                            # noqa: E402
from Module import FidoIpc                                             # noqa: E402
from Module import FidoStore                                           # noqa: E402
from Module.FidoService import FidoService                            # noqa: E402

PIN = "12345678"
CARD_NAME = "Microsoft Virtual Smart Card 0"
SERIAL = "aabbccdd"
GUID = "5f2a7c31-0000-4000-8000-00000000beef"
RP_ID = "example.com"


class FakePackage:
    """最小化的 .tsb 读取器（只实现 exists/read）。"""

    def __init__(self, files):
        self.files = dict(files)

    def exists(self, rel):
        return str(rel).replace("\\", "/") in self.files

    def read(self, rel):
        return self.files[str(rel).replace("\\", "/")]


def fake_cards(_include_disabled=False, use_cache=True):
    """按磁盘上的真实状态回卡片列表（bound 由 guard 是否存在决定）。"""
    store = FidoStore.FidoStore.resolve(GUID, SERIAL, CARD_NAME, create=False)
    return [{"name": CARD_NAME, "uuid": SERIAL, "reader": 0,
             "key": store.key if store else FidoStore.card_key(GUID, SERIAL, CARD_NAME),
             "guid": GUID, "serial": SERIAL, "enabled": True,
             "bound": bool(store is not None and store.bound),
             "count": len(store.credentials) if store else 0}]


OTHER_NAME = "Microsoft Virtual Smart Card 1"
OTHER_GUID = "11111111-2222-4333-8444-555555555555"
OTHER_SERIAL = "11223344"


def fake_two_cards(_include_disabled=False, use_cache=True):
    """两块卡：第二块卡上没有任何与 RP_ID 相关的凭据。"""
    items = fake_cards(use_cache=use_cache)
    store = FidoStore.FidoStore.resolve(OTHER_GUID, OTHER_SERIAL, OTHER_NAME,
                                        create=False)
    items.append({"name": OTHER_NAME, "uuid": OTHER_SERIAL, "reader": 1,
                  "key": store.key if store else FidoStore.card_key(
                      OTHER_GUID, OTHER_SERIAL, OTHER_NAME),
                  "guid": OTHER_GUID, "serial": OTHER_SERIAL, "enabled": True,
                  "bound": bool(store is not None and store.bound),
                  "count": len(store.credentials) if store else 0})
    return items


def ga_params(credential_id):
    return {
        1: RP_ID,
        2: hashlib.sha256(b"restore-challenge").digest(),
        3: [{"type": "public-key", "id": credential_id}],
    }


def dispatch(service, cmd, payload):
    return service.dispatch(cmd, json.dumps(payload).encode())


def main():
    folder = tempfile.mkdtemp(prefix="tpmsc-fido-restore-")
    original_cards, original_settings = FidoStore.cards_dir, FidoStore.settings_path
    FidoStore.cards_dir = lambda: folder
    FidoStore.settings_path = lambda: os.path.join(folder, "settings.json")
    failures = []

    def check(name, condition, detail=""):
        print("%s %s%s" % ("[OK]  " if condition else "[失败]", name,
                           ("  → " + str(detail)) if detail else ""))
        if not condition:
            failures.append(name)

    try:
        # ---- 1. 正常状态：注册一条 passkey，clientPIN 已经绑定过 -------------- #
        store = FidoStore.FidoStore.open(GUID, SERIAL, CARD_NAME)
        master = store.unlock(PIN)
        store.set_pin_verifier(PIN)
        store.remember_master(master)
        credential_id = secrets.token_bytes(32)
        store.add_credential(master, {
            "rp_id": RP_ID, "rp_name": "Example", "user_name": "alice",
            "credential_id": FidoStore.b64url(credential_id), "algorithm": -7,
            "counter": 0,
        }, bytes([1]) + secrets.token_bytes(32))
        check("准备：凭据已注册且本机已绑定", store.bound and store.has_pin_verifier)

        # ---- 2. 备份 → 删除凭据（连本机解锁材料一起没了）→ 还原 -------------- #
        section, files, _log = FidoBackup.collect(guid=GUID, name=CARD_NAME)
        check("导出：备份里有 1 条凭据", int(section.get("count") or 0) == 1)
        store.delete_credential(store.credentials[0]["uuid"])
        store.delete_file()                  # 最坏情况：凭据库整个丢了
        logs = []
        added, _skipped = FidoBackup.restore(FakePackage(files), section,
                                             guid=GUID, log=logs)
        check("还原：凭据写回", added == 1, logs)
        restored = FidoStore.FidoStore.load(store.key)
        check("还原：凭据库存在", restored is not None)
        check("还原：本机解锁材料待重建", restored is not None
              and not restored.bound and not restored.has_pin_verifier)

        # ---- 3. 认证请求：应要求用户选卡+输 PIN，而不是报「PIN 不可用」-------- #
        service = FidoService()
        service.cards = fake_cards
        service.verify_pin = lambda reader, pin: ("ok", "selftest")
        service.update_settings(pin_mode="clientpin")
        params = FidoCbor.encode(ga_params(credential_id))

        reply = dispatch(service, FidoIpc.CMD_GET_ASSERTION,
                         {"cbor_req": base64.b64encode(params).decode()})
        data = reply.get("data") or {}
        check("首次认证：要求 PIN（0x36）", reply.get("rv") == FidoCtap.CTAP2_ERR_PIN_REQUIRED,
              hex(reply.get("rv") or 0))
        check("首次认证：由本程序弹窗（platform_pin=False）",
              data.get("platform_pin") is False, data)
        check("首次认证：弹窗能选卡", len(data.get("cards") or []) == 1, data.get("cards"))

        # ---- 4. 用户在弹窗里输 PIN：卡片校验通过后重建解锁材料 ----------------- #
        login = dispatch(service, FidoIpc.CMD_LOGIN, {"card_uuid": SERIAL, "pin": PIN})
        check("登录：卡片校验通过", login.get("rv") == 0, login)
        restored = FidoStore.FidoStore.load(store.key)
        check("登录后：解锁材料已重建",
              restored is not None and restored.bound and restored.has_pin_verifier)

        # ---- 5. 同一次会话里重试：不再要求平台再输一次 PIN --------------------- #
        reply = dispatch(service, FidoIpc.CMD_GET_ASSERTION,
                         {"cbor_req": base64.b64encode(params).decode()})
        check("重试认证：直接成功（不再弹第二个 PIN 框）", reply.get("rv") == 0,
              hex(reply.get("rv") or 0))
        if not reply.get("rv"):
            assertion = FidoCbor.decode(base64.b64decode(reply["data"]["cbor_resp"]))
            check("重试认证：断言带回凭据 ID", assertion[1]["id"] == credential_id)

        # ---- 6. 之后平台用自己的 PIN 流程（token）也能解库 -------------------- #
        reply = dispatch(service, FidoIpc.CMD_CLIENT_PIN,
                         {"cbor_req": base64.b64encode(FidoCbor.encode(
                             {1: 2, 2: FidoCtap.CLIENT_PIN_GET_RETRIES})).decode()})
        check("clientPIN getRetries：不再报 PIN 未设置",
              reply.get("rv") == 0, hex(reply.get("rv") or 0))

        # ---- 7. 多卡：按「哪张卡有这条凭据」自动挑卡 -------------------------- #
        other = FidoStore.FidoStore.open(OTHER_GUID, OTHER_SERIAL, OTHER_NAME)
        other_master = other.unlock(PIN)
        other.set_pin_verifier(PIN)
        other.remember_master(other_master)
        other.add_credential(other_master, {
            "rp_id": "other.example", "rp_name": "Other", "user_name": "bob",
            "credential_id": FidoStore.b64url(secrets.token_bytes(32)),
            "algorithm": -7, "counter": 0,
        }, bytes([1]) + secrets.token_bytes(32))

        service.cards = fake_two_cards
        service.invalidate()                 # 丢掉上一段的会话，模拟冷启动
        reply = dispatch(service, FidoIpc.CMD_GET_ASSERTION,
                         {"cbor_req": base64.b64encode(params).decode()})
        data = reply.get("data") or {}
        check("多卡：不报「找不到凭据」，改让平台收 PIN",
              reply.get("rv") == FidoCtap.CTAP2_ERR_PIN_REQUIRED
              and data.get("platform_pin") is True,
              (hex(reply.get("rv") or 0), data))
        check("多卡：选中了真正存着该凭据的那张卡",
              service._pin_card == CARD_NAME, service._pin_card)
    finally:
        FidoStore.cards_dir, FidoStore.settings_path = original_cards, original_settings
        shutil.rmtree(folder, ignore_errors=True)

    print()
    if failures:
        print("自检失败 %d 项: %s" % (len(failures), "、".join(failures)))
        return 1
    print("还原后重新绑定自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
