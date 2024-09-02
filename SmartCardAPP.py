import json
import os
import random
import pyglet
import pyperclip
import threading
import time
from ttkbootstrap import *
import ttkbootstrap as ttk
# import tkinter as tk
from functools import partial
from tkinter import messagebox, filedialog, font
from Module.SmartCardAPI import SmartCardAPI
from Module.TPMSmartCard import TPMSmartCard


class SmartCardAPP:
    def __init__(self):
        self.root = tk.Tk()
        self.conf = dict()
        self.read_config()
        self.lang = "cn"
        # 设置主窗口宽度和高度
        self.root.geometry("1080x540")
        self.size = self.get_screens()
        self.root.geometry(f"+{self.size[0]}+{self.size[1]}")
        self.root.title("TPM Smart Card Manager")
        self.data = SmartCardAPI()
        self.tpms = TPMSmartCard()
        pyglet.font.add_file("Config/myfont/MapleMono-SC-NF-Regular.ttf")
        pyglet.font.add_file("Config/myfont/NotoSerifCJKsc-Regular.otf")
        self.pick = {
            "card": "",
            "cert": ""
        }
        # FONT_NAME = "Noto Serif CJK SC"
        FONT_NAME = "MapleMono SC NF"
        self.t_fonts = {
            "label_data": font.Font(family=FONT_NAME,
                                    size=-12),
            "label_name": font.Font(family=FONT_NAME,
                                    size=-12, weight="bold")
        }
        self.frames = {
            "card_main": self.view_frames("card_main"),
            "card_info": self.view_frames("card_info"),
            "cert_main": self.view_frames("cert_main"),
            "cert_info": self.view_frames("cert_info"),
            "cert_user": self.view_frames("cert_user"),
            "cert_last": self.view_frames("cert_last"),
        }

        self.tables = {
            "card_main": self.view_tables("card_main"),
            "cert_main": self.view_tables("cert_main"),
        }
        if self.tables["card_main"][0] is not None:
            self.tables["card_main"][0].bind('<<TreeviewSelect>>', self.card_select)
        if self.tables["cert_main"][0] is not None:
            self.tables["cert_main"][0].bind('<<TreeviewSelect>>', self.cert_select)
        self.button = {
            "card_main": self.view_button("card_main"),
            "cert_main": self.view_button("cert_main"),
        }

        self.labels = {
            "card_info": self.view_labels("card_info"),
            "cert_info": self.view_labels("cert_info"),
            "cert_user": self.view_labels("cert_user"),
            "cert_last": self.view_labels("cert_last"),
        }

        self.button["card_main"]["pin"].config(state=tk.DISABLED)
        self.button["card_main"]["puk"].config(state=tk.DISABLED)
        self.button["card_main"]["del"].config(state=tk.DISABLED)

        self.button["cert_main"]["sys"].config(state=tk.DISABLED)
        self.button["cert_main"]["out"].config(state=tk.DISABLED)
        self.button["cert_main"]["non"].config(state=tk.DISABLED)

        self.load_status()
        self.root.mainloop()

    def la(self, in_name):
        if "global" not in self.conf:
            return in_name
        temp_data = self.conf["global"]
        if self.lang not in temp_data:
            return in_name
        temp_data = temp_data[self.lang]
        if in_name not in temp_data:
            return in_name
        return temp_data[in_name]

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
        for conf_name in ["tables", "frames", "button",
                          "labels", "global"]:
            with open("Config/%s.json" % conf_name, "r",
                      encoding="utf8") as conf_file:
                conf_data = conf_file.read()
                self.conf[conf_name] = json.loads(conf_data)

    def load_status(self):
        self.data.readInfo()
        self.button["card_main"]["del"].config(state=tk.DISABLED)
        self.button["cert_main"]["non"].config(state=tk.DISABLED)

        self.tables["card_main"][0].delete(*self.tables["card_main"][0].get_children())
        self.tables["cert_main"][0].delete(*self.tables["cert_main"][0].get_children())
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
                "add": (self.card_create, None),
                "del": (self.data_delete, "card"),
                "puk": (self.card_change, "puk"),
                "pin": (self.card_change, "pin"),
                "cer": (self.cert_import, None),
                "sys": (self.cert_system, None),
                "out": (self.cert_out_to, None),
                "non": (self.data_delete, "cert"),
            }
            # bt_fun = {}
            for now in bt_all:
                bt_fun = bt_map[now['name']] if now['name'] in bt_map else (None, None)
                if bt_fun[1] is None:
                    bta = ttk.Button(self.root, text=now['text'], bootstyle=now['type'],
                                     command=bt_fun[0])
                else:
                    bta = ttk.Button(self.root, text=now['text'], bootstyle=now['type'],
                                     command=partial(bt_fun[0], bt_fun[1]))
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
            tb_conf = tb_conf[in_name]
            tb_ln_x = tb_conf['conf'][0]
            tb_it_y = tb_conf['conf'][1]
            for tb_line in tb_conf['data']:
                tb_it_x = tb_ln_x
                for tb_item in tb_line:
                    tag = ttk.Label(bootstyle="default", text=self.la(tb_item) + ": "
                                    , font=self.t_fonts['label_name'])
                    tag.place(x=tb_it_x, y=tb_it_y)
                    inf = ttk.Label(bootstyle="default", text="", font=self.t_fonts['label_data'])
                    # inf.place(x=tb_it_x + tag.winfo_reqwidth() + 5, y=tb_it_y)
                    inf.place(x=tb_it_x + 60 + 5, y=tb_it_y)
                    tb_data[tb_item] = [tag, inf]
                    # tb_it_x += tag.winfo_reqwidth() + 5 + tb_line[tb_item]
                    tb_it_x += 60 + 5 + tb_line[tb_item]
                tb_it_y += 20
        return tb_data

    def card_select(self, event):
        treeview = event.widget
        selected_item = treeview.selection()
        if len(selected_item) > 0:
            selected_name = treeview.set(selected_item[0], '#2')
            self.pick["card"] = selected_name
            self.button["card_main"]["del"].config(state=tk.NORMAL)
            self.button["card_main"]["pin"].config(state=tk.NORMAL)
            self.button["card_main"]["puk"].config(state=tk.NORMAL)
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

    def cert_out_to(self, in_path=None):
        if self.pick["cert"] in self.data.certs:
            now_cert = self.data.certs[self.pick["cert"]]
            if now_cert.sc_cert is not None:
                if in_path is None:
                    save_path = filedialog.asksaveasfilename(
                        defaultextension=".crt",  # 默认文件扩展名
                        filetypes=[("Cert files", "*.crt"), ("All files", "*.*")],  # 文件类型过滤器
                        initialdir="~",  # 初始目录，对于Windows系统，你可能想要设置为os.path.expanduser('~')
                        initialfile="%s.crt" % str(now_cert.sc_cert.SerialNums),  # 初始文件名
                        title="Save as"  # 对话框标题
                    )
                else:
                    save_path = "%s\\%s.crt" % (in_path, str(now_cert.sc_cert.SerialNums))
                with open(save_path, "w") as save_file:
                    save_file.write(now_cert.sc_text)
                if in_path is None:
                    messagebox.showinfo("成功", "证书导出成功：%s\n"
                                                "注意：只能导出证书公钥数据，私钥存储在TPM上无法导出" % str(
                        now_cert.sc_cert.CommonName))
                return save_path
            else:
                messagebox.showerror("错误", "证书读取错误")
        else:
            messagebox.showerror("错误", "无法找到证书")
        return None

    def cert_system(self):
        save_path = self.cert_out_to(in_path=os.getenv('APPDATA'))
        if save_path is not None and os.path.exists(save_path):
            os.system("explorer %s" % save_path)

    def cert_select(self, event):
        treeview = event.widget
        selected_item = treeview.selection()
        for fill_name in self.labels["cert_info"]:
            self.labels["cert_info"][fill_name][1].config(text="")
        if len(selected_item) > 0:
            selected_name = treeview.set(selected_item[0], '#2')
            selected_uuid = treeview.set(selected_item[0], '#1')
            self.pick["cert"] = selected_name + " " + selected_uuid
            self.button["cert_main"]["non"].config(state=tk.NORMAL)
            self.button["cert_main"]["sys"].config(state=tk.NORMAL)
            self.button["cert_main"]["out"].config(state=tk.NORMAL)
            if self.pick["cert"] in self.data.certs:
                cert_now = self.data.certs[self.pick["cert"]]
                if cert_now.sc_cert is not None:
                    cert_now = cert_now.sc_cert
                    cert_map = {
                        "cert_name": cert_now.CommonName,
                        "cert_uuid": cert_now.SerialNums,
                        "cert_sign": cert_now.Algorithms,
                        "cert_open": cert_now.IssuedDate,
                        "cert_stop": cert_now.ExpireDate,
                        "is_ca_cert": cert_now.is_ca_cert,
                        "is_expired": cert_now.is_expired,
                        "pub_length": cert_now.pub_key_al + cert_now.pub_length,
                        "key_usages": str(cert_now.MainUsages)[:86] + "..." \
                            if len(str(cert_now.MainUsages)) >= 86 else cert_now.MainUsages,
                        "sub_usages": str(cert_now.SubsUsages)[:86] + "..." \
                            if len(str(cert_now.SubsUsages)) >= 86 else cert_now.SubsUsages,
                        "key_identy": cert_now.MainHashID,
                        "sub_identy": cert_now.SubsHashID,

                        "user_name": cert_now.OwnersInfo["CN"] if "CN" in cert_now.OwnersInfo else "",
                        "user_code": cert_now.OwnersInfo["C"] if "C" in cert_now.OwnersInfo else "",
                        "user_area": cert_now.OwnersInfo["``"] if "``" in cert_now.OwnersInfo else "",
                        "user_city": cert_now.OwnersInfo["``"] if "``" in cert_now.OwnersInfo else "",
                        "user_on_t": cert_now.OwnersInfo["O"] if "O" in cert_now.OwnersInfo else "",
                        "user_ou_t": cert_now.OwnersInfo["OU"] if "OU" in cert_now.OwnersInfo else "",

                        "last_name": cert_now.IssuerInfo["CN"] if "CN" in cert_now.IssuerInfo else "",
                        "last_code": cert_now.IssuerInfo["C"] if "C" in cert_now.IssuerInfo else "",
                        "last_area": cert_now.IssuerInfo["``"] if "``" in cert_now.IssuerInfo else "",
                        "last_city": cert_now.IssuerInfo["``"] if "``" in cert_now.IssuerInfo else "",
                        "last_on_t": cert_now.IssuerInfo["O"] if "O" in cert_now.IssuerInfo else "",
                        "last_ou_t": cert_now.IssuerInfo["OU"] if "OU" in cert_now.IssuerInfo else "",
                    }
                    for fill_name in cert_map:
                        for label in ["cert_info", "cert_user", "cert_last"]:
                            label_now = self.labels[label]
                            if fill_name in label_now:
                                label_now[fill_name][1].config(text=cert_map[fill_name])
            print(selected_name)

    def card_change(self, in_type="pin"):
        if not self.pick["card"] or self.pick["card"] not in self.data.cards:
            return None

        def submit():
            card_uid = self.pick["card"].split(" ")[-1]
            pass_key = pass_txt.get()
            pass_new = next_txt.get()
            same_new = same_txt.get()
            if pass_key == "" or len(pass_key) < 4:
                make.attributes('-topmost', False)
                messagebox.showwarning("错误", "原密码至少为4位")
                make.attributes('-topmost', True)
            elif pass_new == "" or len(pass_new) < 4:
                make.attributes('-topmost', False)
                messagebox.showwarning("错误", "新密码至少为4位")
                make.attributes('-topmost', True)
            elif pass_new != same_new:
                make.attributes('-topmost', False)
                messagebox.showwarning("错误", "两次输入的不匹配")
                make.attributes('-topmost', True)
            else:
                result = TPMSmartCard.changePIN(pass_key, pass_new, card_uid,
                                                type="--change-pin" \
                                                    if in_type == "pin" else "--unblock-pin")
                messagebox.showinfo("修改/重置密码结果", result)
                make.destroy()

        make = ttk.Toplevel(self.root)
        make.geometry("600x200")
        make.geometry(f"+{self.size[0]}+{self.size[1]}")
        make.title("%sPIN密码" % "修改" if in_type == "pin" else "重置PIN密码")
        pass_tag = ttk.Label(make, text="旧的 PIN: " if in_type == "pin" else "卡片 PUK: ",
                             bootstyle="info")
        pass_tag.grid(column=0, row=1, pady=10, padx=15)
        pass_txt = ttk.Entry(make, bootstyle="info", width=60, text="")
        pass_txt.grid(column=1, row=1, pady=10, padx=5)
        pass_tip = ttk.Label(make, text="❌✅", bootstyle="info")
        pass_tip.grid(column=2, row=1, pady=10, padx=5)

        next_pin = ttk.Label(make, text="新的 PIN: ", bootstyle="info")
        next_pin.grid(column=0, row=2, pady=10, padx=15)
        next_txt = ttk.Entry(make, bootstyle="info", width=60)
        next_txt.grid(column=1, row=2, pady=10, padx=5)
        next_tip = ttk.Label(make, text="❌✅", bootstyle="info")
        next_tip.grid(column=2, row=2, pady=10, padx=5)

        same_pin = ttk.Label(make, text="确认 PIN: ", bootstyle="info")
        same_pin.grid(column=0, row=3, pady=10, padx=15)
        same_txt = ttk.Entry(make, bootstyle="info", width=60)
        same_txt.grid(column=1, row=3, pady=10, padx=5)
        same_tip = ttk.Label(make, text="❌✅", bootstyle="info")
        same_tip.grid(column=2, row=3, pady=10, padx=5)

        cancel_button = ttk.Button(make, text="取消", command=make.destroy, bootstyle="danger")
        cancel_button.grid(column=0, row=4, pady=5, padx=15)
        submit_button = ttk.Button(make, text="确认", command=submit, bootstyle="info")
        submit_button.grid(column=2, row=4, pady=5, padx=0)

    def card_create(self):

        def disable():
            if puks_var.get():
                puks_txt.delete(0, tk.END)
                puks_txt.config(state=tk.DISABLED)
                make.attributes('-topmost', False)
                messagebox.showinfo("禁用PUK",
                                    ("注意：您禁用了PUK码，PIN码将是您唯一访问凭据，请妥善保管\n"
                                     "无法使用Admin Key恢复PIN，如果丢失PIN码将无法访问智能卡!\n"))
                make.attributes('-topmost', True)
            else:
                puks_txt.config(state=tk.NORMAL)
                puks_txt.delete(0, tk.END)
                for i in range(0, 16):
                    puks_txt.insert(0, str(random.randint(0, 9)))

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
        make.attributes('-topmost', True)
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
        puks_tip = ttk.Checkbutton(make, text="禁用 PUK", bootstyle="info-round-toggle",
                                   variable=puks_var, command=disable)
        puks_tip.grid(column=2, row=2, pady=10, padx=5)
        for i in range(0, 16):
            puks_txt.insert(0, str(random.randint(0, 9)))

        adks_tag = ttk.Label(make, text="管理密码: ", bootstyle="info")
        adks_tag.grid(column=0, row=3, pady=10, padx=15)
        adks_txt = ttk.Entry(make, bootstyle="info", width=60)
        adks_txt.grid(column=1, row=3, pady=10, padx=5)
        adks_var = tk.BooleanVar()
        adks_tip = ttk.Checkbutton(make, text="随机生成", bootstyle="info-round-toggle",
                                   variable=adks_var, command=randoms)
        for i in range(0, 48):
            adks_txt.insert(0, str(random.randint(0, 9)))
        adks_txt.config(state=tk.DISABLED)
        adks_tip.grid(column=2, row=3, pady=10, padx=5)
        adks_var.set(True)

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
                    pin = pins_txt.get()
                    puk = puks_txt.get()
                    adk = adks_txt.get()
                    out = "用户 PIN: %s\n用户 PUK: %s\n管理密码: %s" % (
                        pin, puk, adk
                    )
                    # cid = result.find("ROOT")
                    # if cid >= 0:
                    #     out = result[cid:cid + 25] + "\n" + out
                    if deals_destroy:
                        make.destroy()
                        messagebox.showinfo("创建结果", result)
                        pyperclip.copy(out)
                        messagebox.showinfo("卡片信息", out + "\n卡片信息已经复制到剪贴板，请妥善保存")

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

    def data_delete(self, in_name="card"):
        data = self.data.cards if in_name == "card" else self.data.certs
        if self.pick[in_name] in data:
            make = ttk.Toplevel(self.root)
            make.geometry("240x200")
            make.geometry(f"+{self.size[0]}+{self.size[1]}")
            make.title("删除%s" % in_name)

            def submit():
                if in_name == "card":
                    result = TPMSmartCard.dropCards(self.data.cards[self.pick[in_name]].sc_path)
                elif in_name == "cert":
                    result = TPMSmartCard.dropCerts(self.pick["cert"])
                self.deselectAll()
                self.load_status()
                make.destroy()
                if len(result) > 0:
                    if in_name == "cert":
                        result += ("\n注意：证书删除后，系统不会立即刷新证书状态"
                                   "\n您需要重启系统来刷新状态(密钥已经立即删除)")
                    messagebox.showinfo("删除结果", result)

            def checks():
                if kill_var.get():
                    submit_b.config(state=tk.NORMAL)
                else:
                    submit_b.config(state=tk.DISABLED)

            kill_tag = ttk.Label(make,
                                 text="您确认要删除%s: \n\n%s ?" % (
                                     in_name,
                                     self.pick[in_name],
                                 ))
            kill_tag.place(x=20, y=10)

            kill_tip = ttk.Label(make, bootstyle="danger",
                                 text="您可能会无法解密文件或丢失访问权限\n"
                                      "危险：此操作不可逆！且无法恢复数据")
            kill_tip.place(x=20, y=80)
            kill_var = tk.BooleanVar()
            kill_yes = ttk.Checkbutton(make, text=" 我已确认待删除的%s并知晓后果" % in_name,
                                       bootstyle="dark", command=checks, variable=kill_var)
            kill_yes.state(['!alternate'])
            kill_yes.place(x=20, y=120)

            cancel_b = ttk.Button(make, text="取消", command=make.destroy, bootstyle="success")
            cancel_b.place(x=20, y=150)
            submit_b = ttk.Button(make, text="删除", command=submit, bootstyle="danger")
            submit_b.place(x=180, y=150)
            submit_b.config(state=tk.DISABLED)

    def cert_import(self):
        make = ttk.Toplevel(self.root)
        make.geometry("620x160")
        make.geometry(f"+{self.size[0]}+{self.size[1]}")
        make.title("导入证书")

        def search():
            file_path = filedialog.askopenfilename(
                filetypes=[("PFX Files", "*.pfx;*.p12")]
            )
            if file_path:
                print(f"选定的文件路径：{file_path}")
                path_txt.delete(0, tk.END)
                path_txt.insert(0, file_path)
                make.attributes('-topmost', True)

        def submit():
            if not os.path.exists(path_txt.get()):
                messagebox.showwarning("错误", "文件不存在")
            else:
                make.attributes('-topmost', False)
                result = TPMSmartCard.initCerts(path_txt.get(),
                                                pass_txt.get())
                self.load_status()
                make.destroy()
                messagebox.showinfo("导入证书结果",
                                    result + "\n注意：证书导入后，私钥无法再通过任何方式从TPM导出或者备份"
                                             "\n如需备份，请保留原始的PFX文件以及密码，否则可能会丢失数据")

        # 在新窗口中添加输入部件
        path_tag = ttk.Label(make, text="证书路径: ", bootstyle="info")
        path_tag.grid(column=0, row=0, pady=10, padx=15)
        path_txt = ttk.Entry(make, bootstyle="info", width=60)
        path_txt.grid(column=1, row=0, pady=10, padx=5)
        path_tip = ttk.Button(make, text="打开文件", bootstyle="info",
                              command=search)
        path_tip.grid(column=2, row=0, pady=10, padx=5)

        pass_tag = ttk.Label(make, text="证书密码: ", bootstyle="info")
        pass_tag.grid(column=0, row=1, pady=10, padx=15)
        pass_txt = ttk.Entry(make, bootstyle="info", width=60, text="")
        pass_txt.grid(column=1, row=1, pady=10, padx=5)
        pass_tip = ttk.Label(make, text="(0~63个字符)", bootstyle="info")
        pass_tip.grid(column=2, row=1, pady=10, padx=5)

        cancel_button = ttk.Button(make, text="取 消", command=make.destroy, bootstyle="danger")
        cancel_button.grid(column=0, row=2, pady=5, padx=15)
        submit_button = ttk.Button(make, text="导入 PFX", command=submit, bootstyle="success")
        submit_button.grid(column=2, row=2, pady=5, padx=0)

        deals_process = ttk.Progressbar(make, length=432)
        deals_process.grid(column=1, row=2, pady=10, padx=5, sticky=tk.W)
        deals_process['value'] = 0


if __name__ == "__main__":
    # os.system('cd /d "%~dp0"')
    print(os.getcwd())
    app = SmartCardAPP()
