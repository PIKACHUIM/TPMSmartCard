# -*- coding: utf-8 -*-
"""UI 冒烟测试：构造系统设置窗口（含 FIDO2 页签）后立即关闭。"""
import os
import sys
import tkinter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from Module.I18n import get_i18n              # noqa: E402
from SubApp.SystemSettings import SystemSettings  # noqa: E402

root = tkinter.Tk()
root.withdraw()
errors = []


def hook(exc_type, exc_value, exc_tb):
    import traceback
    errors.append("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))


root.report_callback_exception = hook
window = SystemSettings(root, get_i18n(), (100, 100))
print("窗口已创建，页签数:", len(window.notebook.tabs()))


def finish():
    print("FIDO 状态文本:\n%s" % window.fido_status_var.get())
    print("凭据行数:", len(window.fido_rows))
    window.close()
    root.after(100, root.destroy)


root.after(2500, finish)
root.mainloop()
print("回调异常:", len(errors))
for item in errors:
    print(item)
