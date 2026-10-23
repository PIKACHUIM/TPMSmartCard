# -*- coding: utf-8 -*-
"""「注册 → 删除凭据 → 再注册」自检（不需要真卡，模拟 Windows 的平台侧）。

覆盖以前的两个故障点：

1. 删凭据时顺手把整个会话（含 pinToken）丢掉了 → 平台用缓存里的 token 再注册
   会被判成「PIN required」，Windows 侧表现为
   「未知的设备状态(代码: 1、9、0x8007000d)」，必须重试几次；
2. 每条命令后都把 pinToken 作废（一次性），同样会让紧接着的注册失败。

用法::

    python Fido/src/devtest/fido_reregister_test.py
"""
import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
# 复用 clientPIN 自检里的「平台侧」实现
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from Module import FidoCbor, FidoCtap, FidoIpc, FidoStore          # noqa: E402
from Module.FidoService import FidoService                        # noqa: E402
from fido_clientpin_test import Platform                          # noqa: E402

PIN = "12345678"
CARD = "Microsoft Virtual Smart Card 0"
GUID = "guid-reg-test"
SERIAL = "serial-reg-test"
RP = "www.token2.com"


def b64(data):
    return base64.b64encode(bytes(data)).decode("ascii")


def cards(_include_disabled=False, use_cache=True):
    store = FidoStore.FidoStore.resolve(GUID, SERIAL, CARD, create=False)
    return [{"name": CARD, "uuid": SERIAL, "reader": 0,
             "key": store.key if store else FidoStore.card_key(GUID, SERIAL, CARD),
             "guid": GUID, "serial": SERIAL, "enabled": True,
             "bound": bool(store is not None and store.bound),
             "count": len(store.credentials) if store else 0}]


def mc_params(platform, exclude=None):
    client_data_hash = hashlib.sha256(b"mc-%d" % len(exclude or [])).digest()
    params = {
        1: client_data_hash,
        2: {"id": RP, "name": "TOKEN2 FIDO2 Demo"},
        3: {"id": b"token2_user_857c201c", "name": "token2_user_857c201c",
            "displayName": "token2_user"},
        4: [{"type": "public-key", "alg": -7}],
        7: {"rk": True, "uv": True},
    }
    if exclude:
        params[5] = [{"type": "public-key", "id": exclude}]
    if platform.token:
        params[FidoCtap.MC_PIN_AUTH_PARAM] = FidoCtap.FidoClientPin.auth_code(
            platform.protocol, platform.token, client_data_hash)
        params[FidoCtap.MC_PIN_AUTH_PROTOCOL] = platform.protocol
    return params


def dispatch(service, cmd, params):
    return service.dispatch(cmd, json.dumps(
        {"cbor_req": b64(FidoCbor.encode(params))}).encode())


def main():
    folder = tempfile.mkdtemp(prefix="tpmsc-rereg-")
    old_cards, old_settings = FidoStore.cards_dir, FidoStore.settings_path
    FidoStore.cards_dir = lambda: folder
    FidoStore.settings_path = lambda: os.path.join(folder, "settings.json")
    failures = []

    def check(name, ok, detail=""):
        print("%s %s%s" % ("[OK]  " if ok else "[失败]", name,
                           ("  → " + str(detail)) if detail else ""))
        if not ok:
            failures.append(name)

    try:
        service = FidoService()
        service.cards = cards
        service.verify_pin = lambda reader, pin: ("ok", "selftest")
        service.update_settings(pin_mode="clientpin")

        platform = Platform(service).agreement()
        check("setPIN", platform.set_pin(PIN).get("rv") == 0)
        check("getToken", platform.get_token(PIN).get("rv") == 0)

        first = dispatch(service, FidoIpc.CMD_MAKE_CREDENTIAL, mc_params(platform))
        check("首次注册成功", first.get("rv") == 0, hex(first.get("rv") or 0))
        store = FidoStore.FidoStore.resolve(GUID, SERIAL, CARD, create=False)
        cred = FidoStore.b64url_decode(store.credentials[0]["meta"]["credential_id"])
        check("凭据已入库", len(store.credentials) == 1)

        # 主页删除：走 service.delete_credential（和界面按钮同一条路）
        ok = service.delete_credential(store.key, store.credentials[0]["uuid"])
        check("删除凭据", ok)

        again = dispatch(service, FidoIpc.CMD_MAKE_CREDENTIAL, mc_params(platform))
        check("删除后再注册成功", again.get("rv") == 0, hex(again.get("rv") or 0))
        if not again.get("rv"):
            raw = base64.b64decode(again["data"]["cbor_resp"])
            att = FidoCbor.decode(raw)
            auth = att[2]
            check("attestationObject 结构正确",
                  att[1] == "none" and len(auth) > 100 and auth[32] & 0x40)
        store = FidoStore.FidoStore.resolve(GUID, SERIAL, CARD, create=False)
        check("新凭据已入库（旧的已删）", len(store.credentials) == 1)

        # 带已删除凭据的 excludeList：应报「已存在」而不是崩
        excl = dispatch(service, FidoIpc.CMD_MAKE_CREDENTIAL, mc_params(platform, cred))
        check("excludeList 里是已删凭据 → 正常注册", excl.get("rv") == 0,
              hex(excl.get("rv") or 0))
    finally:
        FidoStore.cards_dir, FidoStore.settings_path = old_cards, old_settings
        shutil.rmtree(folder, ignore_errors=True)

    print()
    if failures:
        print("自检失败 %d 项: %s" % (len(failures), "、".join(failures)))
        return 1
    print("注册→删除→再注册 自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
