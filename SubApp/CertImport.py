import base64
import hashlib
import os
from random import randbytes
from tkinter import filedialog, messagebox

import pyperclip
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from ttkbootstrap import *
import ttkbootstrap as ttk

from Module.Cryptography import Crypto
from Module.TPMSmartCard import TPMSmartCard


class CertImport:
    def __init__(self, in_flag, in_root, in_main):
        self.flag = in_flag
        self.main = in_main
        self.page = ttk.Toplevel(in_root)
        self.pri_key = None
        self.pub_key = None
        # 导入路径 =====================================================================================
        self.path_var = tk.StringVar()
        self.path_var.trace('w', self.change)
        self.path_tag = ttk.Label(self.page, bootstyle="info",
                                  text="%s: " % self.main.la("msg_select_file_fp"))
        self.path_txt = ttk.Entry(self.page, bootstyle="info", width=60, textvariable=self.path_var)
        self.path_tip = ttk.Button(self.page, bootstyle="info", command=self.search,
                                   text=self.main.la("msg_open") + self.main.la("msg_file"))
        # 导入密码 =====================================================================================
        if self.flag == "pfx":
            self.pass_var = tk.StringVar()
            self.pass_var.trace('w', self.change)
            self.pass_tag = ttk.Label(self.page, bootstyle="info",
                                      text=self.main.la("msg_cert") + self.main.la("msg_pass") + ": ")
            self.pass_txt = ttk.Entry(self.page, bootstyle="info", width=60, show="*",
                                      textvariable=self.pass_var)
            self.v_clouds = tk.IntVar()
            self.v_clouds.set(0)
            self.v_clouds.trace('w', self.clouds)
            self.k_clouds = ttk.Checkbutton(self.page, bootstyle="success-round-toggle",
                                            text=self.main.la('msg_cert_cloud'),
                                            variable=self.v_clouds)
        # 确认按钮 ====================================================================================
        self.cancel_button = ttk.Button(self.page, bootstyle="danger", command=self.page.destroy,
                                        text=self.main.la("msg_cancel"))
        self.submit_button = ttk.Button(self.page, bootstyle="success", command=self.submit,
                                        text=self.main.la("msg_import") + self.flag.upper())
        self.deals_process = ttk.Progressbar(self.page, length=432)
        self.deals_process['value'] = 0
        if self.flag == "pfx":
            self.submit_button.config(state=tk.DISABLED)
        # 执行操作 =====================================================================================
        self.packUI()

    def packUI(self):
        self.page.attributes('-topmost', True)
        self.page.geometry("700x160" if self.flag == "pfx" else "700x120")
        self.page.geometry(f"+{self.main.size[0]}+{self.main.size[1]}")
        self.page.title(self.main.la("msg_import") + self.main.la("msg_cert"))
        self.path_tag.grid(column=0, row=0, pady=10, padx=15)
        self.path_txt.grid(column=1, row=0, pady=10, padx=5)
        self.path_tip.grid(column=2, row=0, pady=10, padx=5)
        self.pass_tag.grid(column=0, row=1, pady=10, padx=15)
        self.pass_txt.grid(column=1, row=1, pady=10, padx=5)
        self.k_clouds.grid(column=2, row=1, pady=20, padx=5, sticky=W)
        self.cancel_button.grid(column=0, row=3, pady=5, padx=15)
        self.submit_button.grid(column=2, row=3, pady=5, padx=0)
        self.deals_process.grid(column=1, row=3, pady=10, padx=5, sticky=tk.W)

    def change(self, *args):
        if self.flag == "pfx" and len(self.pass_txt.get()) == 0:
            if not self.v_clouds.get():
                self.submit_button.config(state=tk.DISABLED)
        if len(self.path_txt.get()) == 0:
            self.submit_button.config(state=tk.DISABLED)
        elif not os.path.exists(self.path_txt.get()):
            self.submit_button.config(state=tk.DISABLED)
        else:
            self.submit_button.config(state=tk.NORMAL)
        if self.v_clouds.get():
            if len(self.path_txt.get()) == 0:
                self.submit_button.config(state=tk.DISABLED)
            else:
                self.submit_button.config(state=tk.NORMAL)

    def x25519(self, ):
        client_pri_key = X25519PrivateKey.generate()
        client_pub_key = client_pri_key.public_key()
        client_pub_pem = client_pub_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        self.pri_key = client_pri_key
        self.pub_key = base64.b64encode(client_pub_pem).decode()

    def clouds(self, *args):
        # 云端下发 ====================================
        if self.v_clouds.get():
            self.pass_tag.config(text=self.main.la("msg_keys_cloud") + ": ")
            self.path_tip.grid_forget()
            self.x25519()
            self.pass_txt.delete(0, tk.END)
            self.pass_txt.config(show="")
            self.pass_txt.insert(0, self.pub_key)
            self.path_tag.config(text=self.main.la("msg_urls_cloud"))
            self.path_txt.delete(0, tk.END)
            self.path_txt.insert(0, "http://127.0.0.1:1080/get/cert")
            if len(self.path_txt.get()) == 0:
                self.submit_button.config(state=tk.DISABLED)
            else:
                self.submit_button.config(state=tk.NORMAL)
            pyperclip.copy(self.pub_key)
            self.page.attributes('-topmost', False)
            messagebox.showinfo(self.main.la("msg_cert_cloud"), self.main.la("msg_tips_cloud"))
            self.page.attributes('-topmost', True)
        else:
            self.path_tip.grid(column=2, row=0, pady=10, padx=5)
            self.path_txt.delete(0, tk.END)
            self.pass_tag.config(text=self.main.la("msg_cert") + self.main.la("msg_pass") + ": ")
            self.pass_txt.delete(0, tk.END)
            self.pass_txt.config(show="*")
            # path_tip.config(text=self.la("msg_open") + self.la("msg_file"))
            self.path_tag.config(text=self.main.la("msg_select_file_fp"))

    def search(self, ):
        self.page.attributes('-topmost', False)
        file_path = filedialog.askopenfilename(
            filetypes=[
                ("PFX Files", "*.pfx;*.p12") if self.flag == "pfx" \
                    else ("Cert Chains", "*.p7b")
                # else ("Cert Files", "*.cer;*.crt;*.pem;*.der;*.p7b")
            ]
        )
        if file_path:
            print(f"File Path：{file_path}")
            self.path_txt.delete(0, tk.END)
            self.path_txt.insert(0, file_path)
        self.page.attributes('-topmost', True)

    def submit(self, ):
        self.page.attributes('-topmost', False)
        # 云端下发 =======================================================================
        if self.v_clouds.get():
            url = self.path_txt.get()
            pub = self.pass_txt.get()
            responded_apis = requests.get(
                url, data={"pubkey": pub, },
            )
            if responded_apis.status_code == 200:
                responded_json = responded_apis.json()
                if "flag" in responded_json and responded_json["flag"]:
                    responded_json = responded_json["data"]
                    encrypted_data = responded_json['vaults']
                    server_pub_pem = responded_json['pubkey']
                    server_pub_key = X25519PublicKey.from_public_bytes(
                        base64.b64decode(server_pub_pem)
                    )
                    encrypted_keys = self.pri_key.exchange(server_pub_key)
                    decrypted_data = Crypto.aes_decrypt(
                        encrypted_keys,
                        base64.b64decode(
                            encrypted_data.encode()
                        )
                    )
                    tmp = hashlib.sha256(decrypted_data).hexdigest()
                    cert_path = os.path.join(os.getenv('APPDATA'), tmp + ".pfx")
                    with open(cert_path, 'wb') as save_file:
                        save_file.write(decrypted_data)
                    result = TPMSmartCard.initCerts(
                        cert_path, responded_json['pfxkey'])
                    with open(cert_path, 'wb') as save_file:
                        for i in range(0, int(len(decrypted_data) / 16 + 1)):
                            save_file.write(randbytes(16))
                    self.main.load_status()
                else:
                    messagebox.showwarning(self.main.la("fail"),
                                           "Error Responded Data")
                    self.page.attributes('-topmost', True)
                    return False
            else:
                messagebox.showwarning(self.main.la("fail"),
                                       "Error Responded Code")
                self.page.attributes('-topmost', True)
                return False
        # 本地导入 =======================================================================
        else:
            if not os.path.exists(self.path_txt.get()):
                messagebox.showwarning(self.main.la("fail"),
                                       self.main.la("msg_file_not_exist"))
                self.page.attributes('-topmost', True)
                return False
            else:
                self.page.attributes('-topmost', False)
                if self.flag == "pfx":
                    result = TPMSmartCard.initCerts(self.path_txt.get(),
                                                    self.pass_txt.get())
                else:
                    result = TPMSmartCard.loadCerts(self.path_txt.get())
                self.main.load_status()
                self.page.destroy()
        messagebox.showinfo(
            self.main.la("msg_import") + self.main.la("msg_cert") + self.main.la("msg_result"),
            result + self.main.la("msg_import_results"))
