import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *


class SmartCardAPP:
    def __init__(self):
        self.root = tk.Tk()

        # 设置主窗口宽度和高度
        self.root.geometry("1020x530")
        self.root.title("皮卡虚拟智能卡")
        # info colored frame style
        self.card_main_tag = ttk.LabelFrame(bootstyle="info", width=380, height=500, text="Card")
        self.card_main_tag.place(x=20, y=10)

        self.cert_main_tag = ttk.LabelFrame(bootstyle="info", width=590, height=500, text="Card")
        self.cert_main_tag.place(x=410, y=10)

        self.card_tree_inf = ttk.Treeview(self.root,
                                          columns=("ITEM", "NAME", "UUID"),
                                          show="headings", bootstyle='info')
        self.card_tree_bar = ttk.Scrollbar(self.root, bootstyle='info',
                                           orient='vertical',
                                           command=self.card_tree_inf.yview)
        self.card_tree_inf.configure(yscrollcommand=self.card_tree_bar.set)
        self.card_tree_inf.place(x=33, y=30, width=355)
        self.card_tree_bar.place(x=373, y=63, height=158)

        # 设置列标题w
        self.card_tree_inf.heading("ITEM", text="#", )
        self.card_tree_inf.heading("NAME", text="Card Name")
        self.card_tree_inf.heading("UUID", text="Card ID")
        # 设置列宽度
        self.card_tree_inf.column("ITEM", width=50, anchor='center')
        self.card_tree_inf.column("NAME", width=190, anchor='center')
        self.card_tree_inf.column("UUID", width=90, anchor='center')

        # 向树形视图中添加数据
        self.data = [("%04d" % i, 'Microsoft Virtual Smart Card 0', '02580012') for i in range(0, 20)]

        for item in self.data:
            self.card_tree_inf.insert("", tk.END, values=item)
        self.card_add = ttk.Button(self.root, text="➕ Add", bootstyle=SUCCESS)
        self.card_add.place(x=33, y=230, )
        self.edit_pin = ttk.Button(self.root, text="↩ Change PIN", bootstyle=INFO)
        self.edit_pin.place(x=100, y=230, )
        self.next_pin = ttk.Button(self.root, text="🔄 Reset PIN", bootstyle=WARNING)
        self.next_pin.place(x=210, y=230, )
        self.card_del = ttk.Button(self.root, text="❌ Delete", bootstyle=DANGER)
        self.card_del.place(x=308, y=230, )

        # 卡片信息 ======
        self.card_info_tag = ttk.LabelFrame(bootstyle="info", width=355, height=200, text="Card Info")
        self.card_info_tag.place(x=33, y=260)

        self.card_name_tag = ttk.Label(bootstyle="info",text="Card Name: ")
        self.card_name_tag.place(x=43, y=275)

        self.card_uuid_tag = ttk.Label(bootstyle="info", text="Card UUID: ")
        self.card_uuid_tag.place(x=250, y=275)

        self.card_open_tag = ttk.Label(bootstyle="info", text="Card Name: ")
        self.card_open_tag.place(x=43, y=295)

        self.card_stop_tag = ttk.Label(bootstyle="info", text="Card UUID: ")
        self.card_stop_tag.place(x=250, y=295)


        self.root.mainloop()


if __name__ == "__main__":
    app = SmartCardAPP()
