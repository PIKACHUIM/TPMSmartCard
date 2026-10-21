# -*- coding: utf-8 -*-
"""后端全链路自检（不需要真卡、不需要驱动）：命名管道 → 会话 → CTAP2。

用途：验证 Python 侧（FidoIpc / FidoService / FidoCtap / FidoStore）在没有
TPM 卡、没有安装 USB/IP 驱动的机器上也能跑通「注册 → 认证」，
用来区分「后端问题」与「驱动/设备问题」。

用法::

    python Fido/src/devtest/fido_backend_test.py

会在临时目录里建一个假卡片凭据库，不会碰真实凭据。
"""
import base64
import hashlib
import os
import shutil
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))      # …/TPMSmartCard
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cryptography.hazmat.primitives import hashes                     # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec             # noqa: E402

from Module import FidoCbor                                           # noqa: E402
from Module import FidoCtap                                           # noqa: E402
from Module import FidoIpc                                            # noqa: E402
from Module import FidoStore                                          # noqa: E402
from Module.FidoService import FidoService                            # noqa: E402

PIPE_NAME = r"\\.\pipe\TPMFIDO-SELFTEST"
FAKE_CARD = {"name": "Microsoft Virtual Smart Card 0", "uuid": "aabbccdd",
             "reader": 0, "key": "guid-selftest", "guid": "selftest",
             "serial": "aabbccdd", "enabled": True, "count": 0}


