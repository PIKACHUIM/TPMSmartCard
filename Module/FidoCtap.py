# -*- coding: utf-8 -*-
"""CTAP2 认证器核心：GetInfo / MakeCredential / GetAssertion。

只实现「外接安全密钥」最常用的一条路径：

* 算法：ES256（ECDSA P-256 + SHA-256），这是 FIDO2 的必备算法；
* 凭据：可发现凭据（resident key，``rk``），私钥存在本机凭据库，
  由卡片 PIN + DPAPI 双层加密（见 :mod:`Module.FidoStore`）；
* 认证器证明：``fmt = "none"``（不声明厂商证明证书，RP 侧看不到型号，
  与绝大多数软件认证器一致）；
* 用户校验：``uv = true``——真正的「用户在场」由卡片 PIN 弹窗保证，
  因此 authData 里会同时置 UP 与 UV 标志。

未实现（也不在 GetInfo 里声明）：clientPIN、largeBlobs、credentialManagement、
hmac-secret、U2F/CTAP1。
"""

import hashlib
import secrets
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from Module import FidoCbor
from Module.FidoStore import AAGUID, StoreError, b64url, b64url_decode

# CTAP2 状态码（只列出本模块用到的）
CTAP2_OK = 0x00
CTAP1_ERR_INVALID_COMMAND = 0x01
CTAP1_ERR_INVALID_PARAMETER = 0x02
CTAP2_ERR_CREDENTIAL_EXCLUDED = 0x19
CTAP2_ERR_UNSUPPORTED_ALGORITHM = 0x26
CTAP2_ERR_OPERATION_DENIED = 0x27
CTAP2_ERR_NO_CREDENTIALS = 0x2E
CTAP2_ERR_NOT_ALLOWED = 0x30
CTAP2_ERR_PIN_REQUIRED = 0x36
CTAP2_ERR_PIN_NOT_SET = 0x35
CTAP1_ERR_OTHER = 0x7F

# CTAP2 命令码
CMD_MAKE_CREDENTIAL = 0x01
CMD_GET_ASSERTION = 0x02
CMD_GET_INFO = 0x04
CMD_CLIENT_PIN = 0x06
CMD_RESET = 0x07
CMD_GET_NEXT_ASSERTION = 0x08
CMD_CANCEL = 0x11

# 认证器数据标志位
FLAG_UP = 0x01
FLAG_UV = 0x04
FLAG_AT = 0x40
FLAG_ED = 0x80

# 私钥信封里的算法标识（为将来支持 Ed25519 预留）
KEY_KIND_P256 = 1

# 认证器声明的能力
MAX_MSG_SIZE = 1200
ALG_ES256 = -7


class CtapError(Exception):
    """CTAP2 层面的错误，交给上层转成状态码返回给平台。"""

    def __init__(self, code, message=""):
        super().__init__(message or ("CTAP 错误 0x%02X" % code))
        self.code = int(code)


class PinRequired(Exception):
    """当前还没有通过卡片 PIN 认证，需要先让用户选卡 + 输 PIN。"""


# --------------------------------------------------------------------------- #
# CBOR 结构构造
# --------------------------------------------------------------------------- #
def get_info():
    """authenticatorGetInfo 的响应（CBOR 字节串）。"""
    return FidoCbor.encode({
        1: ["FIDO_2_0", "FIDO_2_1"],          # 支持的协议版本
        3: AAGUID,                            # 认证器型号标识
        4: {                                  # 能力
            "rk": True,                       # 支持可发现凭据（passkey）
            "up": True,                       # 支持用户在场
            "uv": True,                       # 支持用户校验（卡片 PIN）
            "plat": False,                    # 不是平台认证器
            "clientPin": False,               # 不走 CTAP 内 PIN 协议
        },
        5: MAX_MSG_SIZE,                      # 单条消息上限
        9: ["usb"],                           # 传输方式
        0x0A: [{"type": "public-key", "alg": ALG_ES256}],
    })


