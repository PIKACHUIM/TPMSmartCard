import json
import multiprocessing
import random
import threading
import time
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk as ttk_old
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from Module.SmartCardAPI import SmartCardAPI
from Module.TPMSmartCard import TPMSmartCard


class SmartCardAPP:
    def __init__(self):
        self.root = tk.Tk()
        self.conf = dict()
        self.read_config()
        # 设置主窗口宽度和高度
        self.root.geometry("1020x530")
        self.size = self.get_screens()
        self.root.geometry(f"+{self.size[0]}+{self.size[1]}")
        self.root.title("皮卡虚拟智能卡")
        self.data = SmartCardAPI()
        self.tpms = TPMSmartCard()
        self.pick = {
            "card": ""
        }

        self.frames = {
            "card_main": self.view_frames("card_main"),
            "card_info": self.view_frames("card_info"),
            "cert_main": self.view_frames("cert_main"),
        }

        self.tables = {
            "card_main": self.view_tables("card_main"),
            "cert_main": self.view_tables("cert_main"),
        }
        if self.tables["card_main"][0] is not None:
            self.tables["card_main"][0].bind('<<TreeviewSelect>>', self.card_select)

        self.button = {
            "card_main": self.view_button("card_main"),
            "cert_main": self.view_button("cert_main"),
        }
        self.button["card_main"]["del"].config(state=tk.DISABLED)
        self.labels = {
            "card_info": self.view_labels("card_info"),
        }
        self.button["card_main"]["pin"].config(state=tk.DISABLED)
        self.button["card_main"]["puk"].config(state=tk.DISABLED)
        self.load_status()
        self.root.mainloop()

    def get_screens(self):
        # 获取窗口的宽度和高度
        window_width = self.root.winfo_reqwidth()
        window_height = self.root.winfo_reqheight()

        # 获取屏幕的宽度和高度
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        # 计算窗口的新位置，使其位于屏幕中央
        x = (screen_width // 2) - (window_width // 2)
        y = (screen_height // 2) - (window_height // 2)
        return x, y

    def read_config(self):
        for conf_name in ["tables", "frames", "button", "labels"]:
            with open("Config/%s.json" % conf_name, "r",
                      encoding="utf8") as conf_file:
                conf_data = conf_file.read()
                self.conf[conf_name] = json.loads(conf_data)

    def load_status(self):
        self.data.readInfo()
        self.tables["card_main"][0].delete(*self.tables["card_main"][0].get_children())
        for card_now in self.data.cards:
            if "card_main" in self.tables:
                self.tables["card_main"][0].insert("", tk.END, values=(
                                 self.data.cards[card_now].card_id,
                                 card_now,
                                 self.data.cards[card_now].sc_uuid[:16]))
        for cert_now in self.data.certs:
            if "cert_main" in self.tables:
                self.tables["cert_main"][0].insert("", tk.END, values=(
                    cert_now.split(' ')[-1],
                    " ".join(cert_now.split(' ')[:-1]),
                    self.data.certs[cert_now].sc_exec,
                    self.data.certs[cert_now].sc_keys
                ))

    # 添加框架控件 ============================================================
    def view_frames(self, in_name):
        tb_conf = self.conf['frames']
        if in_name in tb_conf:
            tag = ttk.LabelFrame(bootstyle="info",
                                 width=tb_conf[in_name][0],
                                 height=tb_conf[in_name][1],
                                 text=in_name)
            tag.place(x=tb_conf[in_name][2], y=tb_conf[in_name][3])
            return tag
        return None

    # 添加表格控件 ============================================================
    #                     表格名称 表格的样式风格
    def view_tables(self, in_name, t_style='info'):
        tb_conf = self.conf['tables']
        if in_name in tb_conf:
            # 处理基本信息 ====================================================
            tb_pack = tb_conf[in_name]['pack']
            tb_data = tb_conf[in_name]['data']
            tb_name = list(i for i in tb_data)
            tb_lens = sum([tb_data[i][0] for i in tb_data])
            # 添加表格组件 ====================================================
            inf = ttk.Treeview(self.root,
                               bootstyle=t_style,
                               show="headings",
                               columns=tb_name)
            bar = ttk.Scrollbar(self.root,
                                bootstyle=t_style,
                                orient='vertical',
                                command=inf.yview)
            inf.configure(yscrollcommand=bar.set)
            # 设置表格组件 ====================================================
            inf.place(x=tb_pack[0], y=tb_pack[1], width=tb_lens + 25)
            bar.place(x=tb_pack[0] + tb_lens + 10,
                      y=tb_pack[1] + 33, height=tb_pack[2])
            # 设置表列信息 ====================================================
            for th_name in tb_data:
                inf.heading(th_name, text=tb_data[th_name][1])  # 设置列的标题
                inf.column(th_name, anchor='center', width=tb_data[th_name][0])
            return inf, bar
        return None, None

    # 添加框架控件 ============================================================
    def view_button(self, in_name):
        tb_conf = self.conf['button']
        if in_name in tb_conf:
            bt_dict = dict()
            # 处理基本信息 ====================================================
            bt_cfg = tb_conf[in_name][0]
            bt_btx = bt_cfg[0]
            bt_bty = bt_cfg[1]
            bt_all = tb_conf[in_name][1:]
            bt_map = {
                "add": self.card_create,
                "del": self.card_delete,
            }
            for now in bt_all:
                bta = ttk.Button(self.root, text=now['text'],
                                 bootstyle=now['type'],
                                 command=bt_map[now['name']] \
                                     if now['name'] in bt_map else None)
                bta.place(x=bt_btx, y=bt_bty, width=now['w'])
                bt_btx = bt_btx + now['w'] + 2
                bt_dict[now['name']] = bta
            return bt_dict
        return None

    def view_labels(self, in_name):
        # 卡片信息 ======
        tb_conf = self.conf['labels']
        tb_data = dict()
        if in_name in tb_conf:
            for now in tb_conf[in_name]:
                tag = ttk.Label(bootstyle="info", text=now[0] + ": ")
                tag.place(x=now[1], y=now[2])
                inf = ttk.Label(bootstyle="info", text="")
                inf.place(x=now[1] + (len(now[0]) + 2) * 6, y=now[2])
                tb_data[now[0]] = [tag, inf]
        return tb_data

    def card_select(self, event):
        treeview = event.widget
        selected_item = treeview.selection()
        if len(selected_item) > 0:
            selected_name = treeview.set(selected_item[0], '#2')
            self.pick["card"] = selected_name
            self.button["card_main"]["del"].config(state=tk.NORMAL)
            if selected_name in self.data.cards:
                card_now = self.data.cards[selected_name]
                card_map = {
                    "card_name": selected_name,
                    "card_uuid": card_now.sc_uuid,
                    "card_path": card_now.sc_path,
                    "sc_status": card_now.sc_sha1,
                    "sc_length": card_now.sc_sha2
                }
                for fill_name in card_map:
                    if fill_name in self.labels["card_info"]:
                        self.labels["card_info"][fill_name][1].config(text=card_map[fill_name])
            print(selected_name)

    def card_create(self):

        def disable():
            if puks_var.get():
                puks_txt.delete(0, tk.END)
                puks_txt.config(state=tk.DISABLED)
            else:
                puks_txt.config(state=tk.NORMAL)

        def randoms():
            if adks_var.get():
                adks_txt.delete(0, tk.END)
                for i in range(0, 48):
                    adks_txt.insert(0, str(random.randint(0, 9)))
                adks_txt.config(state=tk.DISABLED)
            else:
                adks_txt.config(state=tk.NORMAL)

        make = ttk.Toplevel(self.root)
        make.geometry("640x240")
        make.geometry(f"+{self.size[0]}+{self.size[1]}")
        make.title("创建新的TPM虚拟智能卡")

        # 在新窗口中添加输入部件
        name_tag = ttk.Label(make, text="卡片名称: ", bootstyle="info")
        name_tag.grid(column=0, row=0, pady=10, padx=15)
        name_txt = ttk.Entry(make, bootstyle="info", width=60)
        name_txt.insert(0, "Personal TPM Virtual Smart Card")
        name_txt.grid(column=1, row=0, pady=10, padx=5)
        name_tip = ttk.Label(make, text="(1~63个字符)", bootstyle="info")
        name_tip.grid(column=2, row=0, pady=10, padx=5)
        pins_tag = ttk.Label(make, text="卡片 PIN: ", bootstyle="info")
        pins_tag.grid(column=0, row=1, pady=10, padx=15)
        pins_txt = ttk.Entry(make, bootstyle="info", width=60, text="")
        for i in range(0, 8):
            pins_txt.insert(0, str(random.randint(0, 9)))
        pins_txt.grid(column=1, row=1, pady=10, padx=5)
        pins_tip = ttk.Label(make, text="(4~15个字符)", bootstyle="info")
        pins_tip.grid(column=2, row=1, pady=10, padx=5)

        puks_tag = ttk.Label(make, text="卡片 PUK: ", bootstyle="info")
        puks_tag.grid(column=0, row=2, pady=10, padx=15)
        puks_txt = ttk.Entry(make, bootstyle="info", width=60)
        puks_txt.grid(column=1, row=2, pady=10, padx=5)
        puks_var = tk.BooleanVar()
        puks_txt.config(state=tk.DISABLED)
        puks_var.set(True)
        puks_tip = ttk.Checkbutton(make, text="禁用此项", bootstyle="info-round-toggle",
                                   variable=puks_var, command=disable)
        puks_tip.grid(column=2, row=2, pady=10, padx=5)

        adks_tag = ttk.Label(make, text="管理密码: ", bootstyle="info")
        adks_tag.grid(column=0, row=3, pady=10, padx=15)
        adks_txt = ttk.Entry(make, bootstyle="info", width=60)
        adks_txt.grid(column=1, row=3, pady=10, padx=5)
        adks_var = tk.BooleanVar()
        adks_tip = ttk.Checkbutton(make, text="随机生成", bootstyle="info-round-toggle",
                                   variable=adks_var, command=randoms)
        adks_tip.grid(column=2, row=3, pady=10, padx=5)

        for i in range(0, 48):
            adks_txt.insert(0, str(random.randint(0, 9)))

        def submit():
            if name_txt.get() == "":
                make.attributes('-topmost', True)
                messagebox.showwarning("错误", "卡片的名称不能为空")
            elif not 4 <= len(pins_txt.get()) <= 15:
                make.attributes('-topmost', True)
                messagebox.showwarning("错误", "卡片PIN 长度不正确")
            elif len(puks_txt.get()) > 0 and not 8 <= len(puks_txt.get()) <= 16:
                make.attributes('-topmost', True)
                messagebox.showwarning("错误", "卡片PUK 需为8~16位")
            elif len(adks_txt.get()) != 48:
                make.attributes('-topmost', True)
                messagebox.showwarning("错误", "管理密码必须为48位")
            else:
                deals_process['value'] = 0
                global deals_destroy
                deals_destroy = False

                def create():
                    global deals_destroy
                    result = TPMSmartCard.makeCards(
                        pins_txt.get(),
                        puks_txt.get(),
                        adks_txt.get(),
                        name_txt.get()
                    )
                    deals_process['value'] = 95
                    result = result.split("\n")[-12:]
                    result = "\n".join(result)
                    deals_process['value'] = 100
                    self.load_status()
                    deals_destroy = True
                    if deals_destroy:
                        make.destroy()
                        messagebox.showinfo("创建TPM卡片结果", result)

                def update():
                    global deals_destroy
                    count = 100
                    while count > 0 and not deals_destroy:
                        deals_process['value'] += 0.9
                        time.sleep(0.15)
                        count -= 1

                cancel_button.config(state=tk.DISABLED)
                submit_button.config(state=tk.DISABLED)
                process = threading.Thread(target=create)
                process.start()
                updates = threading.Thread(target=update)
                updates.start()

        def cancel():
            make.destroy()

        cancel_button = ttk.Button(make, text="取消创建", command=cancel, bootstyle="danger")
        cancel_button.grid(column=0, row=4, pady=5, padx=15)
        submit_button = ttk.Button(make, text="创建卡片", command=submit, bootstyle="info")
        submit_button.grid(column=2, row=4, pady=5, padx=0)
        deals_process = ttk.Progressbar(make, length=432)
        deals_process.grid(column=1, row=4, pady=10, padx=5, sticky=tk.W)
        deals_process['value'] = 0

    def deselectAll(self):
        for item in self.tables["card_main"][0].selection():
            self.tables["card_main"][0].selection_remove(item)
        for item in self.labels["card_info"]:
            self.labels["card_info"][item][1].config(text="")

    def card_delete(self):
        make = ttk.Toplevel(self.root)
        if self.pick["card"] in self.data.cards:
            make.geometry("240x200")
            make.geometry(f"+{self.size[0]}+{self.size[1]}")
            make.title("删除TPM虚拟智能卡")

            def submit():
                result = TPMSmartCard.dropCards(self.data.cards[self.pick["card"]].sc_path)
                self.deselectAll()
                self.load_status()
                make.destroy()
                messagebox.showinfo("删除TPM卡片结果", result)

            def checks():
                if kill_var.get():
                    submit_b.config(state=tk.NORMAL)
                else:
                    submit_b.config(state=tk.DISABLED)

            kill_tag = ttk.Label(make,
                                 text="您确认要删除智能卡: \n\n%s ?" % self.pick["card"])
            kill_tag.place(x=20, y=10)

            kill_tip = ttk.Label(make, bootstyle="danger",
                                 text="您可能会无法解密文件或丢失访问权限\n"
                                      "危险：此操作不可逆！且无法恢复数据")
            kill_tip.place(x=20, y=80)
            kill_var = tk.BooleanVar()
            kill_yes = ttk.Checkbutton(make, text=" 我已确认待删除的卡片并知晓后果",
                                       bootstyle="dark", command=checks, variable=kill_var)
            kill_yes.state(['!alternate'])
            kill_yes.place(x=20, y=120)

            cancel_b = ttk.Button(make, text="取消", command=make.destroy, bootstyle="success")
            cancel_b.place(x=20, y=150)
            submit_b = ttk.Button(make, text="删除", command=submit, bootstyle="danger")
            submit_b.place(x=180, y=150)
            submit_b.config(state=tk.DISABLED)


if __name__ == "__main__":
    app = SmartCardAPP()
