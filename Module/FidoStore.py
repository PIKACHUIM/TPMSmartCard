# -*- coding: utf-8 -*-
"""FIDO2 凭据存储：用 TPM 虚拟智能卡（PIN）+ 本机 DPAPI 双层保护私钥。

安全模型
--------
一条 FIDO2 凭据的私钥（P-256 标量）**从不以明文落盘**，加密分三层：

1. ``tempKey``：每条凭据随机 32 字节，用它 AES-256-GCM 加密私钥；
2. 卡片层：``wrapKey = HMAC-SHA256(masterKey, tempKeySalt)``，
   ``masterKey = PBKDF2-SHA256(PIN, salt)``。PIN 由**卡片**校验（TPM 内的
   PIN 重试计数器），所以「知道 PIN」这件事是被硬件强制的；
3. 本机层：第 2 层的结果再用 DPAPI **机器作用域**封装一次。这样即使
   ``%APPDATA%`` 下的文件被拷走，没有这台机器（也就没有这把 DPAPI 主密钥）
   也解不出内层，离线暴力猜 8 位 PIN 失去意义。

``masterKey`` 另有一份 DPAPI 机器作用域封装的 ``guard``，作用是：
改 PIN / PUK 解锁之后能取回旧 masterKey，把已有凭据重新封装到新 PIN 下，
不至于「改个 PIN 就把 passkey 全废了」。它同样只在本机可用。

存储位置
--------
``%APPDATA%\\TPMSmartCard\\Fido\\cards\\<卡片标识>.json``

卡片标识优先用 TPM 虚拟卡的 store GUID（备份还原后不变），取不到时退回
读卡器序列号。备份（``.tsb``）会把 ``export_for_backup()`` 的结果一起打包，
里面是「去掉 DPAPI 外层」的内层密文——仍然需要 PIN 才能解开。
"""

import base64
import datetime
import hashlib
import hmac
import json
import os
import secrets
import uuid as uuid_module

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from Module import DPAPI
from Module import Paths

# 凭据文件格式版本
STORE_VERSION = 1
# PIN → masterKey 的 KDF 迭代次数（提高离线爆破成本）
KDF_ITERATIONS = 200000
# 认证器 AAGUID（16 字节，固定值，RP 据此识别「同一型号」的认证器）
AAGUID = b"TPMSmartCardFIDO"
# DPAPI 描述（便于 openssl/dpapi 工具排查）
DPAPI_DESCRIPTION = "TPMSMART-FIDO"
# 外层封装方式
OUTER_DPAPI = "dpapi-machine"
OUTER_NONE = "none"

CARDS_DIR = "cards"
SETTINGS_NAME = "settings.json"


class StoreError(Exception):
    """凭据存储的可预期错误（界面直接展示 message）。"""


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def b64e(data):
    return base64.b64encode(bytes(data)).decode("ascii")


def b64d(text):
    return base64.b64decode(str(text or ""))


def b64url(data):
    """base64url（无填充），WebAuthn 的 credentialId / userHandle 用这个。"""
    return base64.urlsafe_b64encode(bytes(data)).decode("ascii").rstrip("=")


def b64url_decode(text):
    raw = str(text or "")
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def _aes_encrypt(key, plaintext, aad=None):
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, bytes(plaintext), aad)


def _aes_decrypt(key, blob, aad=None):
    blob = bytes(blob)
    if len(blob) <= 12:
        raise StoreError("密文长度不正确")
    return AESGCM(key).decrypt(blob[:12], blob[12:], aad)


def derive_master_key(pin, salt, iterations=KDF_ITERATIONS):
    """由卡片 PIN 派生 masterKey（PBKDF2-HMAC-SHA256, 32 字节）。"""
    return hashlib.pbkdf2_hmac("sha256", str(pin).encode("utf-8"), bytes(salt),
                               int(iterations), dklen=32)


def _wrap_outer(inner):
    """内层密文 → (落盘密文, 外层类型)。DPAPI 不可用时退化为不加外层。"""
    blob, _note = DPAPI.protect(inner, flags=DPAPI.FLAG_MACHINE,
                                description=DPAPI_DESCRIPTION)
    if blob:
        return bytes(blob), OUTER_DPAPI
    return bytes(inner), OUTER_NONE