def _cose_p256(public_numbers):
    return {
        1: 2,                                  # kty = EC2
        3: ALG_ES256,                          # alg = ES256
        -1: 1,                                 # crv = P-256
        -2: public_numbers.x.to_bytes(32, "big"),
        -3: public_numbers.y.to_bytes(32, "big"),
    }


def _auth_data(rp_id, flags, counter, attestation=None):
    """拼 authenticatorData。

    ``attestation`` 为 ``None`` 时是断言（无 attestedCredentialData），
    否则是 ``(credential_id, cose_key)``。
    """
    data = bytearray()
    data += hashlib.sha256(str(rp_id).encode("utf-8")).digest()
    data.append(flags & 0xFF)
    data += struct.pack(">I", int(counter) & 0xFFFFFFFF)
    if attestation is not None:
        credential_id, cose_key = attestation
        data += AAGUID
        data += struct.pack(">H", len(credential_id))
        data += credential_id
        data += FidoCbor.encode(cose_key)
    return bytes(data)


def _require(params, key, name):
    if not isinstance(params, dict) or key not in params:
        raise CtapError(CTAP1_ERR_INVALID_PARAMETER, "缺少参数: %s" % name)
    return params[key]


def _decode_params(raw):
    if not raw:
        return {}
    try:
        value = FidoCbor.decode(raw)
    except FidoCbor.CborError as err:
        raise CtapError(CTAP1_ERR_INVALID_PARAMETER, "CBOR 解析失败: %s" % err)
    if not isinstance(value, dict):
        raise CtapError(CTAP1_ERR_INVALID_PARAMETER, "参数必须是 CBOR map")
    return value


def _user_entity(user):
    entity = {"id": bytes(user.get("id") or b"")}
    if user.get("name"):
        entity["name"] = str(user["name"])
    if user.get("displayName"):
        entity["displayName"] = str(user["displayName"])
    return entity


# --------------------------------------------------------------------------- #
# MakeCredential
# --------------------------------------------------------------------------- #
def make_credential(raw_params, store, master_key):
    """注册新凭据，返回 attestationObject。"""
    params = _decode_params(raw_params)
    client_data_hash = bytes(_require(params, 1, "clientDataHash"))
    rp = _require(params, 2, "rp")
    user = _require(params, 3, "user")
    algorithms = _require(params, 4, "pubKeyCredParams")
    if not isinstance(rp, dict) or not rp.get("id"):
        raise CtapError(CTAP1_ERR_INVALID_PARAMETER, "rp.id 不能为空")
    if not isinstance(user, dict) or not user.get("id"):
        raise CtapError(CTAP1_ERR_INVALID_PARAMETER, "user.id 不能为空")

    supported = False
    for item in algorithms or []:
        if isinstance(item, dict) and int(item.get("alg", 0)) == ALG_ES256 \
                and str(item.get("type", "public-key")) == "public-key":
            supported = True
            break
    if not supported:
        raise CtapError(CTAP2_ERR_UNSUPPORTED_ALGORITHM, "只支持 ES256(-7)")

    # excludeList：同一张卡上已有该 RP 的凭据时，按规范报「已存在」
    for item in params.get(5) or []:
        if not isinstance(item, dict):
            continue
        cred_id = item.get("id")
        if not cred_id:
            continue
        if store.find_by_credential_id(cred_id) is not None:
            raise CtapError(CTAP2_ERR_CREDENTIAL_EXCLUDED, "该凭据已存在")

    options = params.get(7) or {}
    rk = bool(options.get("rk", True))

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_value = private_key.private_numbers().private_value
    public_numbers = private_key.public_key().public_numbers()
    credential_id = secrets.token_bytes(32)
    counter = 0

    meta = {
        "rp_id": str(rp.get("id")),
        "rp_name": str(rp.get("name") or rp.get("id")),
        "user_id": b64url(user.get("id") or b""),
        "user_name": str(user.get("name") or ""),
        "user_display_name": str(user.get("displayName") or ""),
        "credential_id": b64url(credential_id),
        "algorithm": ALG_ES256,
        "counter": counter,
        "discoverable": rk,
        "transports": ["usb"],
        "backup_eligible": False,
        "backup_state": False,
    }
    secret = bytes([KEY_KIND_P256]) + private_value.to_bytes(32, "big")
    try:
        store.add_credential(master_key, meta, secret)
    finally:
        del secret

    auth_data = _auth_data(meta["rp_id"], FLAG_UP | FLAG_UV | FLAG_AT, counter,
                           attestation=(credential_id, _cose_p256(public_numbers)))
    return FidoCbor.encode({
        1: "none",                 # fmt：不做厂商证明
        2: auth_data,              # authData
        3: {},                     # attStmt
    })