def main():
    folder = tempfile.mkdtemp(prefix="tpmsc-fido-ipc-")
    original_cards_dir = FidoStore.cards_dir
    original_settings = FidoStore.settings_path
    FidoStore.cards_dir = lambda: folder
    # 设置也要指到临时目录，否则登录成功会把 active_card 写进真实设置文件
    FidoStore.settings_path = lambda: os.path.join(folder, "settings.json")
    service = FidoService()
    service.cards = lambda include_disabled=False: [dict(FAKE_CARD)]
    service.verify_pin = lambda reader, pin: ("ok", "selftest")
    # 本测试走的是「内置 UV」那条路（fido-go 弹框 → CMD_LOGIN），
    # clientPIN 的全链路在 fido_clientpin_test.py 里单独测
    service.update_settings(pin_mode="builtin")
    server = FidoIpc.PipeServer(service.dispatch, name=PIPE_NAME,
                               logger=lambda text: print("  [pipe]", text))
    failures = []

    def check(name, condition, detail=""):
        print("%s %s%s" % ("[OK]  " if condition else "[失败]", name,
                           ("  → " + str(detail)) if detail else ""))
        if not condition:
            failures.append(name)

    try:
        assert server.start(), "管道服务启动失败: %s" % server.error
        check("命名管道启动", True, PIPE_NAME)

        info = FidoIpc.call_pipe(FidoIpc.CMD_GET_INFO, {}, PIPE_NAME)
        parsed = FidoCbor.decode(base64.b64decode(info["data"]["cbor_info"]))
        check("GetInfo", info["rv"] == 0 and parsed[1], parsed[1])
        check("GetInfo 声明 rk/uv", parsed[4].get("rk") and parsed[4].get("uv"),
              parsed[4])
        check("GetInfo AAGUID", len(parsed[3]) == 16, parsed[3])

        client_data_hash = hashlib.sha256(b"selftest-challenge").digest()
        mc_params = FidoCbor.encode({
            1: client_data_hash,
            2: {"id": "example.com", "name": "Example"},
            3: {"id": b"user-1", "name": "alice", "displayName": "Alice"},
            4: [{"type": "public-key", "alg": -7}],
            7: {"rk": True, "uv": True},
        })
        reply = FidoIpc.call_pipe(FidoIpc.CMD_MAKE_CREDENTIAL,
                                  {"cbor_req": base64.b64encode(mc_params).decode()},
                                  PIPE_NAME)
        check("未登录时返回 PIN_REQUIRED", reply["rv"] == 0x36, hex(reply["rv"]))
        check("PIN 提示带卡片列表",
              len((reply.get("data") or {}).get("cards") or []) == 1,
              reply.get("data"))

        login = FidoIpc.call_pipe(FidoIpc.CMD_LOGIN,
                                  {"card_uuid": FAKE_CARD["uuid"], "pin": "12345678"},
                                  PIPE_NAME)
        check("登录", login["rv"] == 0, login)

        reply = FidoIpc.call_pipe(FidoIpc.CMD_MAKE_CREDENTIAL,
                                  {"cbor_req": base64.b64encode(mc_params).decode()},
                                  PIPE_NAME)
        check("MakeCredential", reply["rv"] == 0, hex(reply["rv"]))
        attestation = FidoCbor.decode(base64.b64decode(reply["data"]["cbor_resp"]))
        check("attestation fmt=none", attestation[1] == "none")
        auth_data = attestation[2]
        check("authData 带 AT 标志", bool(auth_data[32] & 0x40), hex(auth_data[32]))
        offset = 37 + 16
        cred_len = struct.unpack(">H", auth_data[offset:offset + 2])[0]
        credential_id = auth_data[offset + 2:offset + 2 + cred_len]
        cose_key = FidoCbor.decode_from(auth_data, offset + 2 + cred_len)[0]
        check("凭据 COSE 公钥", cose_key.get(3) == -7 and cose_key.get(-1) == 1,
              cose_key.get(3))

        ga_params = FidoCbor.encode({
            1: "example.com",
            2: client_data_hash,
            3: [{"type": "public-key", "id": credential_id}],
        })
        reply = FidoIpc.call_pipe(FidoIpc.CMD_GET_ASSERTION,
                                  {"cbor_req": base64.b64encode(ga_params).decode()},
                                  PIPE_NAME)
        check("GetAssertion", reply["rv"] == 0, hex(reply["rv"]))
        assertion = FidoCbor.decode(base64.b64decode(reply["data"]["cbor_resp"]))
        check("断言带回凭据 ID", assertion[1]["id"] == credential_id)
        public_key = ec.EllipticCurvePublicNumbers(
            int.from_bytes(cose_key[-2], "big"),
            int.from_bytes(cose_key[-3], "big"),
            ec.SECP256R1()).public_key()
        public_key.verify(assertion[3], assertion[2] + client_data_hash,
                          ec.ECDSA(hashes.SHA256()))
        check("断言签名验签", True)
        counter = struct.unpack(">I", assertion[2][33:37])[0]
        check("计数器递增", counter >= 1, counter)

        ga_miss = FidoCbor.encode({1: "unknown.example", 2: client_data_hash})
        reply = FidoIpc.call_pipe(FidoIpc.CMD_GET_ASSERTION,
                                  {"cbor_req": base64.b64encode(ga_miss).decode()},
                                  PIPE_NAME)
        check("未知站点返回 NO_CREDENTIALS", reply["rv"] == 0x2E, hex(reply["rv"]))

        mc_exclude = FidoCbor.encode({
            1: client_data_hash,
            2: {"id": "example.com", "name": "Example"},
            3: {"id": b"user-1", "name": "alice"},
            4: [{"type": "public-key", "alg": -7}],
            5: [{"type": "public-key", "id": credential_id}],
        })
        reply = FidoIpc.call_pipe(FidoIpc.CMD_MAKE_CREDENTIAL,
                                  {"cbor_req": base64.b64encode(mc_exclude).decode()},
                                  PIPE_NAME)
        check("重复注册返回 CREDENTIAL_EXCLUDED", reply["rv"] == 0x19, hex(reply["rv"]))

        credentials = service.list_credentials()
        check("凭据列表", len(credentials) == 1, credentials[0]["rp_id"] if credentials else "")
        check("删除凭据", service.delete_credential("guid-selftest",
                                                    credentials[0]["uuid"]))
    finally:
        server.stop()
        FidoStore.cards_dir = original_cards_dir
        FidoStore.settings_path = original_settings
        shutil.rmtree(folder, ignore_errors=True)

    print()
    if failures:
        print("自检失败 %d 项: %s" % (len(failures), "、".join(failures)))
        return 1
    print("后端全链路自检通过（%d 项）" % 12)
    return 0


if __name__ == "__main__":
    sys.exit(main())