def _unwrap_outer(blob, outer):
    """落盘密文 → 内层密文。"""
    blob = bytes(blob or b"")
    if outer != OUTER_DPAPI:
        return blob
    plain, note = DPAPI.unprotect(blob, accounts=(None,),
                                  flags=(DPAPI.FLAG_MACHINE,))
    if plain is None:
        raise StoreError("本机 DPAPI 解不开该凭据（备份来自其它电脑，或系统重装过）：%s" % note)
    return bytes(plain)


def card_key(guid="", serial="", name=""):
    """卡片在 FIDO 存储里的唯一标识（同时也是文件名，必须安全）。

    优先用 store GUID（备份还原后不变），其次读卡器序列号，最后用卡片名哈希。
    """
    guid = str(guid or "").strip().strip("{}").lower()
    if guid:
        return "guid-%s" % guid.replace("-", "")
    serial = str(serial or "").strip().lower()
    if serial:
        safe = "".join(ch for ch in serial if ch.isalnum())[:32]
        if safe:
            return "serial-%s" % safe
    digest = hashlib.sha1(str(name or "").encode("utf-8")).hexdigest()[:16]
    return "name-%s" % digest


def cards_dir():
    folder = os.path.join(Paths.fido_dir(), CARDS_DIR)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        pass
    return folder


def settings_path():
    return os.path.join(Paths.fido_dir(), SETTINGS_NAME)


def card_path(key):
    return os.path.join(cards_dir(), "%s.json" % key)


# --------------------------------------------------------------------------- #
# 全局设置（服务开关、会话超时等）
# --------------------------------------------------------------------------- #
DEFAULT_SETTINGS = {
    # 驱动装好就默认开启：装上驱动、开机启动之后不必再手动去设置里点一次
    "enabled": True,            # FIDO2 服务总开关
    "autostart": False,         # 随程序自启（登录后常驻）
    "session_timeout": 900,     # PIN 认证有效时间（秒）
    "driver_hint_shown": False,  # 是否已提示过安装驱动
    # PIN 由谁收集：clientpin = 平台的 PIN 对话框（推荐，只有一个框）；
    # builtin = 本程序自己弹框（老行为，平台只显示「触摸安全密钥」）
    "pin_mode": "clientpin",
    "active_card": "",          # clientPIN 当前绑定的卡片（按读卡器名）
}


def read_settings():
    settings = dict(DEFAULT_SETTINGS)
    path = settings_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return settings
    if isinstance(data, dict):
        for key in DEFAULT_SETTINGS:
            if key in data:
                settings[key] = data[key]
    return settings


def write_settings(settings):
    path = settings_path()
    payload = dict(DEFAULT_SETTINGS)
    payload.update(settings or {})
    tmp = "%s.tmp" % path
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return payload


