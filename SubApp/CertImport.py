import base64
import hashlib
import json
import os
from random import randbytes
from tkinter import filedialog, messagebox

import pyperclip
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from ttkbootstrap import *
import ttkbootstrap as ttk

from Module import Paths
from Module import Theme
from Module.AppConfigure import AppConfigure
from Module.Cryptography import Crypto
from Module.TPMSmartCard import TPMSmartCard


class CertImport:
    def __init__(self,
                 in_flag="pfx",
                 in_root=None,
                 in_main=None):
        self.flag = in_flag
        self.main = in_main
        self.page = in_root
        self.apps = False
        if self.page is None:
            self.page = tk.Tk()
            self.apps = True
            self.page.iconbitmap(Paths.resource("Config", "iconer", "icon02.ico"))
        else:
            self.page = ttk.Toplevel(in_root)
        if self.main is None:
            self.main = AppConfigure()
            self.main.read()

        # self.page.attributes('-topmost', True)
        # 关闭窗口（点右上角 × / 取消）都要走 close，先取消主题订阅再销毁
        self.page.protocol("WM_DELETE_WINDOW", self.close)
        self.page.geometry("%dx%d" % (
            # 拉丁/西里尔字母比汉字占位更宽，按语言调整窗口宽度
            750 if self.main.wide else 630,
            200 if self.flag == "pfx" else 120
        ))
        # self.page.geometry(f"+{self.main.size[0]}+{self.main.size[1]}")
        self.page.title(self.main.i18n("msg_import") + self.main.i18n("msg_cert"))
        self.pri_key = None
        self.pub_key = None
        # 导入路径 =====================================================================================
        self.path_var = tk.StringVar()
        self.path_var.trace('w', self.change)
        self.path_tag = ttk.Label(self.page, bootstyle="info",
                                  text="%s" % self.main.i18n("msg_select_file_fp"))
        self.path_txt = ttk.Entry(self.page, bootstyle="info", width=60, textvariable=self.path_var)
        self.path_tip = ttk.Button(self.page, bootstyle="info", command=self.search,
                                   text=self.main.i18n("msg_open") + self.main.i18n("msg_file"))
        if self.flag == "pfx":
            self.pass_var = tk.StringVar()
            self.pass_tag = ttk.Label(self.page, bootstyle="info",
                                      text=self.main.i18n("msg_cert") + self.main.i18n("msg_pass"))
            self.pass_txt = ttk.Entry(self.page, bootstyle="info", width=60, show="*",
                                      textvariable=self.pass_var)
        # 导入密码 =====================================================================================
        if self.flag == "pfx":
            self.pass_var.trace('w', self.change)
            self.v_clouds = tk.IntVar()
            self.v_clouds.set(0)
            self.v_clouds.trace('w', self.clouds)
            self.k_clouds = ttk.Checkbutton(self.page, bootstyle="success-round-toggle",
                                            text=self.main.i18n('msg_cert_cloud'),
                                            variable=self.v_clouds)
            # 云端下发方式：勾选 = 使用密码（取件码，自协商）下发；不勾选 = 交换密钥（X25519）
            # 说明：云端下发无法使用本地 CSP，因此这里直接复用「使用本地 CSP」复选框的位置，
            #      进入云端下发时用「使用密码下发」替换它（见 apply_cloud）。
            #      默认（每次进入云端下发）为「使用密码下发」，交换密钥需用户自己切换。
            self.v_cloud_pass = tk.IntVar()
            self.v_cloud_pass.set(1)
            self.v_cloud_pass.trace('w', self.cloud_pass_switch)
            self.k_cloud_pass = ttk.Checkbutton(self.page, bootstyle="success-round-toggle",
                                                text=self.main.i18n('msg_cloud_pass'),
                                                variable=self.v_cloud_pass)
            self.v_csp_ts = tk.IntVar()
            self.v_csp_ts.trace('w', self.csp_ts)
            self.csp_sets = ttk.Checkbutton(self.page, bootstyle="success-round-toggle",
                                            text=self.main.i18n('csp_sets'),
                                            variable=self.v_csp_ts)
            self.csp_data = ttk.Combobox(self.page, bootstyle="info", width=40,
                                         values=list())
        # 确认按钮 ====================================================================================
        self.cancel_button = ttk.Button(self.page, bootstyle="danger", command=self.close,
                                        text=self.main.i18n("msg_cancel"))
        self.submit_button = ttk.Button(self.page, bootstyle="success", command=self.submit,
                                        text=self.main.i18n("msg_import") + self.flag.upper())
        # self.deals_process = ttk.Progressbar(self.page, length=432)
        # self.deals_process['value'] = 0
        self.import_output = ttk.Label(self.page, bootstyle="info", text=self.main.i18n(self.flag + "_text"))

        if self.flag == "pfx":
            self.submit_button.config(state=tk.DISABLED)
        # 执行操作 =====================================================================================
        self.packUI()
        # 窗口按内容实测尺寸再定一次：提示语、CSP 选项、按钮等文案在各语言下长度差别很大，
        # 固定尺寸会把右侧内容挤掉（不低于上面的设计尺寸，且不超出屏幕）
        self.page.update_idletasks()
        self.page.geometry("%dx%d" % (
            min(max(750 if self.main.wide else 630, self.page.winfo_reqwidth()),
                self.page.winfo_screenwidth() - 40),
            min(max(200 if self.flag == "pfx" else 120, self.page.winfo_reqheight()),
                self.page.winfo_screenheight() - 80)
        ))
        self.page.resizable(False, False)

    def packUI(self):
        self.path_tag.grid(column=0, row=0, pady=10, padx=15)
        self.path_txt.grid(column=1, row=0, pady=10, padx=5, columnspan=2)
        self.path_tip.grid(column=3, row=0, pady=10, padx=5)
        if self.flag == "pfx":
            self.pass_tag.grid(column=0, row=1, pady=10, padx=15)
            self.pass_txt.grid(column=1, row=1, pady=10, padx=5, columnspan=2)
            self.k_clouds.grid(column=3, row=1, pady=20, padx=5, sticky=W)
            self.csp_sets.grid(column=1, row=3, pady=20, padx=5, sticky=W)
        self.cancel_button.grid(column=0, row=3, pady=5, padx=15)
        self.submit_button.grid(column=3, row=3, pady=5, padx=0)
        # self.deals_process.grid(column=1, row=3, pady=10, padx=5, sticky=tk.W)
        self.import_output.grid(column=2, row=3, pady=10, padx=5, sticky=tk.W)
        # CSP / 云端下发仅 PFX 导入才有对应控件（cer 导入直接走文件导入）
        if self.flag == "pfx":
            self.v_csp_ts.set(0 if self.apps == False else 1)

    def close(self):
        """关闭窗口；先取消 ttkbootstrap 的主题订阅再销毁。

        控件销毁后订阅不会自动移除，之后切换主题时 ttkbootstrap 会去刷新这些
        已销毁的控件（本窗口有 CSP 下拉框）并报 TclError，见 Module.Theme.unsubscribe。
        """
        Theme.unsubscribe(self.page)
        try:
            self.page.destroy()
        except Exception:
            pass

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
        if self.flag == "pfx" and self.v_clouds.get():
            # 云端下发：地址 + 下方文本框都必须填写（取件码 / 交换密钥）
            if len(self.path_txt.get()) == 0 or len(self.pass_txt.get()) == 0:
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

    def csp_ts(self, *args):
        if self.v_csp_ts.get():
            self.import_output.grid_forget()
            self.csp_data.grid(column=2, row=3, pady=10, padx=5, sticky=tk.W)
            csp_list = TPMSmartCard.CSPFetch()
            csp_data = "Microsoft Base Smart Card Crypto Provider"
            self.csp_data.config(values=csp_list)
            if csp_data in csp_list:
                self.csp_data.current(csp_list.index(csp_data))

        else:
            self.import_output.grid(column=2, row=3, pady=10, padx=5, sticky=tk.W)
            self.csp_data.grid_forget()

    def clouds(self, *args):
        # 云端下发 ====================================
        if self.v_clouds.get():
            # 每次进入云端下发都回到默认的「使用密码下发」；
            # 置位会触发 cloud_pass_switch → apply_cloud，这里不能再调用一次（否则提示会弹两遍）
            if self.v_cloud_pass.get():
                self.apply_cloud()
            else:
                self.v_cloud_pass.set(1)
        else:
            # 退出云端下发：恢复「使用本地 CSP」并按其勾选状态刷新
            self.k_cloud_pass.grid_forget()
            self.csp_sets.grid(column=1, row=3, pady=20, padx=5, sticky=W)
            self.csp_ts()
            self.path_tip.grid(column=3, row=0, pady=10, padx=5)
            self.path_txt.delete(0, tk.END)
            self.pass_tag.config(text=self.main.i18n("msg_cert") + self.main.i18n("msg_pass"))
            self.pass_txt.delete(0, tk.END)
            self.pass_txt.config(show="*")
            # path_tip.config(text=self.la("msg_open") + self.la("msg_file"))
            self.path_tag.config(text=self.main.i18n("msg_select_file_fp"))

    def cloud_pass_switch(self, *args):
        # 切换「使用密码下发 / 交换密钥」==================
        if self.v_clouds.get():
            self.apply_cloud()

    def csp_provider(self):
        """本地导入时返回所选 CSP 名称；云端下发不使用本地 CSP（固定 None）。"""
        if self.v_clouds.get():
            return None
        return self.csp_data.get() if self.v_csp_ts.get() else None

    def apply_cloud(self):
        # 云端下发：本地 CSP 不可用，把它的复选框位置换成「使用密码下发」
        self.csp_data.grid_forget()
        self.csp_sets.grid_forget()
        self.k_cloud_pass.grid(column=1, row=3, pady=20, padx=5, sticky=W)
        self.page.attributes('-topmost', False)
        if self.v_cloud_pass.get():
            # ---- 使用密码（取件码，自协商）下发 ----
            self.pass_tag.config(text=self.main.i18n("msg_cert_code"))
            self.path_tip.grid_forget()
            self.pass_txt.delete(0, tk.END)
            self.pass_txt.config(show="")
            tips = self.main.i18n("msg_tips_code")
        else:
            # ---- 交换密钥（X25519 预协商，原逻辑）----
            self.pass_tag.config(text=self.main.i18n("msg_keys_cloud"))
            self.path_tip.grid_forget()
            self.x25519()
            self.pass_txt.delete(0, tk.END)
            self.pass_txt.config(show="")
            self.pass_txt.insert(0, self.pub_key)
            pyperclip.copy(self.pub_key)
            tips = self.main.i18n("msg_tips_cloud")
        self.path_tag.config(text=self.main.i18n("msg_urls_cloud"))
        self.path_txt.delete(0, tk.END)
        self.path_txt.insert(0, "https://testca.524228.xyz/card/get/cert")
        self.change()
        messagebox.showinfo(self.main.i18n("msg_cert_cloud"), tips)
        self.page.attributes('-topmost', True)

    def search(self, ):
        self.page.attributes('-topmost', False)
        file_path = filedialog.askopenfilename(
            filetypes=[
                (self.main.i18n("msg_dlg_cert_files"), "*.pfx;*.p12")
                if self.flag == "pfx" else
                (self.main.i18n("msg_dlg_cert_files"), "*.p7b")
            ]
        )
        if file_path:
            print(f"File Path：{file_path}")
            self.path_txt.delete(0, tk.END)
            self.path_txt.insert(0, file_path)
        self.page.attributes('-topmost', True)

    def import_decrypted(self, in_pfx, in_pass):
        """把解密得到的 PFX 写入临时文件 → 导入卡片 → 覆写销毁临时文件。

        返回 ``(输出文本, 是否成功)``（见 ``TPMSmartCard.initCerts``）。
        """
        tmp = hashlib.sha256(in_pfx).hexdigest()
        cert_path = os.path.join(os.getenv('APPDATA') or os.path.expanduser("~"), tmp + ".pfx")
        try:
            with open(cert_path, 'wb') as save_file:
                save_file.write(in_pfx)
            try:
                outcome = TPMSmartCard.initCerts(cert_path, in_pass, self.csp_provider())
            except Exception as err:
                print("Import Cert Error:", err)
                outcome = ("Error: %s" % err, False)
        finally:
            # 无论导入成功与否都覆写销毁临时文件（内含私钥），避免残留
            try:
                with open(cert_path, 'wb') as save_file:
                    for i in range(0, len(in_pfx) // 16 + 1):
                        save_file.write(randbytes(16))
            except Exception as err:
                print("Clean Temp Cert Error:", err)
        self.main.load_status()
        return outcome

    def result_text(self, in_result):
        """把导入命令的结果整理成给用户看的结论文案。

        ``initCerts`` / ``loadCerts`` 返回 ``(输出文本, 是否成功)``：
        * 失败：前面标注「错误」，避免用户对着 certutil 原文自己猜；
        * 成功但带 CRYPT_E_EXISTS：证书此前已导入（certutil 只是跳过重复添加，
          退出码仍为 0），要明确说明而不是让用户以为导入失败；
        * 其余成功场景：原样展示命令输出（含「命令成功完成」）。
        """
        if not isinstance(in_result, tuple):
            return str(in_result)
        text, is_ok = in_result
        if not is_ok:
            return "%s：\n%s" % (self.main.i18n("fail"), text)
        if TPMSmartCard.CERT_EXISTS_CODE in text:
            return "%s\n%s" % (self.main.i18n("msg_import_exists"), text)
        return text

    @staticmethod
    def format_tips(in_template, in_data):
        """文案模板缺失 %s（如该语言无对应词条）时直接拼接，避免二次异常。"""
        try:
            return in_template % in_data
        except TypeError:
            return "%s\n%s" % (in_template, in_data)

    def fetch_cloud(self, in_url, in_data):
        """请求证书平台：统一加超时与异常兜底，失败返回 None。"""
        try:
            responded = requests.get(in_url, data=in_data, timeout=15)
        except Exception as err:
            print("Cloud Request Error:", err)
            messagebox.showwarning(self.main.i18n("fail"),
                                   self.format_tips(self.main.i18n("msg_cloud_net"), err))
            self.page.attributes('-topmost', True)
            return None
        if responded.status_code != 200:
            messagebox.showwarning(self.main.i18n("fail"), self.main.i18n("msg_cloud_err_code"))
            self.page.attributes('-topmost', True)
            return None
        try:
            return responded.json()
        except ValueError as err:
            print("Cloud Respond Error:", err)
            messagebox.showwarning(self.main.i18n("fail"), self.main.i18n("msg_cloud_data"))
            self.page.attributes('-topmost', True)
            return None

    def submit(self, ):
        self.page.attributes('-topmost', False)
        result = ""
        # 云端下发（仅 PFX 导入支持）=====================================================
        if self.flag == "pfx" and self.v_clouds.get():
            url = self.path_txt.get()
            # ---- 使用密码（取件码，自协商）：无需事先交换密钥 ----
            if self.v_cloud_pass.get():
                code = self.pass_txt.get().strip()
                responded_json = self.fetch_cloud(url, {"code": code, })
                if responded_json is None:
                    if not self.apps:
                        return False
                elif not ("flag" in responded_json and responded_json["flag"]):
                    messagebox.showwarning(
                        self.main.i18n("fail"),
                        responded_json.get("text") or self.main.i18n("msg_cloud_err_data"))
                    self.page.attributes('-topmost', True)
                    if not self.apps:
                        return False
                else:
                    try:
                        payload = responded_json["data"]
                        cipher_key = Crypto.code_key(
                            code,
                            base64.b64decode(payload["salt"]),
                            int(payload["iterations"])
                        )
                        plain = Crypto.aes_decrypt(
                            cipher_key,
                            base64.b64decode(payload["vaults"])
                        )
                        body = json.loads(plain.decode("utf-8"))
                        result = self.import_decrypted(
                            base64.b64decode(body["pfx"]),
                            body.get("pfxkey", "")
                        )
                    except Exception as import_err:
                        print("取件码解密失败：", import_err)
                        messagebox.showwarning(
                            self.main.i18n("fail"),
                            self.main.i18n("msg_code_invalid"))
                        self.page.attributes('-topmost', True)
                        if not self.apps:
                            return False
            # ---- 交换密钥（X25519 预协商）----
            else:
                pub = self.pass_txt.get()
                responded_json = self.fetch_cloud(url, {"pubkey": pub, })
                if responded_json is None:
                    if not self.apps:
                        return False
                elif not ("flag" in responded_json and responded_json["flag"]):
                    messagebox.showwarning(self.main.i18n("fail"), self.main.i18n("msg_cloud_err_data"))
                    self.page.attributes('-topmost', True)
                    if not self.apps:
                        return False
                else:
                    try:
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
                        # tmp = base64.b64encode(decrypted_data)
                        # tmp = tmp.decode()
                        # result = TPMSmartCard.baseCerts(tmp, responded_json['pfxkey'])
                        result = self.import_decrypted(
                            decrypted_data,
                            responded_json['pfxkey']
                        )
                    except Exception as import_err:
                        print("交换密钥解密失败：", import_err)
                        messagebox.showwarning(self.main.i18n("fail"),
                                               self.main.i18n("msg_cloud_data"))
                        self.page.attributes('-topmost', True)
                        if not self.apps:
                            return False
        # 本地导入 =======================================================================
        else:
            if not os.path.exists(self.path_txt.get()):
                messagebox.showwarning(self.main.i18n("fail"),
                                       self.main.i18n("msg_file_not_exist"))
                self.page.attributes('-topmost', True)
                if not self.apps:
                    return False
            else:
                self.page.attributes('-topmost', False)
                try:
                    if self.flag == "pfx":
                        result = TPMSmartCard.initCerts(
                            self.path_txt.get(), self.pass_txt.get(),
                            in_csp=self.csp_provider())
                    else:
                        result = TPMSmartCard.loadCerts(self.path_txt.get())
                except Exception as import_err:
                    print("Import Cert Error:", import_err)
                    result = ("Error: %s" % import_err, False)
                self.main.load_status()
                self.close()
        messagebox.showinfo(
            self.main.i18n("msg_import") + self.main.i18n("msg_cert") + self.main.i18n("msg_result"),
            self.result_text(result) + self.main.i18n("msg_import_results"))


if __name__ == "__main__":
    # 单独打包成 CertImport.exe 后可能从任意工作目录启动，先切回程序根目录
    Paths.ensure_workdir()
    apps = CertImport("pfx")
    apps.page.mainloop()
