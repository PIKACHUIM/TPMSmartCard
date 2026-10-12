import hashlib
import re

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend


class Crypto:
    # 取件码（自协商）模式：字母表与规范化规则必须与服务端保持一致 ============
    # 服务端实现见 PikaTestCert/worker/src/lib/card-code.ts 的 normalizeCode()
    #   · 去掉一切非 [0-9A-Z] 字符（大小写、分隔符均可忽略）
    #   · O → 0、I → 1、L → 1（服务端生成的取件码不含 I / L / O）
    @staticmethod
    def normalize_code(in_code):
        text = re.sub(r'[^0-9A-Z]', '', str(in_code or "").upper())
        return text.replace("O", "0").replace("I", "1").replace("L", "1")

    @staticmethod
    def code_key(in_code, in_salt, in_iterations):
        """由取件码 + 盐 + 迭代次数派生 32 字节 AES-256 密钥（PBKDF2-SHA256）。

        与服务端 WebCrypto 的 PBKDF2 派生结果完全一致。
        """
        return hashlib.pbkdf2_hmac(
            "sha256",
            Crypto.normalize_code(in_code).encode("utf-8"),
            in_salt,
            int(in_iterations),
            dklen=32
        )

    @staticmethod
    def aes_encrypt(key, data):
        # 生成初始向量 ========================================
        iv = b'\x00' * 16
        # 创建AES2对象 ========================================
        ciphers = Cipher(
            algorithms.AES(key),
            modes.CBC(iv),
            backend=default_backend())
        encrypt = ciphers.encryptor()
        # 加密明文数据 ========================================
        padders = padding.PKCS7(128).padder()
        results = padders.update(data) + padders.finalize()
        results = encrypt.update(results) + encrypt.finalize()
        return results

    @staticmethod
    def aes_decrypt(key, data):
        # 生成初始向量 ========================================
        iv = b'\x00' * 16  # AES 的初始向量
        # 创建AES2对象 ========================================
        ciphers = Cipher(
            algorithms.AES(key),
            modes.CBC(iv),
            backend=default_backend())
        decrypt = ciphers.decryptor()
        # 解密加密数据 ========================================
        origins = decrypt.update(data) + decrypt.finalize()
        padders = padding.PKCS7(128).unpadder()
        origins = padders.update(origins) + padders.finalize()
        return origins