# --------------------------------------------------------------------------- #
# 单张卡的凭据库
# --------------------------------------------------------------------------- #
class FidoStore:
    """一张卡片对应的 FIDO2 凭据集合。"""

    def __init__(self, key, data=None):
        self.key = key
        self.data = data or self._blank()

    # ---- 构造/加载 ------------------------------------------------------- #
    @staticmethod
    def _blank():
        salt = secrets.token_bytes(32)
        return {
            "version": STORE_VERSION,
            "card": {"guid": "", "serial": "", "name": "", "enabled": True},
            "kdf": {"algo": "pbkdf2-sha256", "iterations": KDF_ITERATIONS,
                    "salt": b64e(salt)},
            "guard": None,
            "pin_verifier": None,
            "credentials": [],
            "created_at": _now(),
            "updated_at": _now(),
        }

    @classmethod
    def load(cls, key):
        path = card_path(key)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as err:
            raise StoreError("凭据文件无法读取: %s (%s)" % (path, err))
        if not isinstance(data, dict) or "credentials" not in data:
            raise StoreError("凭据文件格式不正确: %s" % path)
        return cls(key, data)

    @classmethod
    def open(cls, guid="", serial="", name="", create=True):
        """按卡片身份打开（必要时新建）凭据库。"""
        key = card_key(guid, serial, name)
        store = cls.load(key)
        if store is not None:
            changed = False
            for field, value in (("guid", guid), ("serial", serial), ("name", name)):
                if value and store.data["card"].get(field) != value:
                    store.data["card"][field] = value
                    changed = True
            if changed:
                store.save()
            return store
        if not create:
            return None
        store = cls(key)
        store.data["card"].update({"guid": str(guid or ""),
                                   "serial": str(serial or ""),
                                   "name": str(name or "")})
        store.save()
        return store

    @classmethod
    def list_all(cls):
        """列出所有卡片的凭据库（界面/统计用）。"""
        stores = []
        folder = cards_dir()
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            return stores
        for name in names:
            if not name.lower().endswith(".json"):
                continue
            try:
                store = cls.load(name[:-5])
            except StoreError:
                continue
            if store is not None:
                stores.append(store)
        return stores

    def save(self):
        self.data["updated_at"] = _now()
        path = card_path(self.key)
        tmp = "%s.tmp" % path
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path

    def delete_file(self):
        try:
            os.remove(card_path(self.key))
            return True
        except OSError:
            return False

    # ---- 卡片信息 -------------------------------------------------------- #
    @property
    def credentials(self):
        # 注意：不能用 ``or []``——空列表会被替换成新的临时对象，后续 append
        # 写不回去（曾经因此出现「新增后立刻找不到凭据」）。
        items = self.data.get("credentials")
        if not isinstance(items, list):
            items = []
            self.data["credentials"] = items
        return items

    @property
    def card(self):
        info = self.data.get("card")
        if not isinstance(info, dict):
            info = {}
            self.data["card"] = info
        return info

    @property
    def enabled(self):
        return bool(self.card.get("enabled", True))

    def set_enabled(self, enabled):
        self.data["card"]["enabled"] = bool(enabled)
        self.save()

    @property
    def display_name(self):
        card = self.card
        return card.get("name") or card.get("serial") or self.key

    # ---- 密钥派生 / 解锁 ------------------------------------------------- #
    @property
    def salt(self):
        return b64d(self.data["kdf"].get("salt"))

    @property
    def iterations(self):
        return int(self.data["kdf"].get("iterations") or KDF_ITERATIONS)

    def master_key(self, pin):
        """由 PIN 派生 masterKey（不做校验）。"""
        return derive_master_key(pin, self.salt, self.iterations)

    def unlock(self, pin):
        """校验 PIN 并返回 masterKey；PIN 与库不匹配时返回 ``None``。

        校验顺序：优先用 ``guard``（DPAPI 封装的 masterKey）比对，
        guard 不可用（换机/重装过）时退化为「拿第一条凭据试解」。
        """
        master = self.master_key(pin)
        guard = self.data.get("guard")
        if guard:
            try:
                plain = _unwrap_outer(b64d(guard.get("data")), guard.get("outer"))
            except StoreError:
                plain = None
            if plain is not None:
                return master if hmac.compare_digest(plain, master) else None
        if not self.credentials:
            # 空库：任何 PIN 都算「新建」，guard 在首次写入时建立
            return master
        record = self.credentials[0].get("secret") or {}
        try:
            self._unwrap_secret(master, record)
            return master
        except StoreError:
            return None

    def remember_master(self, master):
        """把 masterKey 用 DPAPI 封装存进 ``guard``（改 PIN / 解锁后调用）。"""
        blob, outer = _wrap_outer(bytes(master))
        self.data["guard"] = {"algo": "dpapi-machine", "outer": outer,
                              "data": b64e(blob)}
        self.save()

    def recover_master(self):
        """从 guard 取回 masterKey（PIN 被 PUK 重置后重新封装用）。"""
        guard = self.data.get("guard")
        if not guard:
            return None
        try:
            return _unwrap_outer(b64d(guard.get("data")), guard.get("outer"))
        except StoreError:
            return None

    # ---- clientPIN（PIN 由 Windows 收集）--------------------------------- #
    # 平台在 clientPIN 流程里只送 SHA-256(PIN)[0:16]，设备永远看不到 PIN 原文，
    # 所以比对材料必须留一份。外层再套本机 DPAPI：文件被拷到别的机器也读不出。
    @property
    def has_pin_verifier(self):
        return bool(self.data.get("pin_verifier"))

    def set_pin_verifier(self, pin):
        """记录 PIN 的哈希（应在**卡片已校验过该 PIN**之后调用）。"""
        digest = hashlib.sha256(str(pin).encode("utf-8")).digest()[:16]
        blob, outer = _wrap_outer(digest)
        self.data["pin_verifier"] = {"algo": "sha256-16", "outer": outer,
                                    "data": b64e(blob)}
        self.save()

    def check_pin_verifier(self, digest):
        record = self.data.get("pin_verifier")
        if not record:
            return False
        try:
            plain = _unwrap_outer(b64d(record.get("data")), record.get("outer"))
        except StoreError:
            return False
        return hmac.compare_digest(bytes(plain)[:16], bytes(digest)[:16])

    def clear_pin_verifier(self):
        if self.data.get("pin_verifier") is not None:
            self.data["pin_verifier"] = None
            self.save()

    # ---- 凭据 ------------------------------------------------------------ #
    def _unwrap_secret(self, master, record):
        temp_salt = b64d(record.get("temp_key_salt"))
        try:
            temp_key = _aes_decrypt(hmac.new(bytes(master), temp_salt,
                                             hashlib.sha256).digest(),
                                    b64d(record.get("temp_key_enc")))
            inner = _unwrap_outer(b64d(record.get("data")), record.get("outer"))
            return _aes_decrypt(temp_key, inner)
        except InvalidTag:
            # AES-GCM 认证失败 = 密钥不对（PIN 与凭据库不匹配）
            raise StoreError("PIN 与凭据库不匹配（解密认证失败）")

    def _pack_secret(self, master, payload):
        temp_key = secrets.token_bytes(32)
        temp_salt = secrets.token_bytes(16)
        temp_key_enc = _aes_encrypt(hmac.new(bytes(master), temp_salt,
                                             hashlib.sha256).digest(), temp_key)
        inner = _aes_encrypt(temp_key, payload)
        data, outer = _wrap_outer(inner)
        return {"version": 1, "outer": outer,
                "temp_key_salt": b64e(temp_salt),
                "temp_key_enc": b64e(temp_key_enc),
                "data": b64e(data)}

    def add_credential(self, master, meta, secret_payload):
        """新增一条凭据；``secret_payload`` 是私钥的原始字节。"""
        self._refresh_from_disk()      # 别把内存里已删除的旧条目带回来
        entry = {
            "uuid": str(uuid_module.uuid4()),
            "meta": dict(meta or {}),
            "secret": self._pack_secret(master, secret_payload),
            "created_at": _now(),
            "last_used_at": "",
        }
        self.credentials.append(entry)
        self.save()
        return entry

    def get_secret(self, master, entry_uuid):
        """解出某条凭据的私钥原始字节。"""
        entry = self.find_by_uuid(entry_uuid)
        if entry is None:
            raise StoreError("找不到凭据: %s" % entry_uuid)
        try:
            return self._unwrap_secret(master, entry.get("secret") or {})
        except (InvalidTag, StoreError) as err:
            raise StoreError("凭据解密失败（PIN 与凭据库不匹配）: %s" % err)

    def find_by_uuid(self, entry_uuid):
        for entry in self.credentials:
            if entry.get("uuid") == entry_uuid:
                return entry
        return None

    def find_by_credential_id(self, credential_id):
        want = b64url_decode(credential_id) if isinstance(credential_id, str) else bytes(credential_id)
        for entry in self.credentials:
            current = b64url_decode((entry.get("meta") or {}).get("credential_id"))
            if hmac.compare_digest(current, want):
                return entry
        return None

    def find_for_rp(self, rp_id, allow_ids=None):
        """按 RP ID（以及可选 allowList）挑出可用凭据。"""
        matches = []
        allow = None
        if allow_ids:
            allow = [bytes(item) for item in allow_ids]
        for entry in self.credentials:
            meta = entry.get("meta") or {}
            if str(meta.get("rp_id") or "") != str(rp_id or ""):
                continue
            if allow is not None:
                cred_id = b64url_decode(meta.get("credential_id"))
                if not any(hmac.compare_digest(cred_id, item) for item in allow):
                    continue
            matches.append(entry)
        return matches

    def _refresh_from_disk(self):
        """写之前把磁盘内容读回内存（磁盘才是权威）。

        会话里的 store 是一份可能在内存里放了很久的副本；如果直接整份写回，
        会把「别处刚删掉的凭据」复活（实测现象：界面删了凭据，重启程序又出现，
        而且还能拿它认证）。所以所有写操作先对齐磁盘。
        """
        latest = FidoStore.load(self.key)
        if latest is not None and latest.data is not self.data:
            self.data = latest.data
        return self.data

    def bump_counter(self, entry_uuid, value=None):
        """递增签名计数器（防重放）；返回新值。"""
        self._refresh_from_disk()
        entry = self.find_by_uuid(entry_uuid)
        if entry is None:
            # 磁盘上已经没有这条凭据（被删了）：不写盘，免得又把它写回去
            return 0
        meta = entry.setdefault("meta", {})
        counter = int(meta.get("counter") or 0)
        counter = (counter + 1) if value is None else int(value)
        meta["counter"] = counter & 0xFFFFFFFF
        entry["last_used_at"] = _now()
        self.save()
        return meta["counter"]

    def delete_credential(self, entry_uuid):
        self._refresh_from_disk()
        before = len(self.credentials)
        self.data["credentials"] = [item for item in self.credentials
                                    if item.get("uuid") != entry_uuid]
        if len(self.data["credentials"]) == before:
            return False
        self.save()
        return True

    def clear_credentials(self):
        self._refresh_from_disk()
        self.data["credentials"] = []
        self.save()

    # ---- PIN 变更后的重新封装 -------------------------------------------- #
    def rotate_master(self, old_master, new_master):
        """PIN 变更：把每条凭据的 tempKey 从旧 masterKey 迁移到新 masterKey。

        inner（真正加密私钥的那层）不动，只重算 tempKeyEnc，避免大文件重写。
        """
        if not old_master or not new_master:
            raise StoreError("缺少旧/新 PIN 派生的密钥")
        changed = 0
        for entry in self.credentials:
            record = entry.get("secret") or {}
            try:
                unwrapped = self._unwrap_secret(old_master, record)
            except StoreError as err:
                raise StoreError("有凭据无法用旧 PIN 解开，已中止改 PIN 后的重新封装: %s" % err)
            # 重新打包整条记录（tempKey 换新，inner 重算，外层重新 DPAPI）
            entry["secret"] = self._pack_secret(new_master, unwrapped)
            changed += 1
            del unwrapped
        self.remember_master(new_master)
        return changed

    # ---- 备份 / 还原 ----------------------------------------------------- #
    def export_for_backup(self):
        """导出为可放进 ``.tsb`` 的结构（去掉仅本机可用的 DPAPI 外层）。"""
        exported = []
        warnings = []
        for entry in self.credentials:
            record = entry.get("secret") or {}
            try:
                inner = _unwrap_outer(b64d(record.get("data")), record.get("outer"))
                outer = OUTER_NONE
            except StoreError as err:
                # 解不开外层就只能带上原样密文（换机后不可用），并提示用户
                inner = b64d(record.get("data"))
                outer = record.get("outer")
                warnings.append("凭据 %s 的 DPAPI 外层无法解开，备份里保存的是原样密文"
                                "（仅在当前系统可用）: %s"
                                % (entry.get("uuid"), err))
            exported.append({
                "uuid": entry.get("uuid"),
                "meta": entry.get("meta") or {},
                "created_at": entry.get("created_at", ""),
                "last_used_at": entry.get("last_used_at", ""),
                "secret": {"outer": outer,
                           "temp_key_salt": record.get("temp_key_salt"),
                           "temp_key_enc": record.get("temp_key_enc"),
                           "inner": b64e(inner)},
            })
        payload = {
            "version": STORE_VERSION,
            "key": self.key,
            "card": self.card,
            "kdf": self.data.get("kdf"),
            "exported_at": _now(),
            "credentials": exported,
        }
        return payload, warnings

    def import_from_backup(self, payload):
        """从 ``.tsb`` 里的结构合并回来；返回 ``(新增条数, 跳过条数, 警告列表)``。"""
        warnings = []
        if not isinstance(payload, dict):
            raise StoreError("备份里的 FIDO 数据格式不正确")
        source = payload.get("kdf") or {}
        if source.get("salt"):
            # 保留原盐与迭代次数：凭据是用这个盐派生的 masterKey 封装的
            self.data["kdf"] = {"algo": "pbkdf2-sha256",
                                "iterations": int(source.get("iterations") or KDF_ITERATIONS),
                                "salt": source.get("salt")}
        card = payload.get("card") or {}
        for field in ("guid", "serial", "name"):
            if card.get(field) and not self.data["card"].get(field):
                self.data["card"][field] = card[field]
        added = 0
        skipped = 0
        for item in payload.get("credentials") or []:
            meta = item.get("meta") or {}
            if not meta.get("credential_id"):
                skipped += 1
                continue
            if self.find_by_credential_id(meta["credential_id"]) is not None:
                skipped += 1
                continue
            secret = item.get("secret") or {}
            inner = b64d(secret.get("inner"))
            data, outer = _wrap_outer(inner)
            self.credentials.append({
                "uuid": item.get("uuid") or str(uuid_module.uuid4()),
                "meta": meta,
                "secret": {"version": 1, "outer": outer,
                           "temp_key_salt": secret.get("temp_key_salt"),
                           "temp_key_enc": secret.get("temp_key_enc"),
                           "data": b64e(data)},
                "created_at": item.get("created_at") or _now(),
                "last_used_at": item.get("last_used_at") or "",
            })
            added += 1
        if added:
            # 换了机器之后 DPAPI 层已重建，但 masterKey 需要用户下次输 PIN 时重建 guard
            self.save()
        if payload.get("credentials") and not added:
            warnings.append("备份里的 FIDO 凭据都已存在，未重复导入")
        return added, skipped, warnings

    # ---- 展示用 ---------------------------------------------------------- #
    def summary(self):
        return {
            "key": self.key,
            "name": self.display_name,
            "guid": self.card.get("guid", ""),
            "serial": self.card.get("serial", ""),
            "enabled": self.enabled,
            "count": len(self.credentials),
            "updated_at": self.data.get("updated_at", ""),
        }


