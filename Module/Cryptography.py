from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend


class Crypto:
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
