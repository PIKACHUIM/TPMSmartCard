import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

root = tk.Tk()

# 设置主窗口宽度和高度
root.geometry("800x600")



# 创建树形视图
treeview = ttk.Treeview(root, columns=("Column 1", "Column 2"), show="headings", bootstyle='info')
treeview.pack(side=TOP, padx=0, pady=0)

# 设置列标题
treeview.heading("Column 1", text="ID")
treeview.heading("Column 2", text="Name")

# 设置列宽度
treeview.column("Column 1", width=30)
treeview.column("Column 2", width=500)

# 向树形视图中添加数据
data = [("00", "Item 1B"),
        ("01", "Item 2B"),
        ("02", "Item 3B")]

for item in data:
    treeview.insert("", tk.END, values=item)

card_add = ttk.Button(root, text="Add TPM Card", bootstyle=SUCCESS)
card_add.pack(side=BOTTOM, padx=5, pady=10)

card_get = ttk.Button(root, text="List Certs", bootstyle=INFO)
card_get.pack(side=BOTTOM, padx=5, pady=10)

card_del = ttk.Button(root, text="Delete Card", bootstyle=DANGER)
card_del.pack(side=BOTTOM, padx=5, pady=10)

edit_pin = ttk.Button(root, text="Change PIN", bootstyle=WARNING)
edit_pin.pack(side=BOTTOM, padx=5, pady=10)

next_pin = ttk.Button(root, text="Reset PIN", bootstyle=DARK)
next_pin.pack(side=BOTTOM, padx=5, pady=10)

root.mainloop()
