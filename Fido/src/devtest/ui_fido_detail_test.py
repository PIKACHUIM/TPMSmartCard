# -*- coding: utf-8 -*-
"""主界面「通行密钥详情」自检（不需要真卡、不进事件循环）。

覆盖：
1. 选中 FIDO2 凭据时只显示「通行密钥信息」分组，证书那三组整块收起；
2. 选中证书时反过来（证书分组显示、通行密钥分组收起）；
3. 主页的「删除」对通行密钥同样有效（以前判空后直接不响应）。

用法::

    python Fido/src/devtest/ui_fido_detail_test.py
"""
import os
import sys
import tkinter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# 不进事件循环：只把界面建起来，然后手动 update()
tkinter.Tk.mainloop = lambda self, n=0: None

import SmartCardAPP as A                                              # noqa: E402


def main():
    checks = []

    def check(name, ok, detail=""):
        checks.append(bool(ok))
        print("[%s] %s%s" % ("OK" if ok else "失败", name,
                             ("  → %s" % (detail,)) if detail != "" else ""))

    # 启动路径上的耗时/弹窗动作统统跳过，只测界面逻辑
    A.SmartCardAPP.startup_fido = lambda self: None
    A.SmartCardAPP.startup_ssh_agent = lambda self: None
    A.SmartCardAPP.setup_tray = lambda self: None
    A.SmartCardAPP.open_backup = lambda self: None
    A.SmartCardAPP.check_datas = lambda self: None
    A.SmartCardAPP.load_status = lambda self, in_async=False: None

    app = A.SmartCardAPP()
    app.root.update()

    def managed(group, field):
        widget = app.labels[group][field][1]
        return widget.winfo_manager() == "place"

    check("通行密钥分组已建好", bool(app.labels.get("fido_info")),
          list((app.labels.get("fido_info") or {}).keys()))
    check("初始状态：所有详情分组都收起",
          not any(managed(group, field)
                  for group in ("cert_info", "cert_user", "cert_last", "fido_info")
                  for field in app.labels[group]))

    # ---- 选中一条通行密钥 -------------------------------------------------- #
    tree = app.tables["cert_main"][0]
    app.fido_rows = {"uuid-demo": {
        "uuid": "uuid-demo", "card_key": "demo-key",
        "card": "Microsoft Virtual Smart Card 0",
        "rp_id": "www.token2.com", "rp_name": "TOKEN2 FIDO2 Demo",
        "user_name": "token2_user_857c201c",
        "credential_id": "6jIpQsDcboSF_sxhyQpzbvD8byNDh9x",
        "created_at": "2026-10-23 16:29:36",
        "last_used_at": "2026-10-23 16:30:02",
    }}
    tree.insert("", "end", values=("uuid-demo", "www.token2.com", "FIDO2", "ES256"))
    tree.selection_set(tree.get_children()[0])
    app.root.update()

    check("选中通行密钥：显示「通行密钥信息」分组",
          all(managed("fido_info", field) for field in app.labels["fido_info"]))
    check("选中通行密钥：证书三组收起",
          not any(managed(group, field)
                  for group in ("cert_info", "cert_user", "cert_last")
                  for field in app.labels[group]))
    check("站点已填入", app.labels["fido_info"]["msg_fido_cred_rp"][1].cget("text")
          == "www.token2.com")
    check("用户名已填入",
          app.labels["fido_info"]["msg_fido_cred_user"][1].cget("text")
          == "token2_user_857c201c")
    check("卡片已填入",
          app.labels["fido_info"]["msg_fido_cred_card"][1].cget("text")
          == "Microsoft Virtual Smart Card 0")
    check("凭据 ID 已填入",
          len(app.labels["fido_info"]["msg_fido_cred_id"][1].cget("text")) > 10)
    check("选中标识是 fido:<uuid>", app.pick["cert"] == "fido:uuid-demo",
          app.pick["cert"])
    check("删除按钮可用",
          str(app.button["cert_main"]["non"].cget("state")) != "disabled")

    # ---- 删除入口：应当真的弹出确认框（以前通行密钥选不中这个分支） -------- #
    app.data_delete("cert")
    app.root.update_idletasks()
    dialogs = [child for child in app.root.winfo_children()
               if child.winfo_class() == "Toplevel"]
    titles = [dialog.title() for dialog in dialogs]
    check("主页「删除」对通行密钥弹出确认框", bool(dialogs), titles)
    for dialog in dialogs:
        app.close_dialog(dialog)

    # ---- 选中证书：分成反过来 --------------------------------------------- #
    tree.insert("", "end", values=("cert-uuid", "测试证书", "P-256", "ES256"))
    tree.selection_set(tree.get_children()[-1])
    app.root.update()
    check("选中证书：显示证书分组",
          all(managed("cert_info", field) for field in app.labels["cert_info"]))
    check("选中证书：通行密钥分组收起",
          not any(managed("fido_info", field) for field in app.labels["fido_info"]))

    app.root.destroy()
    passed = sum(1 for item in checks if item)
    print("\n主界面通行密钥详情：%d/%d 项通过" % (passed, len(checks)))
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