# --------------------------------------------------------------------------- #
# GetAssertion
# --------------------------------------------------------------------------- #
def get_assertion(raw_params, store, master_key):
    """用已有凭据签名，返回 assertionObject。"""
    params = _decode_params(raw_params)
    rp_id = str(_require(params, 1, "rpId"))
    client_data_hash = bytes(_require(params, 2, "clientDataHash"))

    allow_list = params.get(3) or []
    allow_ids = []
    for item in allow_list:
        if isinstance(item, dict) and item.get("id"):
            allow_ids.append(bytes(item["id"]))

    entries = store.find_for_rp(rp_id, allow_ids or None)
    if not entries:
        raise CtapError(CTAP2_ERR_NO_CREDENTIALS, "没有匹配的凭据")

    # 有 allowList 时按它的顺序取第一个匹配项；否则取最近使用的一条
    entry = entries[0]
    meta = entry.get("meta") or {}
    try:
        secret = store.get_secret(master_key, entry["uuid"])
    except StoreError as err:
        raise CtapError(CTAP1_ERR_OTHER, str(err))

    kind, raw_key = secret[0], secret[1:]
    if kind != KEY_KIND_P256 or len(raw_key) != 32:
        raise CtapError(CTAP1_ERR_OTHER, "凭据算法不受支持")
    try:
        private_key = ec.derive_private_key(int.from_bytes(raw_key, "big"),
                                            ec.SECP256R1())
    finally:
        del secret

    counter = store.bump_counter(entry["uuid"])
    auth_data = _auth_data(rp_id, FLAG_UP | FLAG_UV, counter)
    signature = private_key.sign(auth_data + client_data_hash,
                                 ec.ECDSA(hashes.SHA256()))

    assertion = {
        1: {"type": "public-key",
            "id": b64url_decode(meta.get("credential_id"))},
        2: auth_data,
        3: signature,
    }
    user_id = b64url_decode(meta.get("user_id")) if meta.get("user_id") else b""
    if user_id:
        assertion[4] = _user_entity({"id": user_id,
                                     "name": meta.get("user_name", ""),
                                     "displayName": meta.get("user_display_name", "")})
    if len(entries) > 1:
        assertion[5] = len(entries)
    return FidoCbor.encode(assertion)


