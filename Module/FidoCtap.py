# -*- coding: utf-8 -*-
"""CTAP2 认证器核心：GetInfo / MakeCredential / GetAssertion / ClientPIN。

只实现「外接安全密钥」最常用的一条路径：

* 算法：ES256（ECDSA P-256 + SHA-256），这是 FIDO2 的必备算法；
* 凭据：可发现凭据（resident key，``rk``），私钥存在本机凭据库，
  由卡片 PIN + DPAPI 双层加密（见 :mod:`Module.FidoStore`）；
* 认证器证明：``fmt = "none"``（不声明厂商证明证书，RP 侧看不到型号，
  与绝大多数软件认证器一致）；
* 用户校验有两种模式（见 :meth:`get_info`）：

  - ``clientpin``（默认）：设备声明 ``clientPin = true``，把 PIN 交给**平台**
    收集，走 CTAP 的 ``authenticatorClientPIN``（0x06）。界面上只有 Windows
    那一个 PIN 对话框，也不会出现「本程序弹框 + Windows 触摸提示」并存、
    最后超时的问题。
  - ``builtin``：设备自己弹 PIN 框（由 fido-go.exe 实现），``clientPin =
    false``。这一条是回退路径，平台不支持 clientPIN 或需要老行为时使用。

未实现（也不在 GetInfo 里声明）：largeBlobs、credentialManagement、
hmac-secret、U2F/CTAP1。
"""

import hashlib
import hmac as _hmac
import secrets
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from Module import FidoCbor
from Module import FidoClientPin
from Module.FidoStore import AAGUID, StoreError, b64url, b64url_decode

# CTAP2 状态码（只列出本模块用到的）
CTAP2_OK = 0x00
CTAP1_ERR_INVALID_COMMAND = 0x01
CTAP1_ERR_INVALID_PARAMETER = 0x02
CTAP2_ERR_MISSING_PARAMETER = 0x14
CTAP2_ERR_CREDENTIAL_EXCLUDED = 0x19
CTAP2_ERR_UNSUPPORTED_ALGORITHM = 0x26
CTAP2_ERR_OPERATION_DENIED = 0x27
CTAP2_ERR_NO_CREDENTIALS = 0x2E
CTAP2_ERR_NOT_ALLOWED = 0x30
CTAP2_ERR_PIN_INVALID = 0x31
CTAP2_ERR_PIN_AUTH_INVALID = 0x33
CTAP2_ERR_PIN_BLOCKED = 0x34
CTAP2_ERR_PIN_NOT_SET = 0x35
CTAP2_ERR_PIN_REQUIRED = 0x36
CTAP2_ERR_PIN_POLICY_VIOLATION = 0x37
CTAP2_ERR_INVALID_SUBCOMMAND = 0x3E
CTAP1_ERR_OTHER = 0x7F

# authenticatorClientPIN 的子命令
CLIENT_PIN_GET_RETRIES = 0x01
CLIENT_PIN_GET_KEY_AGREEMENT = 0x02
CLIENT_PIN_SET_PIN = 0x03
CLIENT_PIN_CHANGE_PIN = 0x04
CLIENT_PIN_GET_TOKEN = 0x05
CLIENT_PIN_GET_TOKEN_UV = 0x06
CLIENT_PIN_GET_UV_RETRIES = 0x07
CLIENT_PIN_GET_TOKEN_WITH_PERMISSIONS = 0x09

# PIN 模式
PIN_MODE_CLIENT = "clientpin"
PIN_MODE_BUILTIN = "builtin"

