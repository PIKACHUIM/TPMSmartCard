# -*- coding: utf-8 -*-
"""CTAP2 clientPIN 的密码学部分（pinUvAuthProtocol 1 / 2）。

为什么要这个模块
================
早期实现走「内置 UV」：设备自己弹 PIN 框。但此时 Windows 已经显示「请触摸
安全密钥」并在计时，用户会同时看到两个界面，输慢一点平台侧就报超时。

改成标准 clientPIN 之后，PIN 由**平台**（Windows 的安全对话框）收集，用
ECDH + AES 加密后送到这里校验，界面上只剩平台那一个对话框。

协议要点（CTAP 2.1 §6.5.4 ~ §6.5.7）
====================================
* 平台先发 ``getKeyAgreement`` 拿设备临时公钥，双方各自算 ECDH sharedSecret；
* protocol 2：``HMAC key = HKDF-SHA256(shared, "CTAP2 HMAC key")``，
  ``AES key = HKDF-SHA256(shared, "CTAP2 AES key")``；
  protocol 1：两者都等于 ``SHA-256(shared)``；
* ``pinHashEnc = AES-256-CBC(aesKey, IV=0, SHA-256(PIN)[0:16])``；
* ``newPinEnc = AES-256-CBC(aesKey, IV=0, PIN + ISO7816 填充)``；
* ``pinAuth = HMAC(hmacKey, 被加密的那段)`` 取前 16 字节；
* ``pinToken`` 由设备随机生成，AES-256-CBC 加密后返回；平台之后用
  ``pinUvAuthParam = HMAC(pinToken, clientDataHash)[0:16]`` 证明已经验过 PIN。

注意：账号 PIN 的**原文**永远到不了设备，只有哈希，所以真正的「这张卡的
PIN 对不对」只能靠 `setPIN` 那一次拿到明文时让卡片自己校验（见 FidoService）。
"""

import hashlib
import hmac
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PROTOCOL_ONE = 1
PROTOCOL_TWO = 2

# 平台优先用 protocol 2（HKDF + SHA-256），1 作为回退（老系统）
SUPPORTED_PROTOCOLS = (PROTOCOL_TWO, PROTOCOL_ONE)

TOKEN_LENGTH = 32
IV_ZERO = b"\x00" * 16
HKDF_SALT = b"\x00" * 32
INFO_HMAC = b"CTAP2 HMAC key"
INFO_AES = b"CTAP2 AES key"

# 平台 key agreement 用的 COSE alg：ECDH-ES + HKDF-256
ALG_ECDH_ES_HKDF_256 = -25


class ClientPinError(Exception):
    """协议层错误（参数缺失/非法），由调用方转成 CTAP 状态码。"""


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def pin_digest(pin):
    """``SHA-256(PIN)`` 前 16 字节——clientPIN 协议里 PIN 的表示方式。"""
    return hashlib.sha256(str(pin).encode("utf-8")).digest()[:16]


def _pad_7816(data):
    """ISO/IEC 7816-4 填充：先补 0x80，再补 0x00 到整数块。"""
    padded = bytes(data) + b"\x80"
    remain = len(padded) % 16
    if remain:
        padded += b"\x00" * (16 - remain)
    return padded


def _unpad_7816(data):
    body = bytes(data)
    index = body.rfind(b"\x80")
    if index < 0:
        raise ClientPinError("填充不正确（找不到 0x80 结尾）")
    return body[:index]


def _aes_cbc(key, data, encrypt):
    cipher = Cipher(algorithms.AES(key), modes.CBC(IV_ZERO))
    ctx = cipher.encryptor() if encrypt else cipher.decryptor()
    return ctx.update(bytes(data)) + ctx.finalize()


def derive_keys(protocol, shared):
    """由 sharedSecret 派生 ``(aes_key, hmac_key)``。

    protocol 2 走 HKDF-SHA256（两个不同的 info 标签），protocol 1 两者都退化成
    ``SHA-256(shared)``。平台侧与设备侧都必须算出一致的值，所以独立成函数。
    """
    if int(protocol) == PROTOCOL_ONE:
        key = hashlib.sha256(shared).digest()
        return key, key
    aes_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=HKDF_SALT,
                   info=INFO_AES).derive(shared)
    hmac_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=HKDF_SALT,
                    info=INFO_HMAC).derive(shared)
    return aes_key, hmac_key


