import hashlib
import os
import json
import re
import sys
import time
import random
import tkinter
from random import randint

import base64
import pyglet
import locale
import platform
import subprocess
import webbrowser
import pyperclip
import threading

import requests
from cryptography.hazmat.primitives import serialization
from flask import request
from ttkbootstrap import *
import ttkbootstrap as ttk
from functools import partial
from tkinter import messagebox, filedialog, font
from Module.SmartCardAPI import SmartCardAPI
from Module.TPMSmartCard import TPMSmartCard
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from SubApp.CertImport import CertImport
from SubApp.MoreConfig import MoreConfig


class SmartCardAPP:
    def __init__(self):
        self.root = tk.Tk()
        self.conf = dict()
        self.read_config()
        # 获取当前系统的默认语言
        default_locale, _ = locale.getlocale()
        # 检查是否是中文环境
        if 'Chinese' in default_locale:
            self.lang = "zh"
        else:
            self.lang = "en"
        # self.lang = "en"
        # 设置主窗口宽度和高度
        self.root.geometry("1080x540")
        self.root.iconbitmap("Config/iconer/icon02.ico")
        self.size = self.get_screens()
        self.root.geometry(f"+{self.size[0]}+{self.size[1]}")
        self.root.title(self.la("main_text"))
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
        style_head = ttk.Style()
        style_head.configure("Treeview.Heading", font=self.t_fonts['label_name'])
        style_head.configure("Treeview", font=self.t_fonts['label_data'])
        # style_head.configure("TButton", font=self.t_fonts['label_name'])
        style_head.configure("TLabel", font=self.t_fonts['label_name'])
        style_head.configure("TCheckbutton", font=self.t_fonts['label_name'])
        style_head.configure("TCheckbutton", font=self.t_fonts['label_name'])

        self.frames = {
            "card_main": self.view_frames("card_main"),
            "card_info": self.view_frames("card_info"),
            "cert_main": self.view_frames("cert_main"),
            "cert_info": self.view_frames("cert_info"),
            "cert_user": self.view_frames("cert_user"),
            "cert_last": self.view_frames("cert_last"),
            "main_main": self.view_frames("main_main"),
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
            "main_main": self.view_button("main_main"),
            "main_line": self.view_button("main_line"),
            "card_opts": self.view_button("card_opts"),
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

        self.button["main_line"]["set"].config(state=tk.DISABLED)
        self.check_datas()
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
        if type(temp_data[in_name]) is list:
            return "".join(temp_data[in_name])
        return temp_data[in_name]

    def check_datas(self):
        opensc_path_x64 = r"C:\Program Files\OpenSC Project\OpenSC"
        opensc_path_x86 = r"C:\Program Files (x86)\OpenSC Project\OpenSC"
        if not os.path.exists(opensc_path_x64) and not os.path.exists(opensc_path_x86):
            if messagebox.askquestion(self.la("sc_title"), self.la("sc_datas")) == 'yes':
                self.install_osc()
                os.startfile(sys.executable)
                exit(0)

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
                          "labels", "global", "cncode"]:
            with open("Config/%s.json" % conf_name, "r",
                      encoding="utf8") as conf_file:
                conf_data = conf_file.read()
                self.conf[conf_name] = json.loads(conf_data)

    def load_status(self):
        self.data.readInfo()
        self.button["card_main"]["del"].config(state=tk.DISABLED)
        self.button["cert_main"]["non"].config(state=tk.DISABLED)
        self.button["card_main"]["pin"].config(state=tk.DISABLED)
        self.button["card_main"]["puk"].config(state=tk.DISABLED)
        self.button["cert_main"]["sys"].config(state=tk.DISABLED)
        self.button["cert_main"]["out"].config(state=tk.DISABLED)
        self.button["card_opts"]["bak"].config(state=tk.DISABLED)
        self.button["card_opts"]["rec"].config(state=tk.DISABLED)
        self.tables["card_main"][0].delete(*self.tables["card_main"][0].get_children())
        self.tables["cert_main"][0].delete(*self.tables["cert_main"][0].get_children())
        for item_name in ["card_info", "cert_info", "cert_user", "cert_last"]:
            for fill_name in self.labels[item_name]:
                self.labels[item_name][fill_name][1].config(text="")
        for card_now in self.data.cards:
            if "card_main" in self.tables:
                self.tables["card_main"][0].insert("", tk.END, values=(
                    self.data.cards[card_now].card_id,
                    card_now,
                    self.data.cards[card_now].sc_uuid[:16]))

        for cert_now in self.data.certs:
            if "cert_main" in self.tables:
                if len(cert_now.split(' ')) > 1:
                    cert_name = " ".join(cert_now.split(' ')[:-1])
                elif self.data.certs[cert_now].sc_cert is not None:
                    cert_name = self.data.certs[cert_now].sc_cert.OwnersInfo['CN']
                else:
                    cert_name = self.la("msg_no_cert")
                self.tables["cert_main"][0].insert("", tk.END, values=(
                    cert_now.split(' ')[-1],
                    cert_name,
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
                                 text=self.la(in_name))
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
                               columns=tb_name,
                               )
            bar = ttk.Scrollbar(self.root,
                                bootstyle=t_style,
                                orient='vertical',
                                command=inf.yview)
            inf.configure(yscrollcommand=bar.set)
            # 设置表格组件 ====================================================
            inf.place(x=tb_pack[0], y=tb_pack[1], width=tb_lens + 25)
            bar.place(x=tb_pack[0] + tb_lens + 13,
                      y=tb_pack[1] + 29, height=tb_pack[2])
            # 设置表列信息 ====================================================
            for th_name in tb_data:
                inf.heading(th_name, text=self.la(tb_data[th_name][1]))  # 标题
                inf.column(th_name, anchor='w', width=tb_data[th_name][0])
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
                "cer": (self.cert_import, "pfx"),
                "csr": (self.reqs_create, None),
                "pem": (self.cert_import, "cer"),
                "sys": (self.cert_system, None),
                "out": (self.cert_out_to, None),
                "non": (self.data_delete, "cert"),

                "inf": (self.about_pages, None),
                "osc": (self.install_osc, None),
                "git": (self.open_github, None),
                "ing": (self.load_status, None),
                "tpm": (self.check_tpm_h, None),
                "set": (None, None),
                "ssh": (MoreConfig.setupSSH, None),
                "key": (MoreConfig.startSSH, None),
            }
            # bt_fun = {}
            for now in bt_all:
                bt_fun = bt_map[now['name']] if now['name'] in bt_map else (None, None)
                if bt_fun[1] is None:
                    bta = ttk.Button(self.root, text=self.la(now['text']),
                                     bootstyle=now['type'], command=bt_fun[0])
                else:
                    bta = ttk.Button(self.root, text=self.la(now['text']),
                                     bootstyle=now['type'], command=partial(bt_fun[0], bt_fun[1]))
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
        la_path = in_path
        if self.pick["cert"] in self.data.certs:
            now_cert = self.data.certs[self.pick["cert"]]
            if now_cert.sc_cert is not None:
                if in_path is None:
                    in_path = filedialog.asksaveasfilename(
                        defaultextension=".crt",  # 默认文件扩展名
                        filetypes=[("Cert files", "*.crt"), ("All files", "*.*")],  # 文件类型过滤器
                        initialdir="~",  # 初始目录，对于Windows系统，你可能想要设置为os.path.expanduser('~')
                        initialfile="%s.crt" % str(now_cert.sc_cert.SerialNums),  # 初始文件名
                        title="Save as"  # 对话框标题
                    )
                else:
                    in_path = "%s\\%s.crt" % (in_path, str(now_cert.sc_cert.SerialNums))
                if in_path is None or len(in_path) <= 0:
                    messagebox.showwarning(self.la("msg_cert_out_ft_item"), self.la("msg_cert_out_ft_path"))
                else:
                    with open(in_path, "w") as save_file:
                        save_file.write(now_cert.sc_text)
                    if la_path is None:
                        messagebox.showinfo(
                            self.la("msg_cert_out_ok_item"),
                            self.la("msg_cert_out_ok_text") % str(now_cert.sc_cert.CommonName)
                        )
                    return in_path
            else:
                messagebox.showerror(self.la("msg_cert_out_ft_item"), self.la("msg_cert_out_ft_text"))
        else:
            messagebox.showerror(self.la("msg_cert_out_ft_item"), self.la("msg_cert_out_ft_none"))
        return None

    def cert_system(self):
        save_path = self.cert_out_to(in_path=os.getenv('APPDATA'))
        if save_path is not None and os.path.exists(save_path):
            os.system("explorer %s" % save_path)

    def cert_select(self, event):
        treeview = event.widget
        selected_item = treeview.selection()
        for item_name in ["cert_info", "cert_user", "cert_last"]:
            for fill_name in self.labels[item_name]:
                self.labels[item_name][fill_name][1].config(text="")
        if len(selected_item) > 0:
            selected_name = treeview.set(selected_item[0], '#2')
            selected_uuid = treeview.set(selected_item[0], '#1')
            selected_name = selected_name.replace(self.la("msg_no_cert"), "")
            if selected_name != "":
                self.pick["cert"] = selected_name + " " + selected_uuid
            else:
                self.pick["cert"] = selected_uuid
            # 模糊匹配 =================================================================================
            if self.pick["cert"] not in self.data.certs:
                for now_line in self.data.certs:
                    now_uuid = now_line.split(" ")[-1]
                    if now_uuid == selected_uuid:
                        self.pick["cert"] = now_line
                        break
            self.button["cert_main"]["non"].config(state=tk.NORMAL)
            # 精确查找证书 =============================================================================
            if self.pick["cert"] in self.data.certs:
                cert_now = self.data.certs[self.pick["cert"]]
                if cert_now.sc_cert is not None:
                    self.button["cert_main"]["sys"].config(state=tk.NORMAL)
                    self.button["cert_main"]["out"].config(state=tk.NORMAL)
                    cert_now = cert_now.sc_cert
                    Algorithms = str(cert_now.Algorithms).split("With")[0]
                    user_name = cert_now.OwnersInfo["CN"] if "CN" in cert_now.OwnersInfo else "(Empty)"
                    user_name = user_name[:35] + ".." if len(user_name) > 35 else user_name
                    last_name = cert_now.IssuerInfo["CN"] if "CN" in cert_now.IssuerInfo else "(Empty)"
                    last_name = last_name[:35] + ".." if len(last_name) > 35 else last_name
                    cer_policy = "(Empty)"
                    if 'certificatePolicies' in cert_now.CertExtend:
                        cer_policy = ""
                        tmp_counts = 0
                        tmp_policy = str(cert_now.CertExtend['certificatePolicies']).split("\n")
                        for i in tmp_policy:
                            if i.find("Policy: ") >= 0:
                                if tmp_counts > 0:
                                    cer_policy += ","
                                cer_policy += i.replace("Policy: ", "")
                                tmp_counts += 1
                        if len(cer_policy) > 36:
                            cer_policy = cer_policy[:36] + "..."
                    cert_map = {
                        "cert_name": cert_now.CommonName,
                        "cert_uuid": cert_now.SerialNums,
                        "cert_sign": cert_now.pub_key_al + cert_now.pub_length,
                        "cert_type": Algorithms.upper(),
                        "cert_open": cert_now.IssuedDate,
                        "cert_stop": cert_now.ExpireDate,
                        "cert_sha1": "HEX " + str(cert_now.CertSHA160).replace(":", ""),
                        "is_ca_cert": cert_now.is_ca_cert,
                        "is_expired": cert_now.is_expired,

                        "key_usages": str(cert_now.MainUsages)[:86] + "..." \
                            if len(str(cert_now.MainUsages)) >= 86 else cert_now.MainUsages,
                        "sub_usages": str(cert_now.SubsUsages)[:86] + "..." \
                            if len(str(cert_now.SubsUsages)) >= 86 else cert_now.SubsUsages,
                        "key_identy": str(cert_now.MainHashID).replace(":", ""),
                        "sub_identy": str(cert_now.SubsHashID).replace(":", ""),
                        "uid_serial": cert_now.OwnersInfo["UID"] if "UID" in cert_now.OwnersInfo else \
                            cert_now.OwnersInfo["SERIALNUMBER"] if "SERIALNUMBER" in cert_now.OwnersInfo else "(Empty)",
                        "cer_policy": cer_policy,
                        "user_name": user_name,
                        "user_code": cert_now.OwnersInfo["C"] if "C" in cert_now.OwnersInfo else "N/A",
                        "user_area": cert_now.OwnersInfo["S"] if "S" in cert_now.OwnersInfo else "N/A",
                        "user_city": cert_now.OwnersInfo["L"] if "L" in cert_now.OwnersInfo else "N/A",
                        "user_on_t": cert_now.OwnersInfo["O"] if "O" in cert_now.OwnersInfo else "(Empty)",
                        "user_ou_t": cert_now.OwnersInfo["OU"] if "OU" in cert_now.OwnersInfo else "(Empty)",

                        "last_name": last_name,
                        "last_code": cert_now.IssuerInfo["C"] if "C" in cert_now.IssuerInfo else "N/A",
                        "last_area": cert_now.IssuerInfo["S"] if "S" in cert_now.IssuerInfo else "N/A",
                        "last_city": cert_now.IssuerInfo["L"] if "L" in cert_now.IssuerInfo else "N/A",
                        "last_on_t": cert_now.IssuerInfo["O"] if "O" in cert_now.IssuerInfo else "(Empty)",
                        "last_ou_t": cert_now.IssuerInfo["OU"] if "OU" in cert_now.IssuerInfo else "(Empty)",
                    }
                    for fill_name in cert_map:
                        for label in ["cert_info", "cert_user", "cert_last"]:
                            label_now = self.labels[label]
                            if fill_name in label_now:
                                label_now[fill_name][1].config(text=cert_map[fill_name])
                else:
                    self.button["cert_main"]["sys"].config(state=tk.DISABLED)
                    self.button["cert_main"]["out"].config(state=tk.DISABLED)
            print(selected_name)

    def about_pages(self):
        messagebox.showinfo(self.la("msg_about_title"),
                            self.la("msg_about_about"))

    def check_tpm_h(self):
        process = subprocess.run(" powershell Get-TPM", text=True,
                                 capture_output=True, shell=True)
        results = process.stdout.splitlines()
        for line in results:
            if line.find("TpmActivated") >= 0:
                if line.find("True") >= 0:
                    messagebox.showinfo(self.la("msg_tpm_check_text"),
                                        self.la("msg_tpm_check_done") % "".join(results))
                    return True
                else:
                    messagebox.showerror(self.la("msg_tpm_check_text"),
                                         self.la("msg_tpm_check_fail") % "".join(results))
        messagebox.showwarning(self.la("msg_tpm_check_text"),
                               self.la("msg_tpm_check_none") % "\n".join(results))
        return False

    def open_github(self):
        webbrowser.open('https://github.com/PIKACHUIM/TPMSmartCard')

    def install_osc(self):
        os.system("msiexec /i OpenSC\\OpenSC-0.25.1_win%s-Light.msi "
                  "/passive /norestart" % platform.architecture()[0][:2])

    def card_change(self, in_type="pin"):
        if not self.pick["card"] or self.pick["card"] not in self.data.cards:
            return None

        def change(item, tips, is_same=False, *args):
            password = item.get()
            # print(password)
            if len(password) < 4:
                tips.config(text="❌ " + self.la("msg_pass_length_l1" if not is_same else "msg_pass_length_l2"))
                submit_button.config(state=tk.DISABLED)
            elif is_same and next_txt.get() != same_txt.get():
                tips.config(text="❌ " + self.la("msg_pass_not_same_"))
                submit_button.config(state=tk.DISABLED)
            else:
                tips.config(text="✅ ")
            if len(pass_txt.get()) >= 4 and len(next_txt.get()) >= 4:
                if next_txt.get() == same_txt.get():
                    next_tip.config(text="✅ ")
                    same_tip.config(text="✅ ")
                    submit_button.config(state=tk.NORMAL)
                else:
                    submit_button.config(state=tk.DISABLED)
            else:
                submit_button.config(state=tk.DISABLED)
            if in_type == "pin" and pass_txt.get() == next_txt.get() == same_txt.get():
                tips.config(text="❌ " + self.la("msg_pass_next_same"))
                submit_button.config(state=tk.DISABLED)

        def submit():
            card_uid = self.pick["card"].split(" ")[-1]
            pass_key = pass_txt.get()
            pass_new = next_txt.get()
            same_new = same_txt.get()
            # print(pass_key, pass_new, same_new)
            if pass_key == "" or len(pass_key) < 4:
                make.attributes('-topmost', False)
                messagebox.showwarning(self.la("warn"), self.la("msg_pass_length_l1"))
                make.attributes('-topmost', True)
            elif pass_new == "" or len(pass_new) < 4:
                make.attributes('-topmost', False)
                messagebox.showwarning(self.la("warn"), self.la("msg_pass_length_l2"))
                make.attributes('-topmost', True)
            elif pass_new != same_new:
                make.attributes('-topmost', False)
                messagebox.showwarning(self.la("warn"), self.la("msg_pass_not_same_"))
                make.attributes('-topmost', True)
            else:
                result = TPMSmartCard.changePIN(pass_key, pass_new, card_uid,
                                                type="--change-pin" \
                                                    if in_type == "pin" else "--unblock-pin")
                messagebox.showinfo(self.la("msg_pass_change_ok"), result)
                make.destroy()

        make = ttk.Toplevel(self.root)
        make.geometry("700x200")
        make.geometry(f"+{self.size[0]}+{self.size[1]}")
        make.title(self.la("msg_pass_change_tx") if in_type == "pin" else self.la("msg_pass_resets_tx"))

        pass_lan = self.la("msg_old") + " PIN: " if in_type == "pin" else self.la("msg_card") + " PUK: "
        pass_var = tk.StringVar()
        pass_tag = ttk.Label(make, text=pass_lan, bootstyle="info")
        pass_txt = ttk.Entry(make, bootstyle="info", width=60, textvariable=pass_var, show="*")
        pass_tip = ttk.Label(make, text="", bootstyle="info")
        pass_var.trace('w', partial(change, pass_txt, pass_tip, False))
        pass_tag.grid(column=0, row=1, pady=10, padx=15)
        pass_txt.grid(column=1, row=1, pady=10, padx=5)
        pass_tip.grid(column=2, row=1, pady=10, padx=5, sticky=W)

        next_var = tk.StringVar()
        next_pin = ttk.Label(make, text=self.la("msg_new") + " PIN: ", bootstyle="info")
        next_txt = ttk.Entry(make, bootstyle="info", width=60, textvariable=next_var, show="*")
        next_tip = ttk.Label(make, text="", bootstyle="info")
        next_var.trace('w', partial(change, next_txt, next_tip, True))
        next_pin.grid(column=0, row=2, pady=10, padx=15)
        next_txt.grid(column=1, row=2, pady=10, padx=5)
        next_tip.grid(column=2, row=2, pady=10, padx=5, sticky=W)

        same_var = tk.StringVar()
        same_pin = ttk.Label(make, text=self.la("msg_confirm") + " PIN: ", bootstyle="info")
        same_txt = ttk.Entry(make, bootstyle="info", width=60, textvariable=same_var, show="*")
        same_tip = ttk.Label(make, text="", bootstyle="info")
        same_var.trace('w', partial(change, same_txt, same_tip, True))
        same_pin.grid(column=0, row=3, pady=10, padx=15)
        same_txt.grid(column=1, row=3, pady=10, padx=5)
        same_tip.grid(column=2, row=3, pady=10, padx=5, sticky=W)

        cancel_button = ttk.Button(make, text=self.la("msg_cancel"), command=make.destroy, bootstyle="danger")
        cancel_button.grid(column=0, row=4, pady=5, padx=15)
        submit_button = ttk.Button(make, text=self.la("msg_confirm"), command=submit, bootstyle="info")
        submit_button.grid(column=2, row=4, pady=5, padx=0)
        submit_button.config(state=tk.DISABLED)
        make.mainloop()

    def card_create(self):
        def change(*args):
            if len(name_txt.get()) == 0 or len(pins_txt.get()) == 0:
                submit_button.config(state=tk.DISABLED)
            else:
                submit_button.config(state=tk.NORMAL)

        def disable():
            if puks_var.get():
                puks_txt.delete(0, tk.END)
                puks_txt.config(state=tk.DISABLED)
                make.attributes('-topmost', False)
                messagebox.showinfo(self.la("msg_disable") + "PUK", self.la("msg_ban_puk_warn"))
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

        def submit():
            if name_txt.get() == "":
                make.attributes('-topmost', True)
                messagebox.showwarning(self.la("fail"), self.la("msg_new_card_txt_e"))
            elif not 4 <= len(pins_txt.get()) <= 15:
                make.attributes('-topmost', True)
                messagebox.showwarning(self.la("fail"), self.la("msg_new_card_pin_e"))
            elif len(puks_txt.get()) > 0 and not 8 <= len(puks_txt.get()) <= 16:
                make.attributes('-topmost', True)
                messagebox.showwarning(self.la("fail"), self.la("msg_new_card_puk_e"))
            elif len(adks_txt.get()) != 48:
                make.attributes('-topmost', True)
                messagebox.showwarning(self.la("fail"), self.la("msg_new_card_key_e"))
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
                    out = "%s PIN: %s\n%s PUK: %s\n%s: %s" % (
                        self.la("msg_user"), pin,
                        self.la("msg_user"), puk,
                        self.la("mag_admin_key"), adk
                    )
                    # cid = result.find("ROOT")
                    # if cid >= 0:
                    #     out = result[cid:cid + 25] + "\n" + out
                    if deals_destroy:
                        make.destroy()
                        messagebox.showinfo(self.la("msg_create") + self.la("msg_result"), result)
                        pyperclip.copy(out)
                        messagebox.showinfo(self.la("msg_card") + self.la("msg_info"),
                                            out + self.la("msg_new_card_dones"))

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

        make = ttk.Toplevel(self.root)
        make.geometry("700x240")
        make.geometry(f"+{self.size[0]}+{self.size[1]}")
        make.attributes('-topmost', True)
        make.title(self.la("msg_new_tpm_card"))

        # 在新窗口中添加输入部件
        cancel_button = ttk.Button(make, text=self.la("msg_cancel") + self.la("msg_create"),
                                   command=cancel, bootstyle="danger")
        cancel_button.grid(column=0, row=4, pady=5, padx=15)
        submit_button = ttk.Button(make, text=self.la("msg_create") + self.la("msg_card"),
                                   command=submit, bootstyle="info")
        submit_button.grid(column=2, row=4, pady=5, padx=0)
        submit_button.config(state=tk.DISABLED)

        name_var = tk.StringVar()
        name_tag = ttk.Label(make, text=self.la("card_name") + ": ", bootstyle="info")
        name_tag.grid(column=0, row=0, pady=10, padx=15)
        name_txt = ttk.Entry(make, bootstyle="info", width=60, textvariable=name_var)
        name_txt.insert(0, "Personal TPM Virtual Smart Card")
        name_txt.grid(column=1, row=0, pady=10, padx=5)
        name_tip = ttk.Label(make, text="(1~63%s)" % self.la("msg_char"), bootstyle="info")
        name_tip.grid(column=2, row=0, pady=10, padx=5)
        name_var.trace('w', change)

        pins_var = tk.StringVar()
        pins_var.trace('w', change)
        pins_tag = ttk.Label(make, text=self.la("msg_card") + " PIN: ", bootstyle="info")
        pins_tag.grid(column=0, row=1, pady=10, padx=15)
        pins_txt = ttk.Entry(make, bootstyle="info", width=60, textvariable=pins_var, show="*")
        # for i in range(0, 8):
        #     pins_txt.insert(0, str(random.randint(0, 9)))
        pins_txt.grid(column=1, row=1, pady=10, padx=5)
        pins_tip = ttk.Label(make, text="(4~15%s)" % self.la("msg_char"), bootstyle="info")
        pins_tip.grid(column=2, row=1, pady=10, padx=5)

        puks_tag = ttk.Label(make, text=self.la("msg_card") + " PUK: ", bootstyle="info")
        puks_tag.grid(column=0, row=2, pady=10, padx=15)
        puks_txt = ttk.Entry(make, bootstyle="info", width=60)
        puks_txt.grid(column=1, row=2, pady=10, padx=5)
        puks_var = tk.BooleanVar()
        puks_tip = ttk.Checkbutton(make, text=self.la("msg_disable") + " PUK", bootstyle="info-round-toggle",
                                   variable=puks_var, command=disable)
        puks_tip.grid(column=2, row=2, pady=10, padx=5)
        for i in range(0, 16):
            puks_txt.insert(0, str(random.randint(0, 9)))

        adks_tag = ttk.Label(make, text=self.la("mag_admin_key") + ": ", bootstyle="info")
        adks_tag.grid(column=0, row=3, pady=10, padx=15)
        adks_txt = ttk.Entry(make, bootstyle="info", width=60)
        adks_txt.grid(column=1, row=3, pady=10, padx=5)
        adks_var = tk.BooleanVar()
        adks_tip = ttk.Checkbutton(make, text=self.la("mag_random_new"), bootstyle="info-round-toggle",
                                   variable=adks_var, command=randoms)
        for i in range(0, 48):
            adks_txt.insert(0, str(random.randint(0, 9)))
        adks_txt.config(state=tk.DISABLED)
        adks_tip.grid(column=2, row=3, pady=10, padx=5)
        adks_var.set(True)
        for i in range(0, 48):
            adks_txt.insert(0, str(random.randint(0, 9)))

        deals_process = ttk.Progressbar(make, length=432)
        deals_process.grid(column=1, row=4, pady=10, padx=5, sticky=tk.W)
        deals_process['value'] = 0
        make.mainloop()

    def deselectAll(self):
        for item in self.tables["card_main"][0].selection():
            self.tables["card_main"][0].selection_remove(item)
        for item in self.labels["card_info"]:
            self.labels["card_info"][item][1].config(text="")

    def data_delete(self, in_name="card"):
        data = self.data.cards if in_name == "card" else self.data.certs
        if self.pick[in_name] in data:
            make = ttk.Toplevel(self.root)
            make.geometry("300x220")
            make.geometry(f"+{self.size[0]}+{self.size[1]}")
            make.title(self.la("msg_remove") + self.la("msg_" + in_name))

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
                        result += self.la("delete_cert_reboot")
                    messagebox.showinfo(self.la("msg_remove") + self.la("msg_result"), result)

            def checks():
                if kill_var.get():
                    submit_b.config(state=tk.NORMAL)
                else:
                    submit_b.config(state=tk.DISABLED)

            kill_tag = ttk.Label(make,
                                 text=self.la("delete_cert_titles") % (
                                     self.la("msg_" + in_name), self.pick[in_name]))
            kill_tag.place(x=20, y=10)

            kill_tip = ttk.Label(make, bootstyle="danger",
                                 text=self.la("delete_cert_detail"))
            kill_tip.place(x=20, y=80)
            kill_var = tk.BooleanVar()
            kill_yes = ttk.Checkbutton(make, text=self.la("delete_cert_checks") % self.la("msg_" + in_name),
                                       bootstyle="dark", command=checks, variable=kill_var)
            kill_yes.state(['!alternate'])
            kill_yes.place(x=20, y=130)

            cancel_b = ttk.Button(make, text=self.la("msg_cancel"), command=make.destroy, bootstyle="success")
            cancel_b.place(x=20, y=180)
            submit_b = ttk.Button(make, text=self.la("msg_remove"), command=submit, bootstyle="danger")
            submit_b.place(x=230, y=180)
            submit_b.config(state=tk.DISABLED)

    def cert_import(self, flag="pfx"):
        sub = CertImport(flag, self.root, self)
        sub.page.mainloop()

    def reqs_create(self):
        def change(*args):
            # 主体名称判断 =============================
            all_keys = list(locals().keys()) + list(globals().keys())
            if "cn_txt" in all_keys:
                if len(cn_txt.get()) == 0:
                    cn_txt.config(bootstyle="danger")
                    if "submit_button" in all_keys:
                        submit_button.config(state=tk.DISABLED)
                else:
                    cn_txt.config(bootstyle="info")
                    if "submit_button" in all_keys:
                        submit_button.config(state=tk.NORMAL)
            # 邮件开关判断 =============================
            if "um_var" in all_keys:
                if um_var.get():
                    um_txt.config(state=tk.NORMAL)
                    um_txt.config(bootstyle="info")
                    um_tip.config(text="0-65536%s" % self.la("msg_char"))
                else:
                    um_txt.delete(0, tk.END)
                    um_txt.config(state=tk.DISABLED)
                    um_txt.config(bootstyle="default")
                    um_tip.config(text=self.la("msg_ml_text"))
            # 密钥限制开关 ===============================
            if v_data.get():
                v_sign.set(1)
                k_sign.config(state=tk.DISABLED)
            else:
                k_sign.config(state=tk.NORMAL)

        def checks(in_text, keyType):
            re_text = {
                "EMail": {
                    "EMail": r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
                },
                "DNS": {
                    "IPAddress": r"^((25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}(25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)$",
                    "IPAddress6": r"^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$|^::1$|^(::[^:]+)*::1$",
                    "DNS": r"^[a-zA-Z0-9]([a-zA-Z0-9.-]{1,253}[a-zA-Z0-9])?$",
                }

            }
            for keyName in re_text[keyType]:
                if re.match(re_text[keyType][keyName], in_text):
                    return keyName.replace("IPAddress6", "IPAddress")
            return None

        def submit():
            cn = cn_var.get().replace(",", " ").replace("\"", "")
            st = st_txt.get().replace(",", " ").replace("\"", "")
            ll = ll_txt.get().replace(",", " ").replace("\"", "")
            cc = cc_txt.get().replace(",", " ").replace("\"", "")
            ou = ou_txt.get().replace(",", " ").replace("\"", "")
            on = on_txt.get().replace(",", " ").replace("\"", "")
            dt = dt_txt.get().replace(",", " ").replace("\"", "")
            cc = self.conf['cncode'][cc] if cc in self.conf['cncode'] else ""
            domain = dn_txt.get().replace(",", ";").split(";")
            emails = um_txt.get().replace(",", ";").split(";")
            domain = [i for i in domain if len(i) > 0]
            emails = [i for i in emails if len(i) > 0]
            ken_len = kl_txt.get()[3:]
            ken_sha = kl_sha.get().lower()
            csp_txt = "Microsoft Base Smart Card Crypto Provider"
            if v_csp_ts.get() and len(csp_data.get()) > 0:
                csp_txt = csp_data.get()
            full_text = ('[Version]\n'
                         'Signature="$Windows NT$"\n'
                         '[NewRequest]\n'
                         'ProviderName = "%s"\n'
                         'ProviderType = 0\n'
                         'Exportable = FALSE\n'
                         'MachineKeySet = TRUE\n' % csp_txt)

            full_text += 'Subject = "%s%s%s%s%s%s%s%s"\n' % (
                "CN=%s," % cn if len(cn) > 0 else "Unknown,",
                "C=%s," % cc if len(cc) > 0 else "",
                "ST=%s," % st if len(st) > 0 else "",
                "L=%s," % ll if len(ll) > 0 else "",
                "O=%s," % on if len(on) > 0 else "",
                "OU=%s," % ou if len(ou) > 0 else "",
                "Description=%s," % dt if len(dt) > 0 else "",
                "2.5.4.15=Private"
            )
            full_text += 'KeySpec = %s%s%s\n' % (
                "AT_SIGNATURE" if v_sign.get() and not v_data.get() else "",
                "AT_KEYEXCHANGE" if v_data.get() else "",
                "AT_NONE" if not v_sign.get() and not v_data.get() else ""
            )
            ku_all = sum([
                ku_key[i] for i in ku_dat if ku_out[i].get()]
            )
            full_text += 'KeyUsage = "0x%04x"\n' % ku_all
            full_text += 'FriendlyName= "%s"\n' % cn
            full_text += 'KeyContainer= "C-%05d"\n' % randint(0, 99999)
            # full_text += 'SMIME= %s\n' % "TRUE" if um_var.get() else "FALSE"
            full_text += 'HashAlgorithm= %s\n' % ken_sha
            full_text += 'KeyLength= %s\n' % ken_len
            # 自签证书和拓展 ===============================================================
            if va_self.get():
                # 类型和时间 ===============================================================
                full_text += 'RequestType = Cert\n'
                full_text += 'NotBefore = "%s 00:00"\n' % open_dt.entry.get().split(" ")[0]
                full_text += 'NotAfter = "%s 00:00"\n' % stop_dt.entry.get().split(" ")[0]
            else:
                full_text += 'RequestType = PKCS10\n'
            # 拓展用途 =====================================================================
            full_text += '\n[EnhancedKeyUsageExtension]\n'
            if va_ca_t.get():
                full_text += 'OID=2.5.29.37\n'
                full_text += 'OID=2.5.29.32\n'
            for i in ext_list:
                if ext_out[i].get():
                    full_text += ext_list[i] + "\n"
            if len(domain) > 0 or len(emails) > 0:
                full_text += 'OID=1.2.840.113549.1.9.15\n'
            # 拓展属性 ======================================================================
            full_text += '\n[Extensions]\n'
            if va_ca_t.get():
                full_text += '2.5.29.19 = "{text}ca=1"\n'
            if len(domain) > 0 or len(emails) > 0:
                full_text += '2.5.29.17 = {text}\n'
                allData = {"EMail": emails, "DNS": domain}
                for keyType in allData:
                    extData = allData[keyType]
                    for keyData in extData:
                        if len(keyData) > 0:
                            keyName = checks(keyData, keyType)
                            if keyName is not None:
                                full_text += '_continue_ = %s=%s&\n' % (
                                    keyName, keyData
                                )
                            else:
                                make.attributes('-topmost', False)
                                messagebox.showwarning(
                                    self.la("msg_error_ut"),
                                    self.la("msg_error_it") + "\n%s" % keyData)
                                make.attributes('-topmost', True)
                                return None

            print(full_text)
            make.attributes('-topmost', False)
            file_path = "%s\\%s.inf" % (os.path.expandvars("%APPDATA%"),
                                        hashlib.sha256(full_text.encode()).hexdigest())
            print(file_path)
            with open(file_path, 'w', encoding="utf8") as file_file:
                file_file.write(full_text)
            save_path = filedialog.asksaveasfilename(
                defaultextension=".csr",  # 默认文件扩展名
                filetypes=[("Cert Request", "*.csr"), ("All files", "*.*")],  # 文件类型过滤器
                initialdir="~",  # 初始目录
                initialfile="%s.csr" % cn,  # 初始文件名
                title="Save as"  # 对话框标题
            )
            result = TPMSmartCard.createCSR(file_path, save_path)
            messagebox.showinfo(self.la("b_csr") + self.la("msg_create"), result)
            # make.attributes('-topmost', True)
            self.load_status()
            make.destroy()

        def csp_ts(*args):
            all_keys = list(locals().keys()) + list(globals().keys())
            if "v_csp_ts" in all_keys and "csp_data" in all_keys:
                if v_csp_ts.get():
                    csp_data.grid(column=2, row=10, pady=5, padx=15, sticky=W, columnspan=5)
                    csp_list = TPMSmartCard.CSPFetch()
                    csp_name = "Microsoft Base Smart Card Crypto Provider"
                    csp_data.config(values=csp_list)
                    if csp_name in csp_list:
                        csp_data.current(csp_list.index(csp_name))
                else:
                    csp_data.grid_forget()

        make = ttk.Toplevel(self.root)
        make.geometry("800x540")
        make.geometry(f"+{self.size[0]}+{self.size[1]}")
        make.attributes('-topmost', True)
        make.title(self.la("msg_create") + self.la("msg_cert"))

        cn_var = tk.StringVar()
        cn_var.trace('w', change)
        cn_tag = ttk.Label(make, text=self.la("user_name") + ": ")
        cn_tag.grid(column=0, row=0, pady=10, padx=15)
        cn_txt = ttk.Entry(make, bootstyle="info", width=83, textvariable=cn_var)
        cn_txt.grid(column=1, row=0, pady=10, padx=5, columnspan=6)
        cn_tip = ttk.Label(make, text="%s1-64%s" % (self.la("msg_must_in"), self.la("msg_char")))
        cn_tip.grid(column=7, row=0, pady=10, padx=5)

        st_tag = ttk.Label(make, text=self.la("user_area") + ": ")
        st_tag.grid(column=0, row=1, pady=10, padx=15, sticky=W)
        st_txt = ttk.Entry(make, bootstyle="info", width=25)
        st_txt.grid(column=1, row=1, pady=10, padx=5, sticky=W, columnspan=2)

        ll_tag = ttk.Label(make, text=self.la("user_city") + ": ")
        ll_tag.grid(column=3, row=1, pady=10, padx=15, sticky=W)
        ll_txt = ttk.Entry(make, bootstyle="info", width=25)
        ll_txt.grid(column=4, row=1, pady=10, padx=5, sticky=W, columnspan=2)

        cc_tag = ttk.Label(make, text=self.la("user_code") + ": ")
        cc_tag.grid(column=6, row=1, pady=10, padx=15)
        cc_txt = ttk.Combobox(make, bootstyle="info", width=7, values=list(self.conf['cncode'].keys()))
        cc_txt.grid(column=7, row=1, pady=10, padx=5, sticky=W, columnspan=2)
        cc_txt.set("N/A")

        on_tag = ttk.Label(make, text=self.la("user_on_t") + ": ")
        on_tag.grid(column=0, row=2, pady=10, padx=15, sticky=W)
        on_txt = ttk.Entry(make, bootstyle="info", width=35)
        on_txt.grid(column=1, row=2, pady=10, padx=5, sticky=W, columnspan=3)

        ou_tag = ttk.Label(make, text=self.la("msg_ou_full") + ": ")
        ou_tag.grid(column=4, row=2, pady=10, padx=15, sticky=W)
        ou_txt = ttk.Entry(make, bootstyle="info", width=38)
        ou_txt.grid(column=5, row=2, pady=10, padx=5, sticky=W, columnspan=3)

        kl_tag = ttk.Label(make, text=self.la("pub_length") + ": ")
        kl_tag.grid(column=0, row=3, pady=10, padx=15)
        kl_txt = ttk.Combobox(make, bootstyle="info", width=7, values=["RSA1024", "RSA2048"])
        kl_txt.grid(column=1, row=3, pady=10, padx=5, sticky=W)
        kl_txt.set("RSA2048")

        kl_sha = ttk.Combobox(make, bootstyle="info", width=7, values=["SHA1", "SHA256"])
        kl_sha.grid(column=2, row=3, pady=10, padx=5, sticky=W)
        kl_sha.set("SHA256")

        ks_tag = ttk.Label(make, text=self.la("msg_ks_full"))
        ks_tag.grid(column=3, row=3, pady=10, padx=15)
        v_sign = tk.IntVar()
        v_sign.set(1)
        v_sign.trace('w', change)
        k_sign = ttk.Checkbutton(make, bootstyle="success", width=8, text=self.la('msg_sign'),
                                 variable=v_sign)
        k_sign.grid(column=4, row=3, pady=10, padx=5, sticky=W)
        k_sign.state(['!alternate'])
        k_sign.config(state=tk.DISABLED)
        v_data = tk.IntVar()
        v_data.set(1)
        v_data.trace('w', change)
        k_data = ttk.Checkbutton(make, bootstyle="success", width=8, text=self.la('msg_data'),
                                 variable=v_data)
        k_data.grid(column=5, row=3, pady=10, padx=5, sticky=W)
        k_data.state(['!alternate'])

        ml_tag = ttk.Label(make, text=self.la("msg_ml_lite"))
        ml_tag.grid(column=6, row=3, pady=10, padx=15)
        um_var = tk.IntVar()
        um_var.trace('w', change)
        m_sign = ttk.Checkbutton(make, bootstyle="info-round-toggle", text=self.la('msg_ml_full'),
                                 variable=um_var)
        m_sign.grid(column=7, row=3, pady=10, padx=5, sticky=W)

        ku_tag = ttk.Label(make, text=self.la("key_usages") + ": ")
        ku_tag.grid(column=0, row=4, pady=10, padx=15)
        ku_num = 1
        ku_dat = {}
        ku_out = {}
        ku_key = {"DigitalSignature": 0x0080,
                  "nonRepudiation": 0x0040,
                  "Encipherment": 0x0020 + 0x0010,
                  "KeyAgreement": 0x0008,
                  "CertCRLsSign": 0x0004 + 0x0002,
                  "EncipherOnly": 0x0001,
                  "DecipherOnly": 0x8000}
        for ku_inf in ku_key:
            ku_out[ku_inf] = tk.BooleanVar()
            ku_dat[ku_inf] = ttk.Checkbutton(make, bootstyle="primary", width=10, text=self.la(ku_inf),
                                             variable=ku_out[ku_inf])
            ku_dat[ku_inf].grid(column=ku_num, row=4, padx=8 if ku_inf == "DecipherOnly" else 5)
            ku_num += 1
            ku_dat[ku_inf].state(['!alternate'])

        dn_tag = ttk.Label(make, text=self.la("msg_domain") + ": ")
        dn_tag.grid(column=0, row=5, pady=10, padx=15)
        dn_txt = ttk.Entry(make, bootstyle="info", width=83)
        dn_txt.grid(column=1, row=5, pady=10, padx=5, columnspan=6)
        dn_tip = ttk.Label(make, text="%s" % self.la("msg_splits"))
        dn_tip.grid(column=7, row=5, pady=10, padx=0)

        um_tag = ttk.Label(make, text=self.la("msg_emails") + ": ")
        um_tag.grid(column=0, row=6, pady=10, padx=15)
        um_txt = ttk.Entry(make, bootstyle="default", width=83)
        um_txt.grid(column=1, row=6, pady=10, padx=5, columnspan=6)
        um_tip = ttk.Label(make, text=self.la("msg_ml_text"))
        um_tip.grid(column=7, row=6, pady=10, padx=0)
        um_txt.config(state=tk.DISABLED)

        dt_tag = ttk.Label(make, text=self.la("DESCRIPTION") + ": ")
        dt_tag.grid(column=0, row=7, pady=10, padx=15)
        dt_txt = ttk.Entry(make, bootstyle="info", width=83)
        dt_txt.grid(column=1, row=7, pady=10, padx=5, columnspan=6)
        dt_tip = ttk.Label(make, text="0-65536%s" % self.la("msg_char"))
        dt_tip.grid(column=7, row=7, pady=10, padx=0)

        def resign(*args):
            if va_self.get():
                # open_dt.grid(column=3, row=8, pady=10, padx=15, columnspan=2)
                # stop_dt.grid(column=6, row=8, pady=10, padx=15, columnspan=2)
                # open_pt.grid(column=2, row=8, pady=10, padx=15)
                # stop_pt.grid(column=5, row=8, pady=10, padx=15)
                open_dt.entry.config(state=tk.NORMAL)
                stop_dt.entry.config(state=tk.NORMAL)
                open_dt.button.config(state=tk.NORMAL)
                stop_dt.button.config(state=tk.NORMAL)
                is_ca_t.config(state=tk.NORMAL)
                for i in ext_list:
                    ext_dat[i].config(state=tk.NORMAL)
            else:
                # open_pt.grid_forget()
                # stop_pt.grid_forget()
                # open_dt.grid_forget()
                # stop_dt.grid_forget()
                open_dt.entry.config(state=tk.DISABLED)
                stop_dt.entry.config(state=tk.DISABLED)
                open_dt.button.config(state=tk.DISABLED)
                stop_dt.button.config(state=tk.DISABLED)
                is_ca_t.config(state=tk.DISABLED)
                for i in ext_list:
                    ext_dat[i].config(state=tk.DISABLED)

        va_self = tk.BooleanVar()
        va_self.trace('w', resign)
        tg_self = ttk.Label(make, text=self.la("is_sign") + ": ")
        tg_self.grid(column=0, row=8, pady=20, padx=15)
        is_self = ttk.Checkbutton(make, bootstyle="info-round-toggle", text=self.la('is_self'), variable=va_self)
        is_self.grid(column=1, row=8, pady=10, padx=5)

        open_pt = ttk.Label(make, text=self.la("cert_open") + ": ")
        open_pt.grid(column=2, row=8, pady=10, padx=15)
        open_dt = ttk.DateEntry(make, style='success.TCalendar', width=15)
        open_dt.grid(column=3, row=8, pady=10, padx=15, columnspan=2)
        open_dt.entry.config(state=tk.DISABLED)
        open_dt.button.config(state=tk.DISABLED)
        stop_pt = ttk.Label(make, text=self.la("cert_stop") + ": ")
        stop_pt.grid(column=5, row=8, pady=10, padx=15)
        stop_dt = ttk.DateEntry(make, style='success.TCalendar', width=15)
        stop_dt.grid(column=6, row=8, pady=10, padx=15, columnspan=2)
        date_tp = open_dt.entry.get()
        date_tp = str(int(date_tp[:4]) + 1) + date_tp[4:]
        stop_dt.entry.delete(0, tk.END)
        stop_dt.entry.insert(0, date_tp)
        stop_dt.entry.config(state=tk.DISABLED)
        stop_dt.button.config(state=tk.DISABLED)

        def set_ca(*args):
            if va_ca_t.get():
                ku_out["CertCRLsSign"].set(True)
            else:
                ku_out["CertCRLsSign"].set(False)

        va_ca_t = tk.BooleanVar()
        va_ca_t.trace('w', set_ca)
        is_ca_t = ttk.Checkbutton(make, bootstyle="info",
                                  text=self.la('is_ca_t'),
                                  variable=va_ca_t)
        is_ca_t.grid(column=0, row=9, pady=10, padx=5)

        ext_list = {
            "codeSign": "OID=1.3.6.1.5.5.7.3.3\nOID=2.23.140.1.4.1",
            "fileSign": "OID=1.2.840.113583.1.1.5\nOID=1.3.6.1.4.1.311.10.3.12",
            "mailSign": "OID=1.3.6.1.5.5.7.3.4\nOID=1.3.6.1.4.1.311.21.19",
            "sslUsage": "OID=1.3.6.1.5.5.7.3.1\nOID=1.3.6.1.5.5.7.3.2",
            "sshUsage": "OID=1.3.6.1.5.5.7.3.10\nOID=1.3.6.1.5.5.7.3.2",
            "efsUsage": "OID=1.3.6.1.4.1.311.10.3.4\nOID=1.3.6.1.4.1.311.10.3.4.1",
            "bitLocks": "OID=1.3.6.1.4.1.311.67.1.1\nOID=1.3.6.1.4.1.311.67.1.2",
            # "anyUsage": "",
        }
        ext_out = {}
        ext_dat = {}
        ext_num = 1
        for ext_name in ext_list:
            ext_out[ext_name] = tk.BooleanVar()
            ext_dat[ext_name] = ttk.Checkbutton(make, bootstyle="primary", width=10, text=self.la(ext_name),
                                                variable=ext_out[ext_name])
            ext_dat[ext_name].grid(column=ext_num, row=9, padx=5)
            ext_num += 1
            ext_dat[ext_name].state(['!alternate'])
        resign()

        cancel_button = ttk.Button(make, text=self.la("msg_cancel"), command=make.destroy, bootstyle="danger")
        cancel_button.grid(column=0, row=10, pady=5, padx=15)
        submit_button = ttk.Button(make, text=self.la("msg_create_csr"), command=submit, bootstyle="success")
        submit_button.grid(column=7, row=10, pady=5, padx=0)
        submit_button.config(state=tk.DISABLED)
        v_csp_ts = tk.IntVar()
        v_csp_ts.set(0)
        v_csp_ts.trace('w', csp_ts)
        csp_sets = ttk.Checkbutton(make, bootstyle="info-round-toggle", text=self.la('csp_set_'),
                                   variable=v_csp_ts)
        csp_data = ttk.Combobox(make, bootstyle="info", width=62, values=list())
        csp_sets.grid(column=1, row=10, pady=5, padx=15, sticky=W)
        # csp_data.grid(column=2, row=10, pady=5, padx=15, sticky=W, columnspan=4)
        make.mainloop()


if __name__ == "__main__":
    app = SmartCardAPP()
