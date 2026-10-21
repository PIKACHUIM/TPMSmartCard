# -*- coding: utf-8 -*-
"""clientPIN 全链路自检（模拟 Windows 平台侧，不需要真实卡片与驱动）。

覆盖：

1. GetInfo 声明 clientPin / pinUvAuthProtocols；
2. getKeyAgreement → setPIN（唯一能拿到明文的一步，交给「卡片」校验）；
3. getPINToken（只送 SHA-256(PIN)[0:16]）→ 拿到可解密的 pinToken；
4. 带 / 不带 / 错误 pinUvAuthParam 的 MakeCredential；
5. 模拟程序重启（清空内存会话与 pinToken）后，仅凭 PIN 哈希能否重新解库
   —— 这一步验证 guard（DPAPI 副本）与 pin_verifier 的持久化。

运行：python Fido\\src\\devtest\\fido_clientpin_test.py
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

from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

from Module import FidoCbor  # noqa: E402
from Module import FidoClientPin  # noqa: E402
from Module import FidoCtap  # noqa: E402
from Module import FidoIpc  # noqa: E402
from Module import FidoStore  # noqa: E402
from Module.FidoService import FidoService  # noqa: E402

PIN = "12345678"
CARD_NAME = "Microsoft Virtual Smart Card 0"
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append(bool(ok))
    tail = ("  → %s" % (detail,)) if detail != "" else ""
    print("[%s] %s%s" % ("OK" if ok else "失败", name, tail))


def b64(data):
    return base64.b64encode(bytes(data)).decode("ascii")


def unb64(text):
    return base64.b64decode(text or "")


class Platform:
    """模拟 Windows 侧：协商密钥、加密 PIN、算 pinAuth。"""

    def __init__(self, service, protocol=2):
        self.service = service
        self.protocol = protocol
        self.aes_key = None
        self.hmac_key = None
        self.token = None

    def _call(self, params):
        resp = self.service.dispatch(
            FidoIpc.CMD_CLIENT_PIN,
            json.dumps({"cbor_req": b64(FidoCbor.encode(params))}).encode())
        return resp

    def agreement(self):
        resp = self._call({1: self.protocol, 2: FidoCtap.CLIENT_PIN_GET_KEY_AGREEMENT})
        if resp.get("rv"):
            raise RuntimeError("getKeyAgreement 失败: 0x%02X" % resp["rv"])
        device_key = FidoCbor.decode(unb64(resp["data"]["cbor_resp"]))[1]

        private_key = ec.generate_private_key(ec.SECP256R1())
        numbers = private_key.public_key().public_numbers()
        self.cose = {1: 2, 3: FidoClientPin.ALG_ECDH_ES_HKDF_256, -1: 1,
                     -2: numbers.x.to_bytes(32, "big"),
                     -3: numbers.y.to_bytes(32, "big")}
        device_pub = ec.EllipticCurvePublicNumbers(
            int.from_bytes(device_key[-2], "big"),
            int.from_bytes(device_key[-3], "big"),
            ec.SECP256R1()).public_key()
        shared = private_key.exchange(ec.ECDH(), device_pub)
        self.aes_key, self.hmac_key = FidoClientPin.derive_keys(self.protocol, shared)
        return self

    def set_pin(self, pin):
        new_pin_enc = FidoClientPin._aes_cbc(
            self.aes_key, FidoClientPin._pad_7816(pin.encode()), True)
        return self._call({
            1: self.protocol, 2: FidoCtap.CLIENT_PIN_SET_PIN, 3: self.cose,
            4: FidoClientPin.auth_code(self.protocol, self.hmac_key, new_pin_enc),
            5: new_pin_enc})

    def get_token(self, pin):
        digest = FidoClientPin.pin_digest(pin)
        pin_hash_enc = FidoClientPin._aes_cbc(self.aes_key, digest, True)
        resp = self._call({
            1: self.protocol, 2: FidoCtap.CLIENT_PIN_GET_TOKEN, 3: self.cose,
            4: FidoClientPin.auth_code(self.protocol, self.hmac_key, pin_hash_enc),
            6: pin_hash_enc})
        if not resp.get("rv"):
            self.token = FidoClientPin._aes_cbc(
                self.aes_key, FidoCbor.decode(unb64(resp["data"]["cbor_resp"]))[2],
                False)
        return resp

    def make_credential(self, with_param=True, wrong_param=False):
        client_data_hash = hashlib.sha256(b"clientpin-challenge").digest()
        params = {
            1: client_data_hash,
            2: {"id": "passkey.example", "name": "Passkey Example"},
            3: {"id": b"user-pin", "name": "bob", "displayName": "Bob"},
            4: [{"type": "public-key", "alg": -7}],
            7: {"rk": True, "uv": True},
        }
        if with_param and self.token:
            param = FidoClientPin.auth_code(self.protocol, self.token, client_data_hash)
            params[FidoCtap.MC_PIN_AUTH_PARAM] = b"\x00" * 16 if wrong_param else param
            params[FidoCtap.MC_PIN_AUTH_PROTOCOL] = self.protocol
        return self.service.dispatch(
            FidoIpc.CMD_MAKE_CREDENTIAL,
            json.dumps({"cbor_req": b64(FidoCbor.encode(params))}).encode())


def fake_cards(_include_disabled=False):
    return [{"name": CARD_NAME, "uuid": "serial-0001", "reader": 0,
             "key": FidoStore.card_key("guid-0001", "serial-0001", CARD_NAME),
             "guid": "guid-0001", "serial": "serial-0001", "enabled": True,
             "count": 0}]


def fake_verify_pin(reader, pin):
    if str(pin) == PIN:
        return "ok", "Verified PIN"
    return "wrong", "Verification failed (2 tries left)"


def main():
    folder = tempfile.mkdtemp(prefix="tpmsc-fido-pin-")
    old_cards, old_settings = FidoStore.cards_dir, FidoStore.settings_path
    FidoStore.cards_dir = lambda: folder
    FidoStore.settings_path = lambda: os.path.join(folder, "settings.json")
    try:
        # 造一个已有凭据的库（相当于用户之前用内置 UV 模式注册过 passkey）
        store = FidoStore.FidoStore.open("guid-0001", "serial-0001", CARD_NAME)
        master = store.unlock(PIN)
        store.add_credential(master, {
            "rp_id": "old.example", "rp_name": "Old", "user_id": "dT0",
            "user_name": "alice", "user_display_name": "Alice",
            "credential_id": "Y3JlZA", "algorithm": -7, "counter": 0,
            "discoverable": True, "transports": ["usb"],
            "backup_eligible": False, "backup_state": False},
            bytes([1]) + hashlib.sha256(b"seed").digest())
        store.remember_master(master)

        service = FidoService()
        service.cards = fake_cards
        service.verify_pin = fake_verify_pin
        service.update_settings(pin_mode="clientpin")

        # 1) GetInfo
        info = service.dispatch(FidoIpc.CMD_GET_INFO, b"{}")
        options = FidoCbor.decode(unb64(info["data"]["cbor_info"]))
        check("GetInfo 声明 clientPin", options[4]["clientPin"] is True)
        check("GetInfo 声明 pinUvAuthProtocols",
              options.get(6) == list(FidoClientPin.SUPPORTED_PROTOCOLS), options.get(6))

        # 2) 没有 pinUvAuthParam 时必须交回平台（platform_pin=True，不弹自带框）
        platform = Platform(service).agreement()
        resp = platform.make_credential(with_param=False)
        check("无 pinUvAuthParam 返回 PIN_REQUIRED",
              resp.get("rv") == FidoCtap.CTAP2_ERR_PIN_REQUIRED, resp.get("rv"))
        check("响应标记 platform_pin（fido-go 不再弹框）",
              (resp.get("data") or {}).get("platform_pin") is True)

        # 3) setPIN：模拟平台第一次收 PIN（这里让 mock 的「卡片」校验通过）
        resp = platform.set_pin(PIN)
        check("setPIN 成功", resp.get("rv") == 0, resp.get("rv"))
        # 服务里是另一个 FidoStore 实例，落盘后再读一遍才算数
        fresh = FidoStore.FidoStore.load(store.key)
        check("已记录 PIN 校验材料（落盘）", fresh.has_pin_verifier)
        check("guard 已写入（DPAPI 副本，重启后免 PIN 原文）",
              fresh.recover_master() is not None)

        # 4) getPINToken
        platform = Platform(service).agreement()
        resp = platform.get_token(PIN)
        check("getPINToken 成功", resp.get("rv") == 0, resp.get("rv"))
        check("pinToken 可解密", platform.token is not None and len(platform.token) == 32)

        # 5) 错误的 pinUvAuthParam（此时 token 还有效，必须回 0x33）
        resp = platform.make_credential(wrong_param=True)
        check("错误 pinUvAuthParam 被拒 (0x33)",
              resp.get("rv") == FidoCtap.CTAP2_ERR_PIN_AUTH_INVALID, resp.get("rv"))

        # 6) 带正确 pinUvAuthParam 的 MC（token 一次性，用完即作废）
        resp = platform.make_credential()
        check("带 pinUvAuthParam 注册成功", resp.get("rv") == 0, resp.get("rv"))
        fresh = FidoStore.FidoStore.load(store.key)
        check("凭据已入库", len(fresh.credentials) == 2, len(fresh.credentials))
        resp = platform.make_credential()
        check("pinToken 一次性：同一次会话里第二次必须重新验 PIN",
              resp.get("rv") == FidoCtap.CTAP2_ERR_PIN_REQUIRED
              and (resp.get("data") or {}).get("platform_pin") is True,
              resp.get("rv"))

        # 7) PIN 错误
        platform = Platform(service).agreement()
        resp = platform.get_token("00000000")
        check("错误 PIN 返回 0x31", resp.get("rv") == FidoCtap.CTAP2_ERR_PIN_INVALID,
              resp.get("rv"))

        # 8) 模拟「程序重启」：内存会话与 pinToken 全丢，只剩磁盘上的哈希与 guard
        service._session = None
        service._pin = FidoClientPin.PinProtocol()
        platform = Platform(service).agreement()
        resp = platform.get_token(PIN)
        check("重启后仅凭 PIN 哈希即可重新解库", resp.get("rv") == 0, resp.get("rv"))
        resp = platform.make_credential()
        check("重启后仍能注册（会话已自动恢复）", resp.get("rv") == 0, resp.get("rv"))

        # 9) 删除凭据：磁盘要干净、会话要失效、旧副本不能把它写回来
        rows = service.list_credentials()
        target = [row for row in rows if row["rp_id"] == "passkey.example"]
        check("列出待删除凭据", len(target) >= 1, len(target))
        target = target[0]
        check("删除凭据成功", service.delete_credential(target["card_key"], target["uuid"]))
        fresh = FidoStore.FidoStore.load(store.key)
        check("磁盘上已删除",
              all(item["uuid"] != target["uuid"] for item in fresh.credentials))
        check("删除后会话失效（必须重新验 PIN）", service.session is None)
        # 模拟「另一份旧副本」在删除后继续用：bump_counter 不能把条目写回
        legacy = FidoStore.FidoStore.load(store.key)
        check("旧副本 bump_counter 返回 0", legacy.bump_counter(target["uuid"]) == 0)
        again = FidoStore.FidoStore.load(store.key)
        check("旧副本没有复活已删凭据",
              all(item["uuid"] != target["uuid"] for item in again.credentials))

        # 10) 显式回到内置 UV 模式：GetInfo 不应再声明 clientPin
        service.update_settings(pin_mode="builtin")
        info = service.dispatch(FidoIpc.CMD_GET_INFO, b"{}")
        options = FidoCbor.decode(unb64(info["data"]["cbor_info"]))
        check("builtin 模式不声明 clientPin", options[4]["clientPin"] is False)
        # 上一步删除凭据已经把会话作废，这里应回到「PinRequired + 不带 platform_pin」
        resp = platform.make_credential(with_param=False)
        check("builtin 模式未登录时要求本程序弹框",
              resp.get("rv") == FidoCtap.CTAP2_ERR_PIN_REQUIRED
              and (resp.get("data") or {}).get("platform_pin") is False,
              (resp.get("rv"), (resp.get("data") or {}).get("platform_pin")))
    finally:
        FidoStore.cards_dir, FidoStore.settings_path = old_cards, old_settings
        shutil.rmtree(folder, ignore_errors=True)

    passed = sum(1 for item in CHECKS if item)
    print("\nclientPIN 全链路：%d/%d 项通过" % (passed, len(CHECKS)))
    if passed != len(CHECKS):
        sys.exit(1)


if __name__ == "__main__":
    main()