# --------------------------------------------------------------------------- #
# 命令分发
# --------------------------------------------------------------------------- #
def handle(command, raw_params, store, master_key, logger=None):
    """处理一条 CTAP2 命令，返回 CBOR 响应字节串。

    :raises PinRequired: 需要先做卡片 PIN 认证
    :raises CtapError: CTAP2 层面的错误
    """
    if command == CMD_GET_INFO:
        return get_info()
    if command == CMD_RESET:
        # 规范允许返回 NOT_ALLOWED；这里刻意不支持「一条命令清空所有凭据」，
        # 清理由「系统设置 → FIDO2」里的显式操作完成。
        raise CtapError(CTAP2_ERR_NOT_ALLOWED, "不支持通过协议重置")
    if command == CMD_CLIENT_PIN:
        raise CtapError(CTAP2_ERR_PIN_NOT_SET, "未启用 CTAP 内 PIN 协议")
    if command == CMD_GET_NEXT_ASSERTION:
        raise CtapError(CTAP1_ERR_INVALID_COMMAND, "只返回一条断言")
    if command not in (CMD_MAKE_CREDENTIAL, CMD_GET_ASSERTION):
        raise CtapError(CTAP1_ERR_INVALID_COMMAND, "未知命令 0x%02X" % command)

    if store is None or master_key is None:
        raise PinRequired()
    try:
        if command == CMD_MAKE_CREDENTIAL:
            return make_credential(raw_params, store, master_key)
        return get_assertion(raw_params, store, master_key)
    except StoreError as err:
        raise CtapError(CTAP1_ERR_OTHER, str(err))


# --------------------------------------------------------------------------- #
# 自检：不依赖卡片与 USB，纯软件跑通一次注册 + 认证
# --------------------------------------------------------------------------- #
def _selftest():
    import os
    import tempfile

    from Module import FidoStore

    folder = tempfile.mkdtemp(prefix="tpmsc-fido-")
    backup = FidoStore.cards_dir
    FidoStore.cards_dir = lambda: folder
    try:
        store = FidoStore.FidoStore("selftest")
        master = store.unlock("12345678")
        client_data_hash = hashlib.sha256(b"challenge").digest()
        params = {
            1: client_data_hash,
            2: {"id": "example.com", "name": "Example"},
            3: {"id": b"user-1", "name": "alice", "displayName": "Alice"},
            4: [{"type": "public-key", "alg": ALG_ES256}],
            7: {"rk": True, "uv": True},
        }
        attestation = FidoCbor.decode(
            make_credential(FidoCbor.encode(params), store, master))
        assert attestation[1] == "none"
        auth_data = attestation[2]
        assert auth_data[32] & FLAG_AT, "authData 应带 attestedCredentialData"
        offset = 37 + 16
        cred_len = struct.unpack(">H", auth_data[offset:offset + 2])[0]
        credential_id = auth_data[offset + 2:offset + 2 + cred_len]
        cose = FidoCbor.decode_from(auth_data, offset + 2 + cred_len)[0]
        print("注册成功: credentialId=%s, cose.alg=%d" % (b64url(credential_id), cose[3]))

        assertion_bytes = get_assertion(FidoCbor.encode({
            1: "example.com",
            2: client_data_hash,
            3: [{"type": "public-key", "id": credential_id}],
        }), store, master)
        assertion = FidoCbor.decode(assertion_bytes)
        assert assertion[1]["id"] == credential_id
        assert assertion[2][32] & FLAG_UV

        # 用注册时拿到的公钥验签，确认签名与 authData 是对得上的
        public_key = ec.EllipticCurvePublicNumbers(
            int.from_bytes(cose[-2], "big"),
            int.from_bytes(cose[-3], "big"),
            ec.SECP256R1()).public_key()
        public_key.verify(assertion[3], assertion[2] + client_data_hash,
                          ec.ECDSA(hashes.SHA256()))
        print("认证成功: counter=%d，签名验签通过"
              % struct.unpack(">I", assertion[2][33:37])[0])

        # 没有匹配凭据时应报 0x2E
        try:
            get_assertion(FidoCbor.encode({
                1: "other.example", 2: client_data_hash,
            }), store, master)
        except CtapError as err:
            assert err.code == CTAP2_ERR_NO_CREDENTIALS, err.code
            print("未知站点正确返回 CTAP2_ERR_NO_CREDENTIALS")
        print("FidoCtap 自检通过")
    finally:
        FidoStore.cards_dir = backup
        for name in os.listdir(folder):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass
        try:
            os.rmdir(folder)
        except OSError:
            pass


if __name__ == "__main__":
    _selftest()