def auth_code(protocol, hmac_key, message):
    """``pinAuth`` / ``pinUvAuthParam`` 的计算方式（取 HMAC 前 16 字节）。"""
    algo = hashlib.sha1 if int(protocol) == PROTOCOL_ONE else hashlib.sha256
    return hmac.new(hmac_key, bytes(message), algo).digest()[:16]


# --------------------------------------------------------------------------- #
# 一次 clientPIN 交互的密钥状态
# --------------------------------------------------------------------------- #
class PinProtocol:
    """保存设备临时密钥、sharedSecret 与 pinToken。

    生命周期：平台每次走 clientPIN 都会先发 ``getKeyAgreement``（``begin``），
    拿到 pinToken 后用它算 MC/GA 的 pinUvAuthParam。整条链路的状态是共享的，
    因此这个对象由 :class:`Module.FidoService.FidoService` 单例持有。
    """

    def __init__(self):
        self.protocol = PROTOCOL_TWO
        self._private_key = None
        self._shared = None
        self._pin_token = None

    # ---- 状态 ------------------------------------------------------------ #
    def reset(self):
        self._private_key = None
        self._shared = None
        self._pin_token = None

    @property
    def has_secret(self):
        return self._shared is not None

    @property
    def pin_token(self):
        return self._pin_token

    def drop_token(self):
        """卡片被换掉/会话失效时作废 pinToken（平台需要重新验 PIN）。"""
        self._pin_token = None

    # ---- 密钥协商 -------------------------------------------------------- #
    def begin(self, protocol):
        """生成设备临时密钥对，返回要回给平台的 COSE_Key。"""
        protocol = int(protocol or PROTOCOL_TWO)
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ClientPinError("不支持的 pinUvAuthProtocol: %s" % protocol)
        self.protocol = protocol
        self._private_key = ec.generate_private_key(ec.SECP256R1())
        self._shared = None
        self._pin_token = None
        numbers = self._private_key.public_key().public_numbers()
        return {
            1: 2,                                        # kty = EC2
            3: ALG_ECDH_ES_HKDF_256,                     # alg
            -1: 1,                                       # crv = P-256
            -2: numbers.x.to_bytes(32, "big"),
            -3: numbers.y.to_bytes(32, "big"),
        }

    def agree(self, protocol, cose_key):
        """用平台的 COSE_Key 算 sharedSecret（必要时先重建设备密钥）。"""
        protocol = int(protocol or PROTOCOL_TWO)
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ClientPinError("不支持的 pinUvAuthProtocol: %s" % protocol)
        if self._private_key is None or protocol != self.protocol:
            # 平台换了协议（或跨进程重启）——必须重新协商，不能沿用旧密钥
            self.begin(protocol)
        if not isinstance(cose_key, dict):
            raise ClientPinError("缺少 keyAgreement 参数")
        try:
            x = int.from_bytes(bytes(cose_key.get(-2) or b""), "big")
            y = int.from_bytes(bytes(cose_key.get(-3) or b""), "big")
            peer = ec.EllipticCurvePublicNumbers(x, y,
                                                 ec.SECP256R1()).public_key()
        except (ValueError, TypeError) as err:
            raise ClientPinError("平台公钥无效: %s" % err)
        self._shared = self._private_key.exchange(ec.ECDH(), peer)
        return self._shared

    # ---- 对称密钥 -------------------------------------------------------- #
    def _hmac_key(self):
        if self._shared is None:
            raise ClientPinError("还没有协商 sharedSecret")
        return derive_keys(self.protocol, self._shared)[1]

    def _aes_key(self):
        if self._shared is None:
            raise ClientPinError("还没有协商 sharedSecret")
        return derive_keys(self.protocol, self._shared)[0]

    def _mac(self, key, message):
        return auth_code(self.protocol, key, message)

    # ---- 加解密 ---------------------------------------------------------- #
    def decrypt_pin_hash(self, blob):
        """解出平台送来的 ``SHA-256(PIN)[0:16]``。"""
        plain = _aes_cbc(self._aes_key(), blob, False)
        if len(plain) < 16:
            raise ClientPinError("pinHashEnc 长度不正确")
        return plain[:16]

    def decrypt_new_pin(self, blob):
        """解出 ``newPinEnc`` 里的 PIN 原文（只有 setPIN 时才有）。"""
        return _unpad_7816(_aes_cbc(self._aes_key(), blob, False))

    def encrypt_token(self, token=None):
        """生成（或沿用）pinToken 并返回加密后的字节串。"""
        token = token or secrets.token_bytes(TOKEN_LENGTH)
        self._pin_token = token
        return _aes_cbc(self._aes_key(), token, True)

    # ---- 完整性校验 ------------------------------------------------------ #
    def check_auth(self, pin_auth, message):
        """校验 clientPIN 请求里的 ``pinAuth``。"""
        expected = self._mac(self._hmac_key(), message)
        try:
            return hmac.compare_digest(expected, bytes(pin_auth))
        except TypeError:
            return False

    def check_token_auth(self, param, message):
        """校验 MC/GA 里的 ``pinUvAuthParam``（用 pinToken 做 MAC）。"""
        if not self._pin_token:
            return False
        expected = self._mac(self._pin_token, message)
        try:
            return hmac.compare_digest(expected, bytes(param))
        except TypeError:
            return False