# MC / GA 里 pinUvAuthParam 与 protocol 的参数键（两者编号不同！）
MC_PIN_AUTH_PARAM = 0x09
MC_PIN_AUTH_PROTOCOL = 0x0A
GA_PIN_AUTH_PARAM = 0x06
GA_PIN_AUTH_PROTOCOL = 0x07

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
def get_info(pin_mode=PIN_MODE_CLIENT):
    """authenticatorGetInfo 的响应（CBOR 字节串）。

    ``pin_mode`` 决定 PIN 由谁收集：

    * ``clientpin``：声明 ``clientPin = true`` 并列出 pinUvAuthProtocols，
      Windows 就会用自己的安全对话框收 PIN，再通过 0x06 送进来校验；
    * ``builtin``：声明 ``uv = true`` 且 ``clientPin = false``，此时平台只会
      提示「触摸安全密钥」，真正的 PIN 由 fido-go 自己弹窗收集。
    """
    client_pin = str(pin_mode or PIN_MODE_CLIENT).lower() != PIN_MODE_BUILTIN
    info = {
        1: ["FIDO_2_0", "FIDO_2_1"],          # 支持的协议版本
        3: AAGUID,                            # 认证器型号标识
        4: {                                  # 能力
            "rk": True,                       # 支持可发现凭据（passkey）
            "up": True,                       # 支持用户在场
            # clientPin 模式下必须声明 uv=false：UV 由 PIN 提供，这跟 YubiKey 5
            # 等没有生物识别的认证器一致。若声明 uv=true，Windows 会以为设备
            # 会自己完成用户验证，于是只显示「触摸安全密钥」干等设备，
            # 不弹它的 PIN 框（实测就是这个现象）。
            "uv": not client_pin,
            "plat": False,                    # 不是平台认证器
            "clientPin": client_pin,
        },
        5: MAX_MSG_SIZE,                      # 单条消息上限
        9: ["usb"],                           # 传输方式
        0x0A: [{"type": "public-key", "alg": ALG_ES256}],
    }
    if client_pin:
        info[6] = list(FidoClientPin.SUPPORTED_PROTOCOLS)
    return FidoCbor.encode(info)


def _require_uv(params, pin, pin_mode, client_data_hash, param_key, protocol_key):
    """clientPIN 模式下校验 MC/GA 的 ``pinUvAuthParam``。

    校验不过就报 PIN_REQUIRED，平台会去走 0x06 流程（自己弹 PIN 框），
    而不是像内置 UV 那样把请求挂在设备这里等用户输入。
    """
    if str(pin_mode or PIN_MODE_CLIENT).lower() == PIN_MODE_BUILTIN:
        return
    if pin is None or not pin.pin_token:
        raise CtapError(CTAP2_ERR_PIN_REQUIRED, "需要 PIN（还没有有效的 pinToken）")
    param = params.get(param_key)
    if not param:
        raise CtapError(CTAP2_ERR_PIN_REQUIRED, "请求里没有 pinUvAuthParam")
    protocol = params.get(protocol_key)
    if protocol is not None and int(protocol) != int(pin.protocol):
        raise CtapError(CTAP2_ERR_PIN_AUTH_INVALID, "pinUvAuthProtocol 不一致")
    if not pin.check_token_auth(bytes(param), bytes(client_data_hash)):
        raise CtapError(CTAP2_ERR_PIN_AUTH_INVALID, "pinUvAuthParam 校验失败")


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
def make_credential(raw_params, store, master_key, pin=None,
                    pin_mode=PIN_MODE_CLIENT):
    """注册新凭据，返回 attestationObject。"""
    params = _decode_params(raw_params)
    client_data_hash = bytes(_require(params, 1, "clientDataHash"))
    _require_uv(params, pin, pin_mode, client_data_hash,
                MC_PIN_AUTH_PARAM, MC_PIN_AUTH_PROTOCOL)
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
def get_assertion(raw_params, store, master_key, pin=None,
                  pin_mode=PIN_MODE_CLIENT):
    """用已有凭据签名，返回 assertionObject。"""
    params = _decode_params(raw_params)
    rp_id = str(_require(params, 1, "rpId"))
    client_data_hash = bytes(_require(params, 2, "clientDataHash"))
    _require_uv(params, pin, pin_mode, client_data_hash,
                GA_PIN_AUTH_PARAM, GA_PIN_AUTH_PROTOCOL)

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
# authenticatorClientPIN（0x06）
# --------------------------------------------------------------------------- #
def client_pin(raw_params, pin, verifier):
    """处理 authenticatorClientPIN。

    ``verifier`` 是回调（由 :class:`Module.FidoService.FidoService` 提供），
    负责「PIN 对不对」这类需要卡片/凭据库参与的事：

    * ``verifier("retries")`` → ``{"status": ok/not_set/locked, "retries": n}``
    * ``verifier("set_pin", PIN原文)`` → 同上（第一次设置，需卡片校验）
    * ``verifier("token", SHA256(PIN)[0:16])`` → 同上（之后每次认证）
    """
    params = _decode_params(raw_params)
    sub_command = int(_require(params, 2, "subCommand"))
    if pin is None:
        raise CtapError(CTAP1_ERR_OTHER, "clientPIN 上下文不可用")

    if sub_command == CLIENT_PIN_GET_RETRIES:
        state = verifier("retries") or {}
        status = str(state.get("status") or "")
        if status == "not_set":
            raise CtapError(CTAP2_ERR_PIN_NOT_SET, "还没有可用的 PIN")
        if status == "locked":
            raise CtapError(CTAP2_ERR_PIN_BLOCKED, "PIN 已锁定")
        return FidoCbor.encode({3: int(state.get("retries") or 0)})

    if sub_command == CLIENT_PIN_GET_KEY_AGREEMENT:
        try:
            return FidoCbor.encode({1: pin.begin(params.get(1))})
        except FidoClientPin.ClientPinError as err:
            raise CtapError(CTAP1_ERR_INVALID_PARAMETER, str(err))

    if sub_command == CLIENT_PIN_SET_PIN:
        return _client_pin_set(params, pin, verifier)

    if sub_command in (CLIENT_PIN_GET_TOKEN,
                       CLIENT_PIN_GET_TOKEN_WITH_PERMISSIONS):
        return _client_pin_token(params, pin, verifier)

    if sub_command == CLIENT_PIN_CHANGE_PIN:
        # 改 PIN 会同时影响卡片登录与凭据库封装，走主程序的「修改 PIN」流程
        raise CtapError(CTAP2_ERR_NOT_ALLOWED, "请在主程序里修改卡片 PIN")
    if sub_command in (CLIENT_PIN_GET_TOKEN_UV, CLIENT_PIN_GET_UV_RETRIES):
        raise CtapError(CTAP2_ERR_INVALID_SUBCOMMAND, "不支持内置 UV")
    raise CtapError(CTAP2_ERR_INVALID_SUBCOMMAND,
                    "未知 clientPIN 子命令 0x%02X" % sub_command)


