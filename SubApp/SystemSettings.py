# -*- coding: utf-8 -*-
"""系统设置对话框：外观 / OpenSC / WinSSH 代理 / TPM 状态 / 关于与更新。

页签顺序：外观（主题 + 语言）在最前，关于与更新在最后。


* 「关于与更新」把工具信息与版本更新检查合并在一页（原独立的「关于本工具」
  「项目主页」按钮已合并到这里，统一指向 GitHub 项目主页）；
* 「外观」可切换界面主题（原版主题 / 美化配色，配置见 Config/themes.json）
  与界面语言，应用后由调用方重建主界面（``self.changed``）；
* 「OpenSC」「WinSSH 代理」把原来挂在工具条上的安装/启动操作收进设置
  （安装耗时，放在子线程执行，避免设置窗口卡死）；
* 「启动与托盘」管理本程序与 WinSSH 代理的开机自启（见 Module/AutoStart.py：
  需要提权的本程序注册成登录触发的计划任务，登录时不会弹 UAC）；
* 「版本更新」优先读取 GitHub Release API，被限流时回退到
  ``/releases/latest`` 的 302 跳转解析 Tag（不依赖 API 配额）。
"""

import json
import threading
import urllib.error
import urllib.request
import webbrowser

import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as ttk

from Module import AutoStart
from Module import Paths
from Module import Theme
from Module.I18n import get_i18n
from Module.TPMSmartCard import TPMSmartCard
from Module.Version import (AUTHOR, GITHUB_URL, LATEST_RELEASE_URL, LICENSE,
                            PRODUCT, RELEASE_API_URL, RELEASES_URL, USER_AGENT,
                            VERSION, compare_versions, normalize_tag)
from SubApp.MoreConfig import MoreConfig

# 联网检查更新的超时时间（秒）
TIMEOUT = 8

# TPM 状态展示的字段（Get-Tpm 字段名 -> 文案键）
TPM_FIELDS = [
    ("TpmPresent", "msg_set_tpm_present"),
    ("TpmReady", "msg_set_tpm_ready"),
    ("TpmEnabled", "msg_set_tpm_enabled"),
    ("TpmActivated", "msg_set_tpm_activated"),
    ("TpmOwned", "msg_set_tpm_owned"),
    ("ManufacturerId", "msg_set_tpm_manufacturer"),
    ("ManufacturerVersion", "msg_set_tpm_version"),
]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁止自动跟随跳转，用于从 302 的 Location 中取出最新版本号。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_of(url):
    return urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })


def fetch_latest_version(timeout=TIMEOUT):
    """获取 GitHub 上的最新版本号，返回 (版本号, 错误信息)。"""
    api_error = None
    # 方式一：GitHub Release API（共享出口 IP 容易被限流）
    try:
        with urllib.request.urlopen(request_of(RELEASE_API_URL), timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
        tag = data.get("tag_name") or data.get("name")
        if tag:
            return normalize_tag(tag), ""
    except Exception as err:
        api_error = err
    # 方式二：官方跳转地址，无 API 配额限制
    try:
        urllib.request.build_opener(NoRedirect).open(
            request_of(LATEST_RELEASE_URL), timeout=timeout)
    except urllib.error.HTTPError as err:
        location = (err.headers.get("Location") or "").rstrip("/")
        if location:
            return normalize_tag(location.rsplit("/", 1)[-1]), ""
        return "", str(err)
    except Exception as err:
        return "", str(err)
    return "", str(api_error)


def check_for_updates(timeout=TIMEOUT):
    """检查更新，返回 (状态, 最新版本, 错误信息)。

    状态：``new`` 有新版本、``latest`` 已是最新、``fail`` 检查失败。
    """
    latest, error = fetch_latest_version(timeout=timeout)
    if not latest:
        return "fail", "", error
    if compare_versions(latest, VERSION) > 0:
        return "new", latest, ""
    return "latest", latest, ""


class SystemSettings:
    """系统设置窗口；作为子窗口由主程序打开。"""

    def __init__(self, in_root, in_i18n=None, in_size=None):
        self.i18n = in_i18n or get_i18n()
        # 主题或语言是否发生变更（调用方据此决定是否重建主界面）
        self.changed = False
        self.alive = True
        # 版本更新检查
        self.checking = False
        self.check_result = None
        # TPM 状态
        self.tpm_values = dict()
        # 后台任务（安装 OpenSC / WinSSH 代理 / 注册自启计划任务）
        self.task_running = False
        self.task_ready = False
        self.task_finish = None
        self.task_result = None
        # OpenSC 安装结果：（是否成功, 退出码, 日志路径），由 worker_opensc 写入
        self.osc_result = None
        self.page = ttk.Toplevel(in_root)
        self.page.resizable(False, False)
        try:
            self.page.iconbitmap(Paths.resource("Config", "iconer", "icon02.ico"))
        except Exception:
            pass
        self.page.title("%s - %s" % (PRODUCT, self.t("msg_set_title")))
        width = 720 if self.i18n.is_wide() else 640
        # 长文案自动换行的宽度（窗口宽度去掉左右内边距）
        self.wrap = width - 90
        self.page.geometry("%dx%d" % (width, 400))
        if in_size is not None:
            self.page.geometry("+%d+%d" % (in_size[0], in_size[1]))
        self.page.protocol("WM_DELETE_WINDOW", self.close)
        # 页签（外观在最前、关于与更新在最后）====================================
        self.notebook = ttk.Notebook(self.page)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(12, 6))
        self.view_appearance(ttk.Frame(self.notebook, padding=16), self.t("msg_set_appearance"))
        self.view_startup(ttk.Frame(self.notebook, padding=16), self.t("msg_set_startup"))
        self.view_osc(ttk.Frame(self.notebook, padding=16), self.t("msg_set_osc"))
        self.view_ssh(ttk.Frame(self.notebook, padding=16), self.t("msg_set_ssh"))
        self.view_tpm(ttk.Frame(self.notebook, padding=16), self.t("msg_set_tpm"))
        self.view_about(ttk.Frame(self.notebook, padding=16), self.t("msg_set_about_update"))
        # 关闭按钮 ==============================================================
        ttk.Button(self.page, bootstyle="secondary", text=self.t("msg_set_close"),
                   command=self.close).pack(side=tk.RIGHT, padx=12, pady=(0, 12))
        # 页签内容（长语言的说明文本会折成多行）可能超出 400，按内容实测高度再定一次尺寸
        self.page.update_idletasks()
        self.page.geometry("%dx%d" % (width, min(max(400, self.page.winfo_reqheight()),
                                                 self.page.winfo_screenheight() - 80)))
        # 首次 TPM 检测放到窗口显示之后，避免打开设置时界面卡顿
        self.page.after(60, self.refresh_tpm)

    # 通用 =====================================================================
    def t(self, key, *args):
        if args:
            return self.i18n.tp(key, *args)
        return self.i18n.t(key)

    def close(self):
        """关闭窗口；同时取消 ttkbootstrap 的主题订阅。

        控件销毁后订阅不会自动移除，若不取消，之后切换主题时
        ttkbootstrap 刷新该控件会报 TclError（见 Module.Theme.unsubscribe）。
        """
        self.alive = False
        Theme.unsubscribe(self.page)
        try:
            self.page.destroy()
        except Exception:
            pass

    def open_url(self, url):
        webbrowser.open(url)

    def separator(self, page):
        ttk.Separator(page, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=14)
        return page

    # 页签：关于与更新 =========================================================
    def view_about(self, page, title):
        self.notebook.add(page, text=title)
        ttk.Label(page, bootstyle="info", text=PRODUCT).pack(anchor=tk.W, pady=(0, 10))
        for key, value in [("msg_set_version", "v%s" % VERSION),
                           ("msg_set_author", AUTHOR),
                           ("msg_set_license", LICENSE),
                           ("msg_set_url", GITHUB_URL.replace("https://", ""))]:
            ttk.Label(page, text="%s: %s" % (self.t(key), value)).pack(anchor=tk.W, pady=1)
        ttk.Button(page, bootstyle="primary-outline", text=self.t("msg_set_home"),
                   command=lambda: self.open_url(GITHUB_URL)).pack(anchor=tk.W, pady=(12, 0))
        self.separator(page)
        line = ttk.Frame(page)
        line.pack(anchor=tk.W)
        self.update_button = ttk.Button(line, bootstyle="primary",
                                        text=self.t("msg_set_check"), command=self.check_update)
        self.update_button.pack(side=tk.LEFT)
        self.download_button = ttk.Button(line, bootstyle="success", state=tk.DISABLED,
                                          text=self.t("msg_set_download"),
                                          command=lambda: self.open_url(RELEASES_URL))
        self.download_button.pack(side=tk.LEFT, padx=8)
        self.update_var = tk.StringVar()
        ttk.Label(page, textvariable=self.update_var, justify=tk.LEFT,
                  wraplength=self.wrap).pack(anchor=tk.W, pady=(12, 0))

    # 页签：外观（主题 + 语言） ===============================================
    def view_appearance(self, page, title):
        self.notebook.add(page, text=title)
        # 界面主题 -------------------------------------------------------------
        self.themes = Theme.available()
        self.theme_codes = [key for key, _ in self.themes]
        self.theme_names = [self.t(profile.get("name") or key) for key, profile in self.themes]
        ttk.Label(page, text=self.t("msg_set_theme")).pack(anchor=tk.W)
        self.theme_var = tk.StringVar()
        self.theme_box = ttk.Combobox(page, bootstyle="info", width=34, state="readonly",
                                      values=self.theme_names, textvariable=self.theme_var)
        self.theme_box.pack(anchor=tk.W, pady=(6, 0))
        current_theme = Theme.current_key()
        if current_theme in self.theme_codes:
            self.theme_box.current(self.theme_codes.index(current_theme))
        ttk.Label(page, bootstyle="secondary", justify=tk.LEFT, wraplength=self.wrap,
                  text=self.t("msg_set_theme_tip")).pack(anchor=tk.W, pady=(8, 0))
        self.separator(page)
        # 界面语言 -------------------------------------------------------------
        self.languages = self.i18n.available()
        self.language_codes = [code for code, _ in self.languages]
        self.language_names = ["%s (%s)" % (name, code) for code, name in self.languages]
        ttk.Label(page, text=self.t("msg_lang")).pack(anchor=tk.W)
        self.language_var = tk.StringVar()
        self.language_box = ttk.Combobox(page, bootstyle="info", width=34, state="readonly",
                                         values=self.language_names, textvariable=self.language_var)
        self.language_box.pack(anchor=tk.W, pady=(6, 0))
        if self.i18n.language in self.language_codes:
            self.language_box.current(self.language_codes.index(self.i18n.language))
        ttk.Label(page, bootstyle="secondary", justify=tk.LEFT, wraplength=self.wrap,
                  text=self.t("msg_lang_tip")).pack(anchor=tk.W, pady=(8, 0))
        ttk.Button(page, bootstyle="success", text=self.t("msg_lang_apply"),
                   command=self.apply_appearance).pack(anchor=tk.W, pady=(14, 0))

    def pick_theme(self):
        selected = self.theme_var.get()
        return self.theme_codes[self.theme_names.index(selected)] \
            if selected in self.theme_names else ""

    def pick_language(self):
        selected = self.language_var.get()
        return self.language_codes[self.language_names.index(selected)] \
            if selected in self.language_names else ""

    def apply_appearance(self):
        """应用主题与语言；两者都会触发主界面重建。"""
        theme_key = self.pick_theme()
        language = self.pick_language()
        if theme_key and theme_key != Theme.current_key():
            Theme.set_current(theme_key)
            self.changed = True
        if language and language != self.i18n.language:
            self.i18n.set_language(language)
            self.changed = True
        self.close()
        return None

    # 页签：启动与托盘 =========================================================
    def view_startup(self, page, title):
        """开机自启：本程序（登录后直接缩到托盘）与 WinSSH 代理。"""
        self.notebook.add(page, text=title)
        ttk.Label(page, bootstyle="secondary", justify=tk.LEFT, wraplength=self.wrap,
                  text=self.t("msg_set_startup_tip")).pack(anchor=tk.W)
        # 本程序自启 -----------------------------------------------------------
        self.appstart_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(page, text=self.t("msg_set_startup_app"),
                        variable=self.appstart_var,
                        command=self.toggle_app_startup).pack(anchor=tk.W, pady=(16, 0))
        self.appstart_state = tk.StringVar()
        ttk.Label(page, bootstyle="secondary", textvariable=self.appstart_state,
                  justify=tk.LEFT, wraplength=self.wrap).pack(anchor=tk.W, padx=26, pady=(2, 0))
        # WinSSH 代理自启 ------------------------------------------------------
        self.agent_path = MoreConfig.sshAgentPath()
        self.agentstart_var = tk.BooleanVar(value=False)
        self.agentstart_box = ttk.Checkbutton(page, text=self.t("msg_set_startup_agent"),
                                              variable=self.agentstart_var,
                                              command=self.toggle_agent_startup)
        self.agentstart_box.pack(anchor=tk.W, pady=(16, 0))
        self.agent_state = tk.StringVar()
        ttk.Label(page, bootstyle="secondary", textvariable=self.agent_state,
                  justify=tk.LEFT, wraplength=self.wrap).pack(anchor=tk.W, padx=26, pady=(2, 0))
        self.refresh_startup()

    def startup_state(self, in_entry):
        """自启状态文案：计划任务（登录不弹 UAC）/ 启动项（登录弹一次 UAC）/ 未启用。"""
        if in_entry.has_task():
            return self.t("msg_set_startup_task")
        if in_entry.run_value():
            return self.t("msg_set_startup_run")
        return self.t("msg_set_startup_off")

    def refresh_startup(self):
        """刷新两个自启开关；代理未随程序安装时禁用它的开关。"""
        entry = AutoStart.app_entry()
        self.appstart_var.set(entry.is_enabled())
        self.appstart_state.set(self.startup_state(entry))
        if not self.agent_path:
            self.agentstart_box.config(state=tk.DISABLED)
            self.agentstart_var.set(False)
            self.agent_state.set(self.t("msg_set_ssh_missing"))
            return None
        agent = AutoStart.agent_entry(self.agent_path)
        enabled = agent.is_enabled()
        self.agentstart_box.config(state=tk.NORMAL)
        self.agentstart_var.set(enabled)
        self.agent_state.set(self.t("msg_set_startup_on") if enabled
                             else self.t("msg_set_startup_off"))
        return None

    def toggle_app_startup(self):
        """开关本程序自启；注册计划任务要起 PowerShell，放到子线程里执行。"""
        entry = AutoStart.app_entry()
        if not self.appstart_var.get():
            entry.disable()
            self.refresh_startup()
            return None
        self.task_result = None
        if self.run_task(entry.enable, self.after_app_startup):
            self.appstart_state.set(self.t("msg_set_installing"))
        return None

    def after_app_startup(self):
        """自启注册结束：失败时明确提示，成功/失败都重新读一次真实状态。"""
        if not self.task_result:
            messagebox.showwarning(self.t("msg_set_title"), self.t("msg_set_startup_fail"))
        self.refresh_startup()
        return None

    def toggle_agent_startup(self):
        """开关 WinSSH 代理自启（写 HKCU 启动项，代理本身不需要提权）。"""
        if not self.agent_path:
            self.refresh_startup()
            return None
        agent = AutoStart.agent_entry(self.agent_path)
        if self.agentstart_var.get():
            if not agent.enable():
                messagebox.showwarning(self.t("msg_set_title"), self.t("msg_set_startup_fail"))
        else:
            agent.disable()
        self.refresh_startup()
        return None

    # 后台任务（安装耗时，放到子线程，结束后回主线程刷新）======================
    def run_task(self, in_worker, in_finish):
        """执行耗时安装操作；已有任务在跑时直接忽略。"""
        if self.task_running:
            return False
        self.task_running = True
        self.task_ready = False
        self.task_finish = in_finish
        threading.Thread(target=self.worker_task, args=(in_worker,), daemon=True).start()
        self.page.after(300, self.poll_task)
        return True

    def worker_task(self, in_worker):
        try:
            in_worker()
        except Exception as err:
            print("Settings Task Error:", err)
        finally:
            self.task_ready = True

    def poll_task(self):
        if not self.alive:
            return None
        if not self.task_ready:
            self.page.after(300, self.poll_task)
            return None
        self.task_running = False
        finish, self.task_finish = self.task_finish, None
        if finish is not None:
            finish()
        return None

    # 页签：OpenSC =============================================================
    def view_osc(self, page, title):
        self.notebook.add(page, text=title)
        self.osc_var = tk.StringVar()
        ttk.Label(page, justify=tk.LEFT, wraplength=self.wrap,
                  textvariable=self.osc_var).pack(anchor=tk.W)
        line = ttk.Frame(page)
        line.pack(anchor=tk.W, pady=(14, 0))
        ttk.Button(line, bootstyle="primary", text=self.t("msg_set_osc_install"),
                   command=self.install_opensc).pack(side=tk.LEFT)
        ttk.Button(line, bootstyle="info-outline", text=self.t("msg_set_tpm_refresh"),
                   command=self.refresh_osc).pack(side=tk.LEFT, padx=8)
        ttk.Label(page, bootstyle="secondary", justify=tk.LEFT, wraplength=self.wrap,
                  text=self.t("msg_set_osc_tip")).pack(anchor=tk.W, pady=(14, 0))
        self.refresh_osc()

    def refresh_osc(self):
        """展示 OpenSC 的安装状态。"""
        path_now = MoreConfig.openscPath()
        self.osc_var.set(self.t("msg_set_osc_on", path_now) if path_now
                         else self.t("msg_set_osc_off"))
        return path_now

    def install_opensc(self):
        """安装随程序分发的 OpenSC（静默安装，需要管理员权限）。"""
        self.osc_result = None
        if self.run_task(self.worker_opensc, self.finish_opensc):
            self.osc_var.set(self.t("msg_set_installing"))
        return None

    def worker_opensc(self):
        """在子线程里安装（安装耗时，不能让设置窗口卡死）。"""
        self.osc_result = MoreConfig.installOpenSC()
        return self.osc_result

    def finish_opensc(self):
        """刷新状态；失败时把退出码、原因与日志路径告诉用户。"""
        ok, code, log_path = self.osc_result or (False, MoreConfig.MSI_NO_START, "")
        self.refresh_osc()
        if not ok:
            messagebox.showerror(self.t("msg_set_osc"),
                                 MoreConfig.installFailText(self.i18n, code, log_path))
        return None

    # 页签：WinSSH 代理 ========================================================
    def view_ssh(self, page, title):
        self.notebook.add(page, text=title)
        ttk.Label(page, bootstyle="secondary", justify=tk.LEFT, wraplength=self.wrap,
                  text=self.t("msg_set_ssh_tip")).pack(anchor=tk.W)
        line = ttk.Frame(page)
        line.pack(anchor=tk.W, pady=(14, 0))
        ttk.Button(line, bootstyle="primary", text=self.t("msg_set_ssh_install"),
                   command=self.install_ssh).pack(side=tk.LEFT)
        ttk.Button(line, bootstyle="primary-outline", text=self.t("msg_set_ssh_start"),
                   command=self.start_ssh).pack(side=tk.LEFT, padx=8)
        self.ssh_var = tk.StringVar()
        ttk.Label(page, justify=tk.LEFT, wraplength=self.wrap,
                  textvariable=self.ssh_var).pack(anchor=tk.W, pady=(14, 0))
        self.show_ssh()

    def show_ssh(self):
        """展示随程序分发的 SSH 代理路径；文件缺失时给出提示。"""
        agent_path = MoreConfig.sshAgentPath()
        self.ssh_var.set(agent_path if agent_path else self.t("msg_set_ssh_missing"))
        return agent_path

    def install_ssh(self):
        """通过 Chocolatey 安装 WinSSH 代理并启动。"""
        if self.run_task(MoreConfig.setupSSH, self.show_ssh):
            self.ssh_var.set(self.t("msg_set_installing"))
        return None

    def start_ssh(self):
        if not MoreConfig.startSSH():
            messagebox.showwarning(self.t("msg_set_title"), self.t("msg_set_ssh_missing"))
        return None

    # 页签：TPM 状态 ===========================================================
    def view_tpm(self, page, title):
        self.notebook.add(page, text=title)
        ttk.Button(page, bootstyle="info", text=self.t("msg_set_tpm_refresh"),
                   command=self.refresh_tpm).grid(column=0, row=0, columnspan=2, sticky=tk.W)
        row = 1
        for field, text_key in TPM_FIELDS:
            ttk.Label(page, text="%s:" % self.t(text_key)).grid(column=0, row=row,
                                                               sticky=tk.W, pady=2)
            value = ttk.Label(page, text=self.t("msg_na"))
            value.grid(column=1, row=row, sticky=tk.W, padx=10, pady=2)
            self.tpm_values[field] = value
            row += 1
        self.tpm_tip_var = tk.StringVar()
        ttk.Label(page, textvariable=self.tpm_tip_var, justify=tk.LEFT,
                  wraplength=self.wrap).grid(column=0, row=row, columnspan=2, sticky=tk.W, pady=(12, 0))
        page.columnconfigure(1, weight=1)

    def refresh_tpm(self):
        """读取并展示 TPM 详细状态（状态未知时给出权限提示）。"""
        if not self.alive:
            return -1
        status, fields, _ = TPMSmartCard.tpmStatus()
        if not self.alive:
            return status
        for field, value in self.tpm_values.items():
            value.config(text=self.format_tpm(field, fields.get(field)))
        if status == -1:
            self.tpm_tip_var.set("%s\n%s" % (self.t("msg_set_tpm_fail"), self.t("msg_set_tpm_note")))
        else:
            self.tpm_tip_var.set(self.t("msg_set_tpm_note"))
        return status

    def format_tpm(self, field, value):
        if value is None or str(value).strip() == "":
            return self.t("msg_na")
        text = str(value).strip()
        if text.lower() in ("true", "false"):
            return "✅" if text.lower() == "true" else "❌"
        if field == "ManufacturerId":
            return SystemSettings.decode_manufacturer(text)
        return text

    @staticmethod
    def decode_manufacturer(text):
        """把 Get-Tpm 的十六进制厂商编号还原为可读文本（49465800 -> IFX）。"""
        try:
            name = bytes.fromhex(text).decode("ascii", "ignore").strip("\x00 \t\r\n")
            if name:
                return "%s (%s)" % (name, text)
        except Exception:
            pass
        return text

    # 版本更新 =================================================================
    def check_update(self):
        if self.checking:
            return None
        self.checking = True
        self.check_result = None
        self.update_button.config(state=tk.DISABLED)
        self.download_button.config(state=tk.DISABLED)
        self.update_var.set(self.t("msg_set_checking"))
        # 网络请求放到子线程，避免界面卡住
        threading.Thread(target=self.worker_update, daemon=True).start()
        self.page.after(200, self.poll_update)
        return None

    def worker_update(self):
        self.check_result = check_for_updates()

    def poll_update(self):
        if not self.alive:
            return None
        if self.check_result is None:
            self.page.after(200, self.poll_update)
            return None
        status, latest, error = self.check_result
        self.check_result = None
        self.checking = False
        self.update_button.config(state=tk.NORMAL)
        if status == "new":
            self.update_var.set(self.t("msg_set_new", latest, VERSION))
            self.download_button.config(state=tk.NORMAL)
        elif status == "latest":
            self.update_var.set(self.t("msg_set_latest", latest))
        else:
            self.update_var.set(self.t("msg_set_fail", error))
        return None


if __name__ == "__main__":
    # 单独运行（开发调试）：只显示设置对话框
    root = ttk.Window(title=PRODUCT)
    root.withdraw()
    SystemSettings(root).page.wait_window()