if __name__ == "__main__":
    # 自检：不接触真实卡片，纯软件层验证加密/解密/导出/导入
    store = FidoStore("selftest")
    master = store.unlock("12345678")
    assert master, "空库应接受任意 PIN"
    store.remember_master(master)
    secret = secrets.token_bytes(32)
    entry = store.add_credential(master, {"rp_id": "example.com",
                                          "credential_id": b64url(secrets.token_bytes(32)),
                                          "counter": 0}, secret)
    assert store.get_secret(master, entry["uuid"]) == secret
    assert store.unlock("12345678") == master
    assert store.unlock("87654321") is None
    new_master = store.master_key("87654321")
    assert store.rotate_master(master, new_master) == 1
    assert store.get_secret(new_master, entry["uuid"]) == secret
    payload, warns = store.export_for_backup()
    print("导出凭据 %d 条，警告 %d 条" % (len(payload["credentials"]), len(warns)))
    other = FidoStore("selftest-copy")
    added, skipped, warns2 = other.import_from_backup(payload)
    print("导入新增 %d 条，跳过 %d 条" % (added, skipped))
    assert added == 1
    assert other.get_secret(new_master, other.credentials[0]["uuid"]) == secret
    store.delete_file()
    other.delete_file()
    print("FidoStore 自检通过")