def _client_pin_set(params, pin, verifier):
    """setPIN：平台第一次收集 PIN 时走这里，能拿到**明文**。"""
    key_agreement = params.get(3)
    new_pin_enc = params.get(5)
    pin_auth = params.get(4)
    if not key_agreement or not new_pin_enc:
        raise CtapError(CTAP2_ERR_MISSING_PARAMETER,
                        "缺少 keyAgreement / newPinEnc")
    try:
        pin.agree(params.get(1), key_agreement)
        if pin_auth and not pin.check_auth(bytes(pin_auth), bytes(new_pin_enc)):
            raise CtapError(CTAP2_ERR_PIN_AUTH_INVALID, "pinAuth 校验失败")
        new_pin = pin.decrypt_new_pin(bytes(new_pin_enc)).decode("utf-8", "replace")
    except FidoClientPin.ClientPinError as err:
        raise CtapError(CTAP1_ERR_INVALID_PARAMETER, str(err))
    if len(new_pin) < 4:
        raise CtapError(CTAP2_ERR_PIN_POLICY_VIOLATION, "PIN 至少 4 个字符")

    state = verifier("set_pin", new_pin) or {}
    status = str(state.get("status") or "")
    if status == "locked":
        raise CtapError(CTAP2_ERR_PIN_BLOCKED, state.get("message") or "PIN 已锁定")
    if status != "ok":
        raise CtapError(CTAP2_ERR_PIN_INVALID,
                        state.get("message") or "PIN 不正确")
    return FidoCbor.encode({})


def _client_pin_token(params, pin, verifier):
    """getPINToken / getPINUvAuthTokenUsingPinWithPermissions。"""
    key_agreement = params.get(3)
    pin_hash_enc = params.get(6)
    pin_auth = params.get(4)
    if not key_agreement or not pin_hash_enc:
        raise CtapError(CTAP2_ERR_MISSING_PARAMETER,
                        "缺少 keyAgreement / pinHashEnc")
    try:
        pin.agree(params.get(1), key_agreement)
        if pin_auth and not pin.check_auth(bytes(pin_auth), bytes(pin_hash_enc)):
            raise CtapError(CTAP2_ERR_PIN_AUTH_INVALID, "pinAuth 校验失败")
        digest = pin.decrypt_pin_hash(bytes(pin_hash_enc))
    except FidoClientPin.ClientPinError as err:
        raise CtapError(CTAP1_ERR_INVALID_PARAMETER, str(err))

    state = verifier("token", digest) or {}
    status = str(state.get("status") or "")
    if status == "not_set":
        raise CtapError(CTAP2_ERR_PIN_NOT_SET, "还没有可用的 PIN")
    if status == "locked":
        raise CtapError(CTAP2_ERR_PIN_BLOCKED, state.get("message") or "PIN 已锁定")
    if status != "ok":
        raise CtapError(CTAP2_ERR_PIN_INVALID,
                        state.get("message") or "PIN 不正确")
    try:
        return FidoCbor.encode({2: pin.encrypt_token()})
    except FidoClientPin.ClientPinError as err:
        raise CtapError(CTAP1_ERR_OTHER, str(err))


