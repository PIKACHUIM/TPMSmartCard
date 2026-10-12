from tkcalendar import DateEntry
import tkinter as tk


class CustomDateEntry(DateEntry):
    """日期选择控件示例实现（当前主程序使用 ttkbootstrap.DateEntry）。

    注意：本模块以前在导入时就会创建 Tk 窗口并进入 mainloop，
    只要有人 import 就会弹窗并阻塞，现改为仅在直接运行时才演示。
    """

    def _select(self, event=None):
        date = self._calendar.selection_get()
        if date is not None:
            self._set_text(date.strftime('%m/%d/%Y'))
            self.event_generate('<<DateEntrySelected>>')
        top_cal = getattr(self, "_top_cal", None)
        if top_cal is not None:
            top_cal.withdraw()
        if 'readonly' not in self.state():
            self.focus_set()


if __name__ == "__main__":
    root = tk.Tk()
    entry = CustomDateEntry(root)
    entry._set_text(entry._date.strftime('%m/%d/%Y'))
    entry.pack()
    root.mainloop()
