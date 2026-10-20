# -*- coding: utf-8 -*-
"""FIDO2 凭据与 .tsb 备份衔接的自检（不需要真卡）。

验证：导出（剥掉本机 DPAPI 外层）→ 模拟"换系统"（删掉本机凭据库）→
还原（用目标机 DPAPI 重新封装）→ 用同一个 PIN 仍能解出私钥。

用法::

    python Fido/src/devtest/fido_backup_test.py
"""
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
from Module import FidoStore                                           # noqa: E402

PIN = "12345678"
CARD_NAME = "Microsoft Virtual Smart Card 0"
GUID = "5f2a7c31-0000-4000-8000-00000000beef"


class FakePackage:
    """最小化的 .tsb 读取器（只实现 exists/read）。"""

    def __init__(self, files):
        self.files = dict(files)

    def exists(self, rel):
        return str(rel).replace("\\", "/") in self.files

    def read(self, rel):
        return self.files[str(rel).replace("\\", "/")]


def main():
    folder = tempfile.mkdtemp(prefix="tpmsc-fido-backup-")
    original = FidoStore.cards_dir
    FidoStore.cards_dir = lambda: folder
    failures = []

    def check(name, condition, detail=""):
        print("%s %s%s" % ("[OK]  " if condition else "[失败]", name,
                           ("  → " + str(detail)) if detail else ""))
        if not condition:
            failures.append(name)

    try:
        store = FidoStore.FidoStore.open(GUID, "aabbccdd", CARD_NAME)
        master = store.unlock(PIN)
        assert master, "新库应接受任意 PIN"
        store.remember_master(master)
        secret = secrets.token_bytes(32)
        store.add_credential(master, {
            "rp_id": "example.com", "rp_name": "Example",
            "user_name": "alice", "user_display_name": "Alice",
            "credential_id": FidoStore.b64url(secrets.token_bytes(32)),
            "algorithm": -7, "counter": 3,
        }, secret)
        check("准备一张卡的凭据", len(store.credentials) == 1)

        section, files, log = FidoBackup.collect(guid=GUID, name=CARD_NAME)
        print("  " + "；".join(log))
        check("导出：识别到凭据", section and section["count"] == 1, section)
        check("导出：生成 fido/ 文件", len(files) == 1 and
              files[0][0].startswith("fido/"), files[0][0] if files else "")
        raw = files[0][1].decode("utf-8")
        check("导出：不含 DPAPI 外层标记", '"dpapi-machine"' not in raw)
        check("导出：不含 guard（本机密钥不随包外泄）", '"guard"' not in raw)

        # 模拟「重装系统」：本机凭据库没了
        store.delete_file()
        check("模拟换系统：凭据库已删除",
              FidoStore.FidoStore.load(store.key) is None)

        package = FakePackage(files)
        logs = []
        added, skipped = FidoBackup.restore(package, section, guid=GUID, log=logs)
        print("  " + "；".join(logs))
        check("还原：写回凭据", added == 1 and skipped == 0, (added, skipped))

        restored = FidoStore.FidoStore.load(store.key)
        check("还原：凭据库存在", restored is not None)
        restored_master = restored.unlock(PIN)
        check("还原：同一 PIN 可解锁", restored_master is not None)
        if restored_master:
            entry = restored.credentials[0]
            check("还原：私钥可解出且一致",
                  restored.get_secret(restored_master, entry["uuid"]) == secret)
            check("还原：计数器保留", entry["meta"]["counter"] == 3,
                  entry["meta"]["counter"])
        check("还原：错误 PIN 解不开", restored.unlock("00000000") is None)
    finally:
        FidoStore.cards_dir = original
        shutil.rmtree(folder, ignore_errors=True)

    print()
    if failures:
        print("自检失败 %d 项: %s" % (len(failures), "、".join(failures)))
        return 1
    print("备份衔接自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