# --------------------------------------------------------------------------- #
# 自检：模拟平台侧完整跑一遍协商 + 加密 PIN + 校验 pinAuth
# --------------------------------------------------------------------------- #
def _selftest():
    for protocol in SUPPORTED_PROTOCOLS:
        device = PinProtocol()
        device_key = device.begin(protocol)

        # 平台侧：生成密钥对，算出 sharedSecret，构造 pinHashEnc
        platform_key = ec.generate_private_key(ec.SECP256R1())
        peer = ec.EllipticCurvePublicNumbers(
            int.from_bytes(device_key[-2], "big"),
            int.from_bytes(device_key[-3], "big"),
            ec.SECP256R1()).public_key()
        platform_numbers = platform_key.public_key().public_numbers()
        platform_cose = {1: 2, 3: ALG_ECDH_ES_HKDF_256, -1: 1,
                         -2: platform_numbers.x.to_bytes(32, "big"),
                         -3: platform_numbers.y.to_bytes(32, "big")}
        device.agree(protocol, platform_cose)

        # 双方算出的 sharedSecret 必须一致
        shared = platform_key.exchange(ec.ECDH(), peer)
        assert shared == device._shared, "ECDH 结果不一致"
        aes_key = device._aes_key()
        hmac_key = device._hmac_key()
        if protocol == PROTOCOL_ONE:
            assert aes_key == hashlib.sha256(shared).digest()
        else:
            assert aes_key == HKDF(algorithm=hashes.SHA256(), length=32,
                                   salt=HKDF_SALT, info=INFO_AES).derive(shared)
            assert hmac_key == HKDF(algorithm=hashes.SHA256(), length=32,
                                    salt=HKDF_SALT, info=INFO_HMAC).derive(shared)

        digest = pin_digest("12345678")
        pin_hash_enc = _aes_cbc(aes_key, digest, True)
        assert device.decrypt_pin_hash(pin_hash_enc) == digest

        algo = hashlib.sha1 if protocol == PROTOCOL_ONE else hashlib.sha256
        pin_auth = hmac.new(hmac_key, pin_hash_enc, algo).digest()[:16]
        assert device.check_auth(pin_auth, pin_hash_enc)

        # pinToken 往返 + pinUvAuthParam
        token_enc = device.encrypt_token()
        platform_token = _aes_cbc(aes_key, token_enc, False)
        assert platform_token == device.pin_token
        challenge = hashlib.sha256(b"client-data").digest()
        param = hmac.new(platform_token, challenge, algo).digest()[:16]
        assert device.check_token_auth(param, challenge)

        # 错误的 pinAuth 必须被拒
        assert not device.check_auth(b"\x00" * 16, pin_hash_enc)

        # newPinEnc 的 7816 填充往返
        new_pin = "87654321"
        enc = _aes_cbc(aes_key, _pad_7816(new_pin.encode()), True)
        assert device.decrypt_new_pin(enc).decode() == new_pin
        print("protocol %d 通过" % protocol)
    print("FidoClientPin 自检通过")


if __name__ == "__main__":
    _selftest()