# --------------------------------------------------------------------------- #
# 命令分发
# --------------------------------------------------------------------------- #
def handle(command, raw_params, store, master_key, logger=None, pin=None,
           pin_mode=PIN_MODE_CLIENT, pin_verifier=None):
    """处理一条 CTAP2 命令，返回 CBOR 响应字节串。

    :raises PinRequired: 需要先做卡片 PIN 认证（内置 UV 模式）
    :raises CtapError: CTAP2 层面的错误
    """
    if command == CMD_GET_INFO:
        return get_info(pin_mode)
    if command == CMD_RESET:
        # 规范允许返回 NOT_ALLOWED；这里刻意不支持「一条命令清空所有凭据」，
        # 清理由「系统设置 → FIDO2」里的显式操作完成。
        raise CtapError(CTAP2_ERR_NOT_ALLOWED, "不支持通过协议重置")
    if command == CMD_CLIENT_PIN:
        if pin_verifier is None:
            raise CtapError(CTAP2_ERR_PIN_NOT_SET, "未启用 clientPIN")
        return client_pin(raw_params, pin, pin_verifier)
    if command == CMD_GET_NEXT_ASSERTION:
        raise CtapError(CTAP1_ERR_INVALID_COMMAND, "只返回一条断言")
    if command not in (CMD_MAKE_CREDENTIAL, CMD_GET_ASSERTION):
        raise CtapError(CTAP1_ERR_INVALID_COMMAND, "未知命令 0x%02X" % command)

    if store is None or master_key is None:
        raise PinRequired()
    try:
        if command == CMD_MAKE_CREDENTIAL:
            result = make_credential(raw_params, store, master_key, pin, pin_mode)
        else:
            result = get_assertion(raw_params, store, master_key, pin, pin_mode)
    except StoreError as err:
        raise CtapError(CTAP1_ERR_OTHER, str(err))
    # pinToken 只用一次：平台缓存了 token 也不能跳过 PIN。下一次注册/认证会
    # 重新走 getKeyAgreement + getPINToken，用户必须再输一次 PIN（实测按预期
    # 解决了「输一次 PIN 之后一直不再验证」）。
    if pin is not None:
        pin.drop_token()
    return result


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
            make_credential(FidoCbor.encode(params), store, master,
                            pin_mode=PIN_MODE_BUILTIN))
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
        }), store, master, pin_mode=PIN_MODE_BUILTIN)
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
            }), store, master, pin_mode=PIN_MODE_BUILTIN)
        except CtapError as err:
            assert err.code == CTAP2_ERR_NO_CREDENTIALS, err.code
            print("未知站点正确返回 CTAP2_ERR_NO_CREDENTIALS")

        # ---- clientPIN：模拟平台侧完整走一遍 ------------------------------ #
        info_client = FidoCbor.decode(get_info(PIN_MODE_CLIENT))
        assert info_client[4]["clientPin"] is True
        # uv 必须为 False：否则 Windows 会等设备自己完成用户验证（只显示触摸）
        assert info_client[4]["uv"] is False
        assert info_client[6] == list(FidoClientPin.SUPPORTED_PROTOCOLS)
        info_builtin = FidoCbor.decode(get_info(PIN_MODE_BUILTIN))
        assert info_builtin[4]["clientPin"] is False
        print("GetInfo 按模式声明 clientPin")

        pin_state = FidoClientPin.PinProtocol()
        seen = {"set_pin": [], "token": []}

        def verifier(action, payload=None):
            if action == "retries":
                return {"status": "ok", "retries": 8}
            if action == "set_pin":
                seen["set_pin"].append(payload)
                return {"status": "ok", "retries": 8}
            if action == "token":
                seen["token"].append(payload)
                return {"status": "ok", "retries": 8}
            return {"status": "not_set"}

        def platform_side(protocol):
            """平台：getKeyAgreement → 算 ECDH → 派生 AES/HMAC 密钥。"""
            agreement = FidoCbor.decode(client_pin(
                FidoCbor.encode({1: protocol, 2: CLIENT_PIN_GET_KEY_AGREEMENT}),
                pin_state, verifier))
            device_key = agreement[1]
            private_key = ec.generate_private_key(ec.SECP256R1())
            numbers = private_key.public_key().public_numbers()
            cose = {1: 2, 3: FidoClientPin.ALG_ECDH_ES_HKDF_256, -1: 1,
                    -2: numbers.x.to_bytes(32, "big"),
                    -3: numbers.y.to_bytes(32, "big")}
            device_pub = ec.EllipticCurvePublicNumbers(
                int.from_bytes(device_key[-2], "big"),
                int.from_bytes(device_key[-3], "big"),
                ec.SECP256R1()).public_key()
            shared = private_key.exchange(ec.ECDH(), device_pub)
            aes_key, hmac_key = FidoClientPin.derive_keys(protocol, shared)
            return cose, aes_key, hmac_key

        pin_text = "12345678"
        cose, aes_key, hmac_key = platform_side(2)
        new_pin_enc = FidoClientPin._aes_cbc(
            aes_key, FidoClientPin._pad_7816(pin_text.encode()), True)
        client_pin(FidoCbor.encode({
            1: 2, 2: CLIENT_PIN_SET_PIN, 3: cose,
            4: FidoClientPin.auth_code(2, hmac_key, new_pin_enc),
            5: new_pin_enc}), pin_state, verifier)
        assert seen["set_pin"] == [pin_text], seen["set_pin"]
        print("setPIN 解析出明文 PIN 并交给回调")

        cose, aes_key, hmac_key = platform_side(2)
        digest = FidoClientPin.pin_digest(pin_text)
        pin_hash_enc = FidoClientPin._aes_cbc(aes_key, digest, True)
        token_resp = FidoCbor.decode(client_pin(FidoCbor.encode({
            1: 2, 2: CLIENT_PIN_GET_TOKEN, 3: cose,
            4: FidoClientPin.auth_code(2, hmac_key, pin_hash_enc),
            6: pin_hash_enc}), pin_state, verifier))
        platform_token = FidoClientPin._aes_cbc(aes_key, token_resp[2], False)
        assert platform_token == pin_state.pin_token
        assert seen["token"] == [digest]
        print("getPINToken 返回可解密的 pinToken")

        # 带 pinUvAuthParam 的 MC 应该成功；错误/缺失的必须被拒。
        # 注意 pinToken 是一次性的，所以「错误 param」要先于「正确 param」测。
        param = FidoClientPin.auth_code(2, platform_token, client_data_hash)
        signed = dict(params)
        signed[MC_PIN_AUTH_PARAM] = param
        signed[MC_PIN_AUTH_PROTOCOL] = 2
        bad = dict(signed)
        bad[MC_PIN_AUTH_PARAM] = b"\x00" * 16
        try:
            handle(CMD_MAKE_CREDENTIAL, FidoCbor.encode(bad), store, master,
                   pin=pin_state, pin_mode=PIN_MODE_CLIENT, pin_verifier=verifier)
            raise AssertionError("错误的 pinUvAuthParam 应当被拒绝")
        except CtapError as err:
            assert err.code == CTAP2_ERR_PIN_AUTH_INVALID, err.code
        att = FidoCbor.decode(handle(CMD_MAKE_CREDENTIAL, FidoCbor.encode(signed),
                                     store, master, pin=pin_state,
                                     pin_mode=PIN_MODE_CLIENT,
                                     pin_verifier=verifier))
        assert att[1] == "none"
        try:
            handle(CMD_MAKE_CREDENTIAL, FidoCbor.encode(signed), store, master,
                   pin=pin_state, pin_mode=PIN_MODE_CLIENT, pin_verifier=verifier)
            raise AssertionError("pinToken 一次性，重复使用应当要求 PIN")
        except CtapError as err:
            assert err.code == CTAP2_ERR_PIN_REQUIRED, err.code
        print("MC 的 pinUvAuthParam 校验正确（token 一次性）")
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
