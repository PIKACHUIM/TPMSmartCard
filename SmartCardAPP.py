import hashlib
import os
import json
import re
import sys
import time
import random
import tkinter
import traceback
import unicodedata
from random import randint

import base64
import pyglet

from datetime import datetime, timedelta
import subprocess
import pyperclip
import threading

import requests
from cryptography.hazmat.primitives import serialization
from flask import request
from ttkbootstrap import *
import ttkbootstrap as ttk
from functools import partial
from tkinter import messagebox, filedialog, font
import tkinter.ttk as ttk_plain
from Module.SmartCardAPI import SmartCardAPI
from Module.I18n import get_i18n
from Module.Paths import ensure_workdir, resource
from Module.TPMSmartCard import TPMSmartCard
from Module import Theme
from Module import TPMBackup
from Module.TrayIcon import TrayIcon
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from SubApp.CertImport import CertImport
from SubApp.MoreConfig import MoreConfig
from SubApp.SystemSettings import SystemSettings

# 界面默认字体；语言包里的 _font 可为特定语言覆盖（如韩语需要 Hangul 字体）
FONT_NAME_DEFAULT = "MapleMono SC NF"

# 登录自启的启动参数（见 Module/AutoStart.py）：带它就只常驻托盘，不显示主窗口
TRAY_FLAG = "--minimized"

# 界面主题与配色来自 Config/themes.json（可在「系统设置 - 外观」里切换），
# 下面的常量是配置缺省或读取失败时的兜底值
THEME_NAME = os.environ.get("TPMSMART_THEME") or "yeti"
COLOR_HEAD_BG = "#eef2f7"      # 表格表头背景
COLOR_HEAD_FG = "#3c4a5a"      # 表格表头文字
COLOR_MUTED = "#66788a"        # 分组框标题等次要文字
TABLE_ROW_HEIGHT = 20          # 表格行高兜底值（正常由主题决定，此处仅探测失败时使用）
TABLE_HEAD_HEIGHT = 29         # 表格表头高度兜底值
HEAD_PADDING = (6, 2)          # 表格表头内边距（收紧后表格整体高度更小）
TABLE_BAR_WIDTH = 12           # 表格滚动条宽度
FRAME_STYLE = "secondary"      # 分组框风格兜底值
TABLE_STYLE = "secondary"      # 表格风格兜底值
MIN_BUTTON_WIDTH = 56          # 按钮最小宽度
BUTTON_PADDING_FALLBACK = 30   # 量不出控件尺寸时，文案宽度需额外预留的内边距
# 原版主题：按钮使用的系统配色（ttkbootstrap 会给 Tk 控件自动上主题色）
NATIVE_COLOR_BG = "SystemButtonFace"
NATIVE_COLOR_FG = "SystemWindowText"
NATIVE_COLOR_DIS = "SystemGrayText"
# 原版主题下各控件使用的 ttk 默认样式名（避免被 ttkbootstrap 接管配色）
NATIVE_STYLES = {
    "Button": "TButton",
    "Label": "TLabel",
    "LabelFrame": "TLabelframe",
    "Treeview": "Treeview",
    "Scrollbar": "Vertical.TScrollbar",
    "Entry": "TEntry",
    "Combobox": "TCombobox",
    "Checkbutton": "TCheckbutton",
}
LABEL_WIDTH = 60               # 详情标签列宽度
LABEL_GAP = 5                  # 标签与取值之间的间距
LABEL_ROW_HEIGHT = 20          # 详情标签行高

# 还原结果弹窗最多展示多少字符：完整日志同时落盘到文件，弹窗只保证可读
RESTORE_DIALOG_LIMIT = 7000


def fit_dialog_text(text, limit=RESTORE_DIALOG_LIMIT):
    """裁剪过长的提示文本：Tk 消息框在超长文本下排版很差，超出部分给出日志文件提示。"""
    text = str(text or "")
    if len(text) <= limit:
        return text
    return "%s\n\n…（日志过长已截断，完整内容见上面的日志文件路径）" % text[:limit]


class SmartCardAPP:
    def __init__(self):
        self.root = tk.Tk()
        # 登录自启（--minimized）时不显示主窗口，直接常驻托盘
        self.startup_hidden = self.has_flag(TRAY_FLAG)
        self.tray = None
        self.tray_hinted = False
        self.checked = False
        # 主窗口是否已经真正显示过 / 是否被用户主动收进托盘（见 on_unmap / ensure_visible）
        self.window_shown = False
        self.window_hidden = False
        self.conf = dict()
        self.read_config()
        # 界面语言：用户设置 > TPMSMART_LANG > 系统语言 > 默认（语言包见 Config/locales）
        self.i18n_data = get_i18n()
        self.lang = self.i18n_data.language
        # 设置主窗口宽度和高度
        self.root.geometry("1080x540")
        self.root.iconbitmap(resource("Config", "iconer", "icon02.ico"))
        self.size = self.get_screens()
        self.root.geometry(f"+{self.size[0]}+{self.size[1]}")
        if self.startup_hidden:
            # 先藏起来，避免启动过程闪一下窗口（随后只留托盘图标）
            self.root.withdraw()
        self.data = SmartCardAPI()
        self.tpms = TPMSmartCard()
        pyglet.font.add_file(resource("Config", "myfont", "MapleMono-SC-NF-Regular.ttf"))
        pyglet.font.add_file(resource("Config", "myfont", "NotoSerifCJKsc-Regular.otf"))
        self.pick = {
            "card": "",
            "cert": ""
        }
        self.setup_fonts()
        self.build_ui()
        # 托盘先建好：后面的启动检查、状态刷新如果弹框，用户也能从托盘找回窗口
        self.setup_tray()
        if not self.startup_hidden:
            self.check_datas()
        self.load_status()
        # 双击 .tsb（文件类型关联）时由启动参数直接进入还原流程
        self.open_backup()
        self.root.mainloop()

    def open_backup(self):
        """把命令行里的 .tsb 备份文件路径送进还原流程（双击关联文件时触发）。"""
        if len(sys.argv) < 2:
            return None
        package = str(sys.argv[1]).strip('"')
        if not package.lower().endswith(TPMBackup.BACKUP_SUFFIX):
            return None
        if not os.path.isfile(package):
            return None
        if self.startup_hidden:
            # 带着备份文件启动时必须看得见界面，不能把窗口留在托盘里
            self.show_window()
        # 等主窗口建好、首次状态刷新完成后再弹还原确认框
        self.root.after(300, lambda: self.card_restore(package))
        return None

    @staticmethod
    def has_flag(in_flag):
        """命令行里是否带指定开关（登录自启由 Module/AutoStart.py 传 --minimized）。"""
        return any(str(arg).strip().lower() == in_flag for arg in sys.argv[1:])

    # 托盘常驻 ================================================================
    @property
    def tray_ready(self):
        """托盘是否可用；不可用时不拦截关闭，否则窗口关不掉、程序也退不出。"""
        return self.tray is not None and self.tray.is_alive

    def setup_tray(self):
        """建立托盘图标：关闭/最小化到托盘，右键菜单「显示主程序 / 退出」。"""
        if self.tray is not None:
            return self.tray
        self.tray = TrayIcon(self.root,
                             resource("Config", "iconer", "icon02.ico"),
                             self.i18n("main_text"),
                             self.i18n("msg_tray_show"),
                             self.i18n("msg_tray_exit"),
                             self.show_window, self.quit_app)
        if not self.tray.start():
            print("SmartCardAPP: 托盘图标不可用：%s" % self.tray.error)
            self.tray = None
            return None
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.bind("<Map>", self.on_map)
        self.root.bind("<Unmap>", self.on_unmap)
        # 启动后兜底一次：正常启动却没显示出主窗口时把它拉回来
        self.root.after(1500, self.ensure_visible)
        return self.tray

    def on_map(self, in_event=None):
        """记录主窗口已经真正显示过（用来区分启动时序与用户点最小化）。"""
        if in_event is None or in_event.widget is self.root:
            if self.root.winfo_viewable():
                self.window_shown = True
        return None

    def on_unmap(self, in_event=None):
        """点最小化（主窗口进入 iconic）时收进托盘。

        窗口真正显示过之后才认这个动作：Tk 建顶层窗口的过程中状态可能短暂变成
        iconic，若跟着收进托盘，用户看到的就是「启动后没有窗口」。
        另外子控件取消映射也会触发 <Unmap>，所以还要看主窗口自己的状态；
        自己调用 withdraw() 时状态是 withdrawn，也不会反复触发。
        """
        if not self.tray_ready or not self.window_shown:
            return None
        try:
            if self.root.state() == "iconic":
                self.hide_window()
        except tk.TclError:
            pass
        return None

    def ensure_visible(self):
        """兜底：正常启动（非登录自启）却没显示出主窗口时，把它拉回前台。

        只在启动阶段做一次；用户之后自己收进托盘不会被再拉出来。
        """
        if self.startup_hidden or self.window_hidden or self.window_shown:
            return None
        print("SmartCardAPP: 启动后主窗口未显示，主动恢复显示")
        self.show_window()
        return None

    def hide_window(self):
        """隐藏主窗口到托盘；首次隐藏用气泡提示怎么找回、怎么退出。"""
        if not self.tray_ready:
            # 托盘不可用时不能把窗口藏起来（否则找不回、也退不出），直接退出
            self.quit_app()
            return None
        self.window_hidden = True
        self.root.withdraw()
        if not self.tray_hinted:
            self.tray_hinted = True
            self.tray.notify(self.i18n("main_text"), self.i18n("msg_tray_hidden"))
        return None

    def show_window(self):
        """从托盘恢复主窗口（登录自启时跳过的启动检查在这里补一次）。"""
        self.window_shown = True
        self.window_hidden = False
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass
        if not self.checked:
            self.check_datas()
        return None

    def quit_app(self):
        """退出程序：先摘掉托盘图标，再销毁主窗口（mainloop 随之结束）。"""
        if self.tray is not None:
            self.tray.stop()
            self.tray = None
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        return None

    def setup_fonts(self, in_create=True):
        """按当前语言与主题准备字体/配色；切换语言或主题后重新调用即可生效。"""
        font_name = self.i18n_data.font(FONT_NAME_DEFAULT)
        if not in_create and self.t_fonts:
            for tag in self.t_fonts.values():
                tag.configure(family=font_name)
        else:
            self.t_fonts = {
                "label_data": font.Font(family=font_name,
                                        size=-12),
                "label_name": font.Font(family=font_name,
                                        size=-12, weight="bold")
            }
        self.setup_theme()
        return None

    def setup_theme(self):
        """应用当前主题：「原版」（系统默认主题）或美化配色（见 Config/themes.json）。"""
        self.theme = Theme.current()
        self.frame_style = self.theme.get("frame") or ""
        self.table_style = self.theme.get("table") or ""
        self.style = ttk.Style()
        if self.native:
            # 原版主题：直接切到系统默认的 ttk 主题（Windows 下即默认蓝灰）
            plain = ttk_plain.Style()
            for theme_name in (self.theme.get("theme"), "vista", "winnative", "default"):
                if not theme_name:
                    continue
                try:
                    plain.theme_use(theme_name)
                    break
                except Exception:
                    continue
        else:
            # ttkbootstrap 的 Style 是单例，构造参数只在首次生效，
            # 切换主题必须显式调用 theme_use
            theme_now = self.theme.get("theme") or THEME_NAME
            try:
                self.style.theme_use(theme_now)
            except Exception as err:
                # theme_use 会刷新所有已创建控件；若其中某个控件（如刚关闭的
                # 对话框里的下拉框）已销毁就会抛 TclError，此时主题已切换成功，
                # 且界面马上就要重建，忽略即可
                print("Theme: 忽略刷新已销毁控件时的异常:", err)
        self.apply_style()
        return self.style

    @property
    def native(self):
        """当前是否为「原版」主题（系统默认主题，控件不做任何美化）。"""
        return bool(self.theme.get("native"))

    def new_widget(self, in_name, in_bootstyle=None, in_master=None, **kwargs):
        """创建控件。

        原版主题使用系统默认外观：ttkbootstrap 会接管所有 ttk 控件并套用
        自己的配色，因此这里把控件样式直接指回 ttk 的默认样式
        （走 Tcl 层，绕过 ttkbootstrap 的接管）。
        """
        master = self.root if in_master is None else in_master
        if not self.native:
            widget_cls = getattr(ttk, in_name)
            if not in_bootstyle:
                return widget_cls(master, **kwargs)
            return widget_cls(master, bootstyle=in_bootstyle, **kwargs)
        if in_name == "Button":
            # 原版主题：按钮用原生 Tk 控件，并显式套用系统配色
            # （ttkbootstrap 会给 Tk 控件自动上主题色，这里必须覆盖掉）
            button = tk.Button(master, **kwargs)
            button.configure(background=NATIVE_COLOR_BG, foreground=NATIVE_COLOR_FG,
                             activebackground=NATIVE_COLOR_BG,
                             activeforeground=NATIVE_COLOR_FG,
                             disabledforeground=NATIVE_COLOR_DIS,
                             relief="raised", borderwidth=1)
            return button
        widget = getattr(ttk_plain, in_name)(master, **kwargs)
        style_name = NATIVE_STYLES.get(in_name)
        if style_name:
            try:
                widget.tk.call(str(widget), "configure", "-style", style_name)
            except Exception as err:
                print("Theme: 设置系统默认样式失败:", err)
        return widget

    def apply_style(self):
        """统一字体；配色只由主题决定（原版主题完全交给系统默认样式）。"""
        style = self.style
        if not self.native:
            style.configure("Treeview.Heading", font=self.t_fonts['label_name'])
            style.configure("Treeview", font=self.t_fonts['label_data'])
            style.configure("TLabel", font=self.t_fonts['label_name'])
            style.configure("TCheckbutton", font=self.t_fonts['label_name'])
        if self.native:
            # 原版主题也收紧表头内边距，两个主题的表格高度才接近
            style.configure("Treeview.Heading", padding=HEAD_PADDING)
            # 原版主题：ttkbootstrap 会把美化主题的文字色残留在样式里
            # （浅色文字配系统默认的浅色底会看不见），统一改回系统文字色。
            # 弹窗（系统设置等）用的是各配色按钮，这里一并覆盖。
            text_color = "SystemWindowText"
            for style_name in ("TButton", "TLabel", "TCheckbutton", "TRadiobutton",
                               "Treeview", "Treeview.Heading", "TLabelframe.Label",
                               "TEntry", "TCombobox", "TNotebook.Tab"):
                style.configure(style_name, foreground=text_color)
            for color in ("primary", "secondary", "success", "info", "warning",
                          "danger", "light", "dark"):
                for suffix in ("", "-outline", "-link"):
                    style.configure("%s%s.TButton" % (color, suffix),
                                    foreground=text_color)
            for style_name in self.button_style_names():
                style.configure("%s.TButton" % style_name, foreground=text_color)
            return None
        style.configure("Treeview.Heading", padding=HEAD_PADDING)
        if self.theme.get("flat_heading"):
            # 美化主题：表头固定为中性灰阶，避免主题自带的高饱和色块
            head_bg = self.theme.get("head_bg") or COLOR_HEAD_BG
            head_fg = self.theme.get("head_fg") or COLOR_HEAD_FG
            style.configure("Treeview.Heading",
                            background=head_bg,
                            foreground=head_fg,
                            relief="flat",
                            borderwidth=0)
            style.map("Treeview.Heading",
                      background=[("active", head_bg)])
            style.configure("TLabelframe.Label",
                            foreground=self.theme.get("muted") or COLOR_MUTED)
        style.configure("TLabelframe.Label", font=self.t_fonts['label_name'])
        return None

    def close_dialog(self, in_window):
        """关闭子窗口：先取消其中控件的主题订阅，再销毁窗口。

        ttkbootstrap 创建控件时会登记到主题频道（Publisher）上，Toplevel 本身与
        下拉框（Combobox）也在其中；控件销毁后订阅不会自动移除，之后再切换主题
        时 ttkbootstrap 会去刷新这些已销毁的控件并报 TclError
        （``bad window path name "..."``，见 Module.Theme.unsubscribe）。
        """
        Theme.unsubscribe(in_window)
        try:
            in_window.destroy()
        except Exception:
            pass
        return None

    def build_ui(self):
        """构建主界面控件；切换语言后重新调用即可按新语言重建全部文案。"""
        self.root.title(self.i18n("main_text"))
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
            # 点表格空白处取消选中（详情与按钮状态随之复位）
            self.tables["card_main"][0].bind('<Button-1>',
                                             partial(self.table_blank_click, "card_main"))
        if self.tables["cert_main"][0] is not None:
            self.tables["cert_main"][0].bind('<<TreeviewSelect>>', self.cert_select)
            self.tables["cert_main"][0].bind('<Button-1>',
                                            partial(self.table_blank_click, "cert_main"))
        self.button = {
            "card_main": self.view_button("card_main"),
            "cert_main": self.view_button("cert_main"),
            "main_main": self.view_button("main_main"),
            "card_opts": self.view_button("card_opts"),
        }

        self.labels = {
            "card_info": self.view_labels("card_info"),
            "cert_info": self.view_labels("cert_info"),
            "cert_user": self.view_labels("cert_user"),
            "cert_last": self.view_labels("cert_last"),
        }
        # 按钮行在两块之间垂直居中，保证按钮上下间距一致
        self.align_button_rows()
        # 详情区未选中卡片/证书时显示的居中提示
        # （使用者/颁发者未选中证书时也保留分组框，框内显示同一提示，不再整块消失）
        self.hints = {
            "card_info": self.view_hint("card_info", "msg_hint_card"),
            "cert_info": self.view_hint("cert_info", "msg_hint_cert"),
            "cert_user": self.view_hint("cert_user", "msg_hint_cert"),
            "cert_last": self.view_hint("cert_last", "msg_hint_cert"),
        }
        # 构建阶段就把详情字段收起来：未选中卡片/证书时应当直接显示「选择…查看详情」，
        # 否则启动时（读卡数据完成前，例如 TPM 提示框弹出期间窗口已被绘制）
        # 会先闪出一屏只有字段名、没有内容的空详情
        for label_group in self.labels:
            self.toggle_labels(label_group, False)

        self.button["card_main"]["pin"].config(state=tk.DISABLED)
        self.button["card_main"]["puk"].config(state=tk.DISABLED)
        self.button["card_opts"]["del"].config(state=tk.DISABLED)
        self.button["card_opts"]["bak"].config(state=tk.DISABLED)
        self.button["cert_main"]["sys"].config(state=tk.DISABLED)
        self.button["cert_main"]["out"].config(state=tk.DISABLED)
        self.button["cert_main"]["non"].config(state=tk.DISABLED)

    def i18n(self, in_name):
        """界面文案翻译；多级回退顺序由 Module.I18n 决定，缺词条时返回键名。"""
        return self.i18n_data.t(in_name)

    @property
    def wide(self):
        """当前语言是否需要更宽的行控件（子窗口按此调整窗口宽度）。

        与 Module.AppConfigure.wide 同一语义：CertImport 等子窗口既可由主程序
        打开（传入 self），也可单独运行（自带 AppConfigure），两边都要有这个属性。
        """
        return self.i18n_data.is_wide()

    def card_settings(self):
        """系统设置：关于本工具 / 版本更新 / 界面语言 / TPM 状态。

        其中切换界面语言后需要重建主界面（其余设置项不影响主界面）。
        """
        dialog = SystemSettings(self.root, self.i18n_data, self.size)
        self.root.wait_window(dialog.page)
        if dialog.changed:
            # 当前回调所在的按钮即将被销毁，等事件循环转一圈再重建
            self.root.after(0, self.rebuild_ui)

    def rebuild_ui(self):
        """切换语言后重建全部控件（数据与选中状态由 load_status 重新加载）。"""
        for child in list(self.root.winfo_children()):
            # 销毁前先取消主题订阅，否则紧接着的 setup_theme 会刷新这些已销毁控件
            Theme.unsubscribe(child)
            child.destroy()
        self.lang = self.i18n_data.language
        self.pick = {
            "card": "",
            "cert": ""
        }
        self.setup_fonts(in_create=False)
        self.build_ui()
        if self.tray is not None:
            # 托盘提示与右键菜单文案同样跟随界面语言
            self.tray.set_texts(self.i18n("main_text"), self.i18n("msg_tray_show"),
                                self.i18n("msg_tray_exit"))
        self.load_status()

    def check_datas(self):
        # 启动检查只做一次：登录自启时跳过，第一次从托盘打开窗口时补做
        self.checked = True
        # TPM --------------------------------------------------------------------------------
        tpm_status = self.check_tpm_h(out=False)
        if tpm_status == 1:
            messagebox.showerror(
                self.i18n("msg_cert_out_ft_item"),
                self.i18n("msg_tpm_check_fail") % self.i18n("msg_tpm_none_act")
            )
        elif tpm_status != 0:
            # 状态未知（如未以管理员权限运行）时用警告提示，不再是红色报错
            messagebox.showwarning(
                self.i18n("msg_cert_out_ft_item"),
                self.i18n("msg_tpm_check_none") % self.i18n("msg_tpm_unknown")
            )
        # OpenSC -----------------------------------------------------------------------------
        if not MoreConfig.openscPath():
            if messagebox.askquestion(self.i18n("sc_title"), self.i18n("sc_datas")) == 'yes':
                self.install_osc()
                self.restart_app()

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
        # 界面文案已独立到 Config/locales，这里的配置只负责布局与表格列
        # 路径按程序根目录解析：双击 .tsb 关联文件、登录自启时工作目录不是程序目录
        for conf_name in ["tables", "frames", "button",
                          "labels", "cncode"]:
            with open(resource("Config", "%s.json" % conf_name), "r",
                      encoding="utf8") as conf_file:
                conf_data = conf_file.read()
                self.conf[conf_name] = json.loads(conf_data)

    def load_status(self):
        self.data.readInfo()
        # 表格整体重建，之前的选中行会丢失：记下原选中的卡片，重建后尽量恢复
        keep_card = self.pick.get("card") or ""
        if keep_card not in self.data.cards:
            keep_card = ""
        self.pick["card"] = ""
        self.pick["cert"] = ""
        self.button["card_opts"]["del"].config(state=tk.DISABLED)
        self.button["cert_main"]["non"].config(state=tk.DISABLED)
        self.button["card_main"]["pin"].config(state=tk.DISABLED)
        self.button["card_main"]["puk"].config(state=tk.DISABLED)
        self.button["cert_main"]["sys"].config(state=tk.DISABLED)
        self.button["cert_main"]["out"].config(state=tk.DISABLED)
        self.button["card_opts"]["bak"].config(state=tk.DISABLED)
        self.tables["card_main"][0].delete(*self.tables["card_main"][0].get_children())
        self.tables["cert_main"][0].delete(*self.tables["cert_main"][0].get_children())
        for item_name in ["card_info", "cert_info", "cert_user", "cert_last"]:
            for fill_name in self.labels[item_name]:
                self.labels[item_name][fill_name][1].config(text="")
        # 还没选卡片/证书：详情区只留一行提示，标签整体不显示
        for hint_name in ["card_info", "cert_info", "cert_user", "cert_last"]:
            self.toggle_labels(hint_name, False)
        for card_now in self.data.cards:
            if "card_main" in self.tables:
                self.tables["card_main"][0].insert("", tk.END, values=(
                    self.data.cards[card_now].card_id,
                    card_now,
                    self.data.cards[card_now].sc_uuid[:16]))

        # 证书列表与卡片绑定：未选卡时不显示属于某张卡的证书
        self.fill_cert_table()
        if keep_card:
            # 恢复原来的选卡（重新选中该行会触发 card_select，证书列表随之刷新）
            self.select_table_row("card_main", "#2", keep_card)

    def select_table_row(self, in_name, in_column, in_value):
        """在表格里按列值选中一行（找不到就不动），用于刷新后恢复选中状态。"""
        table = (self.tables.get(in_name) or (None, None))[0]
        if table is None or not in_value:
            return None
        for item in table.get_children():
            if table.set(item, in_column) == in_value:
                table.selection_set(item)
                table.focus(item)
                table.see(item)
                return item
        return None

    def card_certs(self):
        """当前该显示的证书：证书绑定到解析时所在的读卡器（``SmartCardCer.sc_card``）。

        选中卡片时只显示该卡的证书（先选卡才能管理该卡上的证书）；
        未选卡时只显示『归属不到任何卡片』的证书（如物理卡读卡器、旧 certutil
        解析路径），否则这些证书会因为选不到对应卡片而彻底看不到。
        """
        picked = self.pick.get("card") or ""
        if picked:
            return {name: cert for name, cert in self.data.certs.items()
                    if getattr(cert, "sc_card", None) == picked}
        return {name: cert for name, cert in self.data.certs.items()
                if getattr(cert, "sc_card", None) not in self.data.cards}

    def fill_cert_table(self):
        """按当前选中的卡片重建证书表格（证书列表随选卡变化）。"""
        table = (self.tables.get("cert_main") or (None, None))[0]
        if table is None:
            return None
        table.delete(*table.get_children())
        # 列表内容可能整体变了，之前的证书选中状态与详情一并复位
        self.clear_cert_pick()
        for cert_now, cert_data in self.card_certs().items():
            if len(cert_now.split(' ')) > 1:
                cert_name = " ".join(cert_now.split(' ')[:-1])
            else:
                cert_name = self.i18n("msg_no_cert")
                # 证书解析失败(sc_cert 为 None)或无 CN(SAN 证书)时保持默认文案
                owners = getattr(cert_data.sc_cert, "OwnersInfo", None)
                if owners and owners.get("CN"):
                    cert_name = owners["CN"]
            table.insert("", tk.END, values=(
                cert_now.split(' ')[-1],
                cert_name,
                cert_data.sc_exec,
                cert_data.sc_keys
            ))
        return None

    def clear_cert_pick(self):
        """清空证书选中状态：详情区回到居中提示，相关按钮禁用。"""
        self.pick["cert"] = ""
        for item_name in ["cert_info", "cert_user", "cert_last"]:
            for fill_name in self.labels[item_name]:
                self.labels[item_name][fill_name][1].config(text="")
            self.toggle_labels(item_name, False)
        for key in ["non", "sys", "out"]:
            self.button["cert_main"][key].config(state=tk.DISABLED)
        return None

    # 按钮行垂直居中 ==========================================================
    # 按钮组, 上方块, 下方块（table: / frame: / end: 三种引用）
    BUTTON_ROWS = (
        ("card_main", "table:card_main", "frame:card_info"),
        ("cert_main", "table:cert_main", "frame:cert_info"),
        ("card_opts", "frame:card_info", "end:card_main"),
    )

    def align_button_rows(self):
        """把按钮行垂直居中到上下两块之间，使按钮上下间距一致。

        美化主题与原版主题的按钮高度不同（31 / 28），固定坐标无法两边都等距，
        因此这里按控件实测高度重新定位（构建阶段 winfo_reqheight 已可用）。
        """
        self.root.update_idletasks()
        for group, above, below in self.BUTTON_ROWS:
            buttons = self.button.get(group)
            if not buttons:
                continue
            row_height = list(buttons.values())[0].winfo_reqheight()
            top = self.block_edge(above, bottom=True)
            bottom = self.block_edge(below, bottom=False)
            if top is None or bottom is None or bottom - top <= row_height:
                continue
            row_y = top + (bottom - top - row_height) // 2
            for widget in buttons.values():
                widget.place_configure(y=row_y)
                widget.lift()
        return None

    def block_edge(self, in_name, bottom=True):
        """取某个块的上下边界；``table:``/``frame:`` 对应已有控件，``end:`` 为框体底边。

        取的都是边框位置（与 ``frame:`` 的上边界同一口径），这样居中到两块之间的
        按钮行，其上下留白才真正相等；``end:`` 是「所在框体的底边」。
        """
        head, _, name = in_name.partition(":")
        if head == "table":
            tree = (self.tables.get(name) or (None, None))[0]
            if tree is None:
                return None
            return tree.winfo_y() + tree.winfo_height() if bottom else tree.winfo_y()
        frame = self.frames.get(name)
        if frame is None:
            return None
        if head == "end":
            return frame.winfo_y() + frame.winfo_height()
        return frame.winfo_y() + frame.winfo_height() if bottom else frame.winfo_y()

    # 添加框架控件 ============================================================
    def view_frames(self, in_name):
        tb_conf = self.conf['frames']
        if in_name in tb_conf:
            tag = self.new_widget("LabelFrame", self.frame_style,
                                  width=tb_conf[in_name][0],
                                  height=tb_conf[in_name][1],
                                  text=self.i18n(in_name))
            tag.place(x=tb_conf[in_name][2], y=tb_conf[in_name][3])
            return tag
        return None

    # 添加表格控件 ============================================================
    #                     表格名称 表格的样式风格
    def view_tables(self, in_name, t_style=None):
        tb_conf = self.conf['tables']
        if in_name not in tb_conf:
            return None, None
        # 处理基本信息 ========================================================
        tb_pack = tb_conf[in_name]['pack']
        tb_data = tb_conf[in_name]['data']
        tb_name = list(i for i in tb_data)
        tb_head = [self.i18n(tb_data[i][1]) for i in tb_name]
        tb_lens = sum([tb_data[i][0] for i in tb_data])
        # 列宽直接使用布局配置（固定排布，便于各列宽窄一致）
        tb_cols = [tb_data[i][0] for i in tb_name]
        # 表格 + 滚动条可用的总宽度（配置缺省时按列宽推算，兼容旧配置）
        tb_area = tb_pack[3] if len(tb_pack) > 3 else tb_lens + 25
        # 添加表格组件 ========================================================
        inf = self.new_widget("Treeview", t_style or self.table_style,
                              show="headings",
                              columns=tb_name)
        bar = self.new_widget("Scrollbar", t_style or self.table_style,
                              orient='vertical',
                              command=inf.yview)
        inf.configure(yscrollcommand=bar.set)
        # 表头样式必须配置到控件实际使用的样式上（<主题样式>.Heading），
        # 否则会被主题的专用样式覆盖：配色要与滚动条区分开，否则表头与滑块
        # 颜色相同会连成一片，看上去滚动条贯穿整个表格
        head_style = "%s.Heading" % (inf.cget("style") or "Treeview")
        self.style.configure(head_style, padding=HEAD_PADDING)
        if not self.native and self.theme.get("flat_heading"):
            head_bg = self.theme.get("head_bg") or COLOR_HEAD_BG
            head_fg = self.theme.get("head_fg") or COLOR_HEAD_FG
            self.style.configure(head_style, background=head_bg, foreground=head_fg,
                                 relief="flat", borderwidth=0)
            self.style.map(head_style, background=[("active", head_bg)])
        # 表头高度/行高随主题不同，先探测再决定可视行数
        tb_head_h, tb_row_h = self.table_metrics(inf)
        tb_rows = max(3, int(tb_pack[2] / tb_row_h))
        inf.configure(height=tb_rows)
        inf.update_idletasks()
        # 设置表格组件：表格占满整个区域，滚动条叠在表体右侧 ===================
        # （表头下沿起始、与表体等高，视觉上滚动条位于表格内部）
        # 宽度取控件实际值：不同主题的滚动条宽度不同（原版主题更宽）
        bar_width = bar.winfo_reqwidth() or TABLE_BAR_WIDTH
        inf.place(x=tb_pack[0], y=tb_pack[1], width=tb_area)
        bar.place(x=tb_pack[0] + tb_area - bar_width - 1,
                  y=tb_pack[1] + tb_head_h,
                  height=tb_rows * tb_row_h)
        bar.lift()
        # 设置表列信息 ========================================================
        for th_name, th_width, th_text in zip(tb_name, tb_cols, tb_head):
            inf.heading(th_name, text=th_text)  # 标题
            # 不让列随控件宽度拉伸：右侧多出的留白正好被滚动条盖住，
            # 最后一列的内容不会被滚动条遮挡
            inf.column(th_name, anchor='w', width=th_width, stretch=False)
        return inf, bar

    @staticmethod
    def table_metrics(tree):
        """探测表格的表头高度与行高（不同主题数值不同，用于对齐滚动条）。"""
        try:
            tree.configure(height=2)
            tree.update_idletasks()
            small = tree.winfo_reqheight()
            tree.configure(height=4)
            tree.update_idletasks()
            large = tree.winfo_reqheight()
        except Exception:
            return TABLE_HEAD_HEIGHT, TABLE_ROW_HEIGHT
        row_h = max(1, (large - small) // 2)
        head_h = small - 2 * row_h
        if row_h <= 1 or head_h <= 0:
            return TABLE_HEAD_HEIGHT, TABLE_ROW_HEIGHT
        return head_h, row_h

    # 添加按钮控件 ============================================================
    def view_button(self, in_name):
        tb_conf = self.conf['button']
        if in_name not in tb_conf:
            return None
        bt_dict = dict()
        # 处理基本信息 ========================================================
        # [起始 X, 起始 Y, 按钮间距(可选), 整排总宽度(可选，用于自适应按钮宽度)]
        bt_cfg = tb_conf[in_name][0]
        bt_btx = bt_cfg[0]
        bt_bty = bt_cfg[1]
        bt_gap = bt_cfg[2] if len(bt_cfg) > 2 else 2
        bt_total = bt_cfg[3] if len(bt_cfg) > 3 else 0
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

            "ing": (self.load_status, None),
            "tpm": (self.check_tpm_h, None),
            "set": (self.card_settings, None),
            "bak": (self.card_backup, None),
            "rec": (self.card_restore, None),
        }
        # 按钮宽度按当前语言文案的实测宽度分配，长文案语言（俄语等）不会被截断
        bt_texts = [self.i18n(now['text']) for now in bt_all]
        bt_styles = [self.button_style(now) for now in bt_all]
        bt_sizes = self.fit_buttons(bt_texts, bt_styles, bt_total, bt_gap, bt_all)
        for now, bta_text, bta_style, bta_size in zip(bt_all, bt_texts, bt_styles, bt_sizes):
            bt_fun = bt_map[now['name']] if now['name'] in bt_map else (None, None)
            bta = self.new_widget("Button", bta_style, text=bta_text,
                                  command=bt_fun[0] if bt_fun[1] is None
                                  else partial(bt_fun[0], bt_fun[1]))
            bta.place(x=bt_btx, y=bt_bty, width=bta_size)
            bt_btx = bt_btx + bta_size + bt_gap
            bt_dict[now['name']] = bta
        return bt_dict

    def button_style(self, item):
        """按钮配色：主题可整体覆盖（配置里没写就用 button.json 的 type）。"""
        override = (self.theme.get("button") or {}).get(item['name'])
        return override or item['type']

    def button_style_names(self):
        """界面用到的全部按钮配色名（原版主题下用于统一文字颜色）。"""
        styles = set((self.theme.get("button") or {}).values())
        for group in (self.conf.get('button') or {}).values():
            for item in group[1:]:
                if item.get("type"):
                    styles.add(item["type"])
        return sorted(styles)

    def fit_buttons(self, texts, styles, total, gap, conf):
        """确定一排按钮各自的宽度。

        以布局配置里的 ``w`` 为基准（保证间距均匀、可预期）；
        某个按钮的文案比配置更宽时按需加宽，整排放不下时再等比压缩。
        """
        if not total:
            return [item['w'] for item in conf]
        count = len(texts)
        avail = total - gap * (count - 1)
        if count <= 0 or avail <= 0:
            return [item['w'] for item in conf]
        needs = [self.measure_button(text, style) for text, style in zip(texts, styles)]
        sizes = [max(conf[index]['w'], needs[index]) for index in range(count)]
        total_now = sum(sizes)
        if total_now > avail:
            sizes = [max(MIN_BUTTON_WIDTH, int(size * avail / total_now)) for size in sizes]
        sizes[-1] = max(MIN_BUTTON_WIDTH, avail - sum(sizes[:-1]))
        return sizes

    def measure_button(self, text, style_name):
        """量出按钮文案实际需要的宽度（含主题的内边距与边框）。"""
        probe = self.new_widget("Button", style_name, text=text)
        width = probe.winfo_reqwidth()
        probe.destroy()
        if width <= 1:
            # 控件尺寸尚未计算时用字体测量兜底
            width = self.t_fonts['label_data'].measure(text) + BUTTON_PADDING_FALLBACK
        return width

    def view_labels(self, in_name):
        # 卡片信息 ======
        tb_conf = self.conf['labels']
        # 需要折行的条目（如部门名称）：键为标签名，值为折行宽度
        wrap_conf = tb_conf.get("wrap") or {}
        tb_data = dict()
        if in_name in tb_conf:
            tb_conf = tb_conf[in_name]
            tb_ln_x = tb_conf['conf'][0]
            tb_it_y = tb_conf['conf'][1]
            # 行高可选（缺省 20）：详情框越高的分组可以排得松一些
            tb_row = tb_conf['conf'][2] if len(tb_conf['conf']) > 2 else LABEL_ROW_HEIGHT
            for tb_line in tb_conf['data']:
                tb_it_x = tb_ln_x
                for tb_item in tb_line:
                    tag = self.new_widget("Label", "default",
                                          text=self.i18n(tb_item) + ": ",
                                          font=self.t_fonts['label_name'])
                    tag.place(x=tb_it_x, y=tb_it_y)
                    inf = self.new_widget("Label", "default", text="",
                                          font=self.t_fonts['label_data'])
                    if tb_item in wrap_conf:
                        # 超出可用宽度的长文本自动折行，多行时左对齐
                        inf.config(wraplength=wrap_conf[tb_item],
                                   justify=tk.LEFT)
                    inf.place(x=tb_it_x + LABEL_WIDTH + LABEL_GAP, y=tb_it_y)
                    # 同时记下坐标，未选中卡片/证书时要整组隐藏
                    tb_data[tb_item] = [tag, inf,
                                        (tb_it_x, tb_it_y),
                                        (tb_it_x + LABEL_WIDTH + LABEL_GAP, tb_it_y)]
                    tb_it_x += LABEL_WIDTH + LABEL_GAP + tb_line[tb_item]
                tb_it_y += tb_row
        return tb_data

    # 详情区：未选中卡片/证书时只显示一行居中提示 ==============================
    def view_hint(self, in_name, in_text_key):
        frame_now = self.frames.get(in_name)
        if frame_now is None:
            return None
        hint = self.new_widget("Label", "secondary", in_master=frame_now,
                               font=self.t_fonts['label_data'],
                               text=self.i18n(in_text_key))
        hint.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        return hint

    def toggle_labels(self, in_group, in_visible):
        """显示/隐藏一组详情标签：隐藏时改为显示该区域的居中提示。"""
        for item in (self.labels.get(in_group) or {}).values():
            for widget, pos in ((item[0], item[2]), (item[1], item[3])):
                if in_visible:
                    widget.place(x=pos[0], y=pos[1])
                else:
                    widget.place_forget()
        hint = self.hints.get(in_group)
        if hint is None:
            return None
        if in_visible:
            hint.place_forget()
        else:
            hint.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        return None

    def table_blank_click(self, in_name, event):
        """点击表格空白处取消选中。

        只处理表体里没有行命中的位置（点表头、列分隔线不影响选中状态），
        取消选中后会触发 <<TreeviewSelect>>，由对应处理函数复位详情与按钮。
        """
        tree = (self.tables.get(in_name) or (None, None))[0]
        if tree is None:
            return None
        if tree.identify_region(event.x, event.y) not in ("tree", "nothing"):
            return None
        if tree.identify_row(event.y):
            return None
        selected_item = tree.selection()
        if selected_item:
            tree.selection_remove(*selected_item)
        return None

    def card_select(self, event):
        treeview = event.widget
        selected_item = treeview.selection()
        # 有选中卡片才显示详情标签，否则只留一行提示
        self.toggle_labels("card_info", len(selected_item) > 0)
        if len(selected_item) > 0:
            selected_name = treeview.set(selected_item[0], '#2')
            # 换了卡片，证书列表要跟着换（同一张卡重复选中时保留已选中的证书）
            card_changed = selected_name != self.pick.get("card")
            self.pick["card"] = selected_name
            self.button["card_opts"]["del"].config(state=tk.NORMAL)
            self.button["card_main"]["pin"].config(state=tk.NORMAL)
            self.button["card_main"]["puk"].config(state=tk.NORMAL)
            self.button["card_opts"]["bak"].config(state=tk.NORMAL)
            if selected_name in self.data.cards:
                card_now = self.data.cards[selected_name]
                card_map = {
                    "card_name": selected_name,
                    "card_uuid": card_now.sc_uuid,
                    "card_path": card_now.sc_path,
                    "card_list": card_now.card_id,
                    "sc_status": card_now.sc_sha1,
                    "sc_length": card_now.sc_sha2
                }
                for fill_name in card_map:
                    if fill_name in self.labels["card_info"]:
                        self.labels["card_info"][fill_name][1].config(text=card_map[fill_name])
            print(selected_name)
        else:
            card_changed = bool(self.pick.get("card"))
            # 取消选中：清空详情与选中状态，相关按钮回到未选中时的状态
            self.pick["card"] = ""
            for fill_name in self.labels["card_info"]:
                self.labels["card_info"][fill_name][1].config(text="")
            for key in ["pin", "puk"]:
                self.button["card_main"][key].config(state=tk.DISABLED)
            for key in ["del", "bak"]:
                self.button["card_opts"][key].config(state=tk.DISABLED)
        if card_changed:
            # 证书列表按卡片过滤，选卡/取消选卡后同步刷新
            self.fill_cert_table()

    def card_backup(self):
        """备份选中的 TPM 虚拟智能卡（卡片数据目录 + 卡片设备注册表）。

        卡片数据目录位于 LocalService 服务账户配置下::

            %SystemRoot%\\ServiceProfiles\\LocalService\\AppData\\Local\\
            Microsoft\\Windows\\SmartCard\\Tpm

        该目录默认 ACL 只允许 SYSTEM/管理员访问，因此备份需要管理员权限；
        打包配置里 uac_admin=True，安装后运行即满足。
        """
        if not TPMBackup.is_admin():
            messagebox.showwarning(self.i18n("warn"), self.i18n("msg_bak_admin"))
            return None
        if self.pick["card"] not in self.data.cards:
            messagebox.showwarning(self.i18n("warn"), self.i18n("msg_bak_select"))
            return None
        card_now = self.data.cards[self.pick["card"]]
        out_path = filedialog.asksaveasfilename(
            defaultextension=TPMBackup.BACKUP_SUFFIX,
            filetypes=[(self.i18n("msg_dlg_tsb_files"), "*%s" % TPMBackup.BACKUP_SUFFIX),
                       (self.i18n("msg_dlg_all_files"), "*.*")],
            initialdir=os.path.expanduser("~"),
            initialfile="%s-%s%s" % (TPMBackup.normalize_name(card_now.sc_name),
                                     card_now.card_id, TPMBackup.BACKUP_SUFFIX),
            title=self.i18n("msg_bak_dir"))
        if not out_path:
            return None
        try:
            report = TPMBackup.create_backup(out_path,
                                             name=card_now.sc_name,
                                             uid=card_now.card_id)
        except TPMBackup.BackupError as err:
            messagebox.showerror(self.i18n("fail"), self.i18n("msg_bak_fail") % err)
            return None
        except Exception as err:
            print("Backup Card Error:", err)
            traceback.print_exc()
            messagebox.showerror(self.i18n("fail"), self.i18n("msg_bak_fail") % err)
            return None
        result = self.i18n("msg_bak_ok") % (report["file"],
                                           str(report["file_count"]),
                                           TPMBackup.human_size(report["size"]),
                                           str(report["reg_count"]))
        if report.get("warning"):
            result += "\n\n" + report["warning"]
        # 备份日志一并展示并落盘：清单里的 store.guid 与备份范围（单卡 / 整目录）
        # 直接决定还原时能否把「设备 → store 目录」绑定写回去，出问题要看得到。
        detail = report.get("log") or []
        if detail:
            log_file = TPMBackup.save_log(detail, tag="backup")
            result += "\n\n" + "\n".join(str(line) for line in detail)
            if log_file:
                result += "\n\n备份日志文件: %s" % log_file
        messagebox.showinfo(self.i18n("msg_bak_title"), fit_dialog_text(result))
        return None

    def card_restore(self, package=None):
        """从 .tsb 备份文件还原虚拟智能卡（回写卡片数据目录并导入注册表）。

        :param package: 双击关联的 .tsb 文件时由启动参数直接给出；省略时弹文件选择框
        注意：卡片私钥由 TPM 保护，备份只在同一台电脑且同一 TPM（未清除）上可还原。
        """
        if not TPMBackup.is_admin():
            messagebox.showwarning(self.i18n("warn"), self.i18n("msg_bak_admin"))
            return None
        if not package:
            package = filedialog.askopenfilename(
                defaultextension=TPMBackup.BACKUP_SUFFIX,
                filetypes=[(self.i18n("msg_dlg_tsb_files"), "*%s" % TPMBackup.BACKUP_SUFFIX),
                           (self.i18n("msg_dlg_all_files"), "*.*")],
                initialdir=os.path.expanduser("~"),
                title=self.i18n("msg_rec_dir"))
        if not package:
            return None
        try:
            manifest = TPMBackup.read_manifest(package)
        except TPMBackup.BackupError as err:
            messagebox.showerror(self.i18n("fail"),
                                 "%s\n%s" % (self.i18n("msg_rec_bad"), err))
            return None
        card_now = manifest.get("card") or {}
        uid = str(card_now.get("instance") or "")
        tips = ""
        # 同名卡片已存在时提醒覆盖风险（建议先删除卡片，避免文件被占用）
        if TPMBackup.find_card(uid=uid) is not None:
            tips += (self.i18n("msg_rec_exist") % uid) + "\n\n"
        tips += self.i18n("msg_rec_confirm") % (card_now.get("name") or self.i18n("msg_na"),
                                                uid or self.i18n("msg_na"),
                                                manifest.get("created_at") or self.i18n("msg_na"))
        if not messagebox.askokcancel(self.i18n("msg_rec_title"), tips):
            return None
        # TPM 指纹校验：与备份不一致时强烈警告，但仍允许强制还原
        tpm_state, tpm_text = TPMBackup.check_tpm(manifest)
        print("Restore TPM Check:", tpm_state, tpm_text)
        force = False
        if tpm_state == "mismatch":
            if not messagebox.askokcancel(self.i18n("msg_rec_title"),
                                          self.i18n("msg_rec_tpm_diff") % tpm_text):
                return None
            force = True
        try:
            report = TPMBackup.restore_backup(package, force=force)
        except TPMBackup.BackupError as err:
            messagebox.showerror(self.i18n("fail"), self.i18n("msg_rec_fail") % err)
            return None
        except Exception as err:
            print("Restore Card Error:", err)
            traceback.print_exc()
            messagebox.showerror(self.i18n("fail"), self.i18n("msg_rec_fail") % err)
            return None
        result = self.i18n("msg_rec_ok") % (str(report["file_count"]),
                                            str(report["reg_count"]))
        if report.get("stale"):
            result += "\n" + self.i18n("msg_rec_stale") % str(len(report["stale"]))
        # 还原的结论、逐条日志与现场诊断一并展示：GUI 下没有控制台，只提示
        # 「已完成」的话，出问题时（注册表没写进去 / 设备没建出来 / 绑定没写回 /
        # 卡片没加载）用户无从判断，也无法反馈。完整日志同时落盘到 log_file。
        detail = report.get("log") or []
        if detail:
            result += "\n\n" + "\n".join(str(line) for line in detail)
        messagebox.showinfo(self.i18n("msg_rec_title"), fit_dialog_text(result))
        self.load_status()
        return None

    def cert_out_to(self, in_path=None):
        la_path = in_path
        if self.pick["cert"] in self.data.certs:
            now_cert = self.data.certs[self.pick["cert"]]
            if now_cert.sc_cert is not None:
                if in_path is None:
                    in_path = filedialog.asksaveasfilename(
                        defaultextension=".crt",  # 默认文件扩展名
                        # 文件类型过滤器
                        filetypes=[(self.i18n("msg_dlg_cert_files"), "*.crt"),
                                   (self.i18n("msg_dlg_all_files"), "*.*")],
                        # 初始目录：展开 ~ ，与启动方式（工作目录）无关
                        initialdir=os.path.expanduser("~"),
                        initialfile="%s.crt" % str(now_cert.sc_cert.SerialNums),  # 初始文件名
                        title=self.i18n("msg_dlg_save_as")  # 对话框标题
                    )
                    # 用户取消保存对话框：直接返回，不再弹出选择路径的提示
                    if not in_path:
                        return None
                else:
                    in_path = "%s\\%s.crt" % (in_path, str(now_cert.sc_cert.SerialNums))
                if len(in_path) <= 0:
                    messagebox.showwarning(self.i18n("msg_cert_out_ft_item"), self.i18n("msg_cert_out_ft_path"))
                else:
                    with open(in_path, "w") as save_file:
                        save_file.write(now_cert.sc_text)
                    if la_path is None:
                        messagebox.showinfo(
                            self.i18n("msg_cert_out_ok_item"),
                            self.i18n("msg_cert_out_ok_text") % str(now_cert.sc_cert.CommonName)
                        )
                    return in_path
            else:
                messagebox.showerror(self.i18n("msg_cert_out_ft_item"), self.i18n("msg_cert_out_ft_text"))
        else:
            messagebox.showerror(self.i18n("msg_cert_out_ft_item"), self.i18n("msg_cert_out_ft_none"))
        return None

    def cert_system(self):
        save_path = self.cert_out_to(in_path=os.getenv('APPDATA'))
        if save_path is not None and os.path.exists(save_path):
            os.system("explorer %s" % save_path)

    def cert_value(self, in_text, in_limit=0):
        """证书扩展字段的显示值。

        取值为空（或缺失）时返回「（空）」，超长时截断并加省略号，
        避免把 ``b''`` 之类的原始值直接显示到界面上。
        """
        text = str(in_text)
        if text == "":
            return self.i18n("msg_empty")
        if in_limit and len(text) >= in_limit:
            return text[:in_limit] + "..."
        return text

    def cert_select(self, event):
        treeview = event.widget
        selected_item = treeview.selection()
        for item_name in ["cert_info", "cert_user", "cert_last"]:
            for fill_name in self.labels[item_name]:
                self.labels[item_name][fill_name][1].config(text="")
        # 有选中证书才显示详情，否则三个分组框都只留一行居中提示
        has_cert = len(selected_item) > 0
        for toggle_name in ["cert_info", "cert_user", "cert_last"]:
            self.toggle_labels(toggle_name, has_cert)
        if len(selected_item) > 0:
            selected_name = treeview.set(selected_item[0], '#2')
            selected_uuid = treeview.set(selected_item[0], '#1')
            selected_name = selected_name.replace(self.i18n("msg_no_cert"), "")
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
                    empty_tag = self.i18n("msg_empty")
                    none_tag = self.i18n("msg_na")
                    user_name = cert_now.OwnersInfo["CN"] if "CN" in cert_now.OwnersInfo else empty_tag
                    user_name = user_name[:35] + ".." if len(user_name) > 35 else user_name
                    last_name = cert_now.IssuerInfo["CN"] if "CN" in cert_now.IssuerInfo else empty_tag
                    last_name = last_name[:35] + ".." if len(last_name) > 35 else last_name
                    cer_policy = empty_tag
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
                        "cert_sha1": self.i18n("msg_hex_prefix") + str(cert_now.CertSHA160).replace(":", ""),
                        "is_ca_cert": cert_now.is_ca_cert,
                        "is_expired": cert_now.is_expired,

                        "key_usages": self.cert_value(cert_now.MainUsages, 86),
                        "sub_usages": self.cert_value(cert_now.SubsUsages, 86),
                        "key_identy": self.cert_value(str(cert_now.MainHashID).replace(":", "")),
                        "sub_identy": self.cert_value(str(cert_now.SubsHashID).replace(":", "")),
                        "uid_serial": cert_now.OwnersInfo["UID"] if "UID" in cert_now.OwnersInfo else \
                            cert_now.OwnersInfo["SERIALNUMBER"] if "SERIALNUMBER" in cert_now.OwnersInfo else empty_tag,
                        "cer_policy": cer_policy,
                        "user_name": user_name,
                        "user_code": cert_now.OwnersInfo["C"] if "C" in cert_now.OwnersInfo else none_tag,
                        "user_area": cert_now.OwnersInfo["S"][:7] if "S" in cert_now.OwnersInfo else none_tag,
                        "user_city": cert_now.OwnersInfo["L"][:7] if "L" in cert_now.OwnersInfo else none_tag,
                        "user_on_t": cert_now.OwnersInfo["O"][:39] if "O" in cert_now.OwnersInfo else empty_tag,
                        "user_ou_t": cert_now.OwnersInfo["OU"][:39] if "OU" in cert_now.OwnersInfo else empty_tag,

                        "last_name": last_name,
                        "last_code": cert_now.IssuerInfo["C"] if "C" in cert_now.IssuerInfo else none_tag,
                        "last_area": cert_now.IssuerInfo["S"][:7] if "S" in cert_now.IssuerInfo else none_tag,
                        "last_city": cert_now.IssuerInfo["L"][:7] if "L" in cert_now.IssuerInfo else none_tag,
                        "last_on_t": cert_now.IssuerInfo["O"][:39] if "O" in cert_now.IssuerInfo else empty_tag,
                        "last_ou_t": cert_now.IssuerInfo["OU"][:39] if "OU" in cert_now.IssuerInfo else empty_tag,
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
        else:
            # 取消选中：清空选证状态，详情回到提示，相关按钮禁用
            self.clear_cert_pick()

    def check_tpm_h(self, out=True):
        """检测 TPM 状态（解析见 Module.TPMSmartCard.tpmStatus）。

        状态码：0 已激活、1 未激活、-1 状态未知（如未以管理员权限运行）。
        """
        status, _, results = TPMSmartCard.tpmStatus()
        if out:
            if status == 0:
                messagebox.showinfo(self.i18n("msg_tpm_check_text"),
                                    self.i18n("msg_tpm_check_done") % results)
            elif status == 1:
                messagebox.showerror(self.i18n("msg_tpm_check_text"),
                                     self.i18n("msg_tpm_check_fail") % results)
            else:
                messagebox.showwarning(self.i18n("msg_tpm_check_text"),
                                       self.i18n("msg_tpm_check_none") % results)
        return status

    def install_osc(self):
        """安装随程序分发的 OpenSC（安装逻辑统一放在 MoreConfig 中）。"""
        return MoreConfig.installOpenSC()

    def restart_app(self):
        """安装 OpenSC 后重启自身，让新装的驱动/服务在新进程里生效。

        注意：不能使用内置的 ``exit()`` / ``quit()``，它们由 ``site`` 模块注入，
        而 cx_Freeze 冻结后的解释器不会执行 site 初始化，会抛 NameError: name 'exit' is not defined。
        统一改用 ``sys.exit()``（sys 已导入，任何环境都存在）。
        """
        if getattr(sys, "frozen", False):
            # 打包后 sys.executable 就是应用本体
            os.startfile(sys.executable)
        else:
            # 源码运行：exe 是 python.exe，需要把脚本路径一并传过去
            os.startfile(sys.executable, "open",
                         '"%s"' % os.path.abspath(sys.argv[0]))
        # 先正常收尾（摘托盘、销毁主窗口），再退出当前进程
        self.quit_app()
        sys.exit(0)

    def card_change(self, in_type="pin"):
        if not self.pick["card"] or self.pick["card"] not in self.data.cards:
            return None

        def change(item, tips, is_same=False, *args):
            password = item.get()
            # print(password)
            if len(password) < 8:
                tips.config(text="❌ " + self.i18n("msg_pass_length_l1" if not is_same else "msg_pass_length_l2"))
                submit_button.config(state=tk.DISABLED)
            elif is_same and next_txt.get() != same_txt.get():
                tips.config(text="❌ " + self.i18n("msg_pass_not_same_"))
                submit_button.config(state=tk.DISABLED)
            else:
                tips.config(text="✅ ")
            if len(pass_txt.get()) >= 8 and len(next_txt.get()) >= 8:
                if next_txt.get() == same_txt.get():
                    next_tip.config(text="✅ ")
                    same_tip.config(text="✅ ")
                    submit_button.config(state=tk.NORMAL)
                else:
                    submit_button.config(state=tk.DISABLED)
            else:
                submit_button.config(state=tk.DISABLED)
            if in_type == "pin" and pass_txt.get() == next_txt.get() == same_txt.get():
                tips.config(text="❌ " + self.i18n("msg_pass_next_same"))
                submit_button.config(state=tk.DISABLED)

        def submit():
            # 读卡器编号必须用实际编号：卡片编号(如 0002) ≠ pcsc 编号（删过卡后会错位），
            # 旧实现按卡名末位数字当编号，会报 reader "2" not found。
            card_uid = self.data.readerIndexFor(self.pick["card"])
            if card_uid is None:
                make.attributes('-topmost', False)
                messagebox.showwarning(self.i18n("warn"), self.i18n("msg_reader_not_found"))
                make.attributes('-topmost', True)
                return
            pass_key = pass_txt.get()
            pass_new = next_txt.get()
            same_new = same_txt.get()
            # print(pass_key, pass_new, same_new)
            if pass_key == "" or len(pass_key) < 8:
                make.attributes('-topmost', False)
                messagebox.showwarning(self.i18n("warn"), self.i18n("msg_pass_length_l1"))
                make.attributes('-topmost', True)
            elif pass_new == "" or len(pass_new) < 8:
                make.attributes('-topmost', False)
                messagebox.showwarning(self.i18n("warn"), self.i18n("msg_pass_length_l2"))
                make.attributes('-topmost', True)
            elif pass_new != same_new:
                make.attributes('-topmost', False)
                messagebox.showwarning(self.i18n("warn"), self.i18n("msg_pass_not_same_"))
                make.attributes('-topmost', True)
            else:
                result = TPMSmartCard.changePIN(pass_key, pass_new, card_uid,
                                                type="--change-pin" \
                                                    if in_type == "pin" else "--unblock-pin")
                messagebox.showinfo(self.i18n("msg_pass_change_ok"), result)
                self.close_dialog(make)

        make = ttk.Toplevel(self.root)
        # 点右上角 × 也走 close_dialog：先取消主题订阅再销毁
        make.protocol("WM_DELETE_WINDOW", lambda: self.close_dialog(make))
        # 拉丁/西里尔字母比汉字占位更宽，标签与右侧提示语按语言留足宽度
        make.geometry("%dx%d" % (760 if self.wide else 700, 200))
        make.geometry(f"+{self.size[0]}+{self.size[1]}")
        make.title(self.i18n("msg_pass_change_tx") if in_type == "pin" else self.i18n("msg_pass_resets_tx"))

        pass_lan = self.i18n("msg_old") + " PIN: " if in_type == "pin" else self.i18n("msg_card") + " PUK: "
        pass_var = tk.StringVar()
        pass_tag = ttk.Label(make, text=pass_lan, bootstyle="info")
        pass_txt = ttk.Entry(make, bootstyle="info", width=60, textvariable=pass_var, show="*")
        pass_tip = ttk.Label(make, text="", bootstyle="info")
        pass_var.trace('w', partial(change, pass_txt, pass_tip, False))
        pass_tag.grid(column=0, row=1, pady=10, padx=15)
        pass_txt.grid(column=1, row=1, pady=10, padx=5)
        pass_tip.grid(column=2, row=1, pady=10, padx=5, sticky=W)

        next_var = tk.StringVar()
        next_pin = ttk.Label(make, text=self.i18n("msg_new") + " PIN: ", bootstyle="info")
        next_txt = ttk.Entry(make, bootstyle="info", width=60, textvariable=next_var, show="*")
        next_tip = ttk.Label(make, text="", bootstyle="info")
        next_var.trace('w', partial(change, next_txt, next_tip, True))
        next_pin.grid(column=0, row=2, pady=10, padx=15)
        next_txt.grid(column=1, row=2, pady=10, padx=5)
        next_tip.grid(column=2, row=2, pady=10, padx=5, sticky=W)

        same_var = tk.StringVar()
        same_pin = ttk.Label(make, text=self.i18n("msg_confirm") + " PIN: ", bootstyle="info")
        same_txt = ttk.Entry(make, bootstyle="info", width=60, textvariable=same_var, show="*")
        same_tip = ttk.Label(make, text="", bootstyle="info")
        same_var.trace('w', partial(change, same_txt, same_tip, True))
        same_pin.grid(column=0, row=3, pady=10, padx=15)
        same_txt.grid(column=1, row=3, pady=10, padx=5)
        same_tip.grid(column=2, row=3, pady=10, padx=5, sticky=W)

        cancel_button = ttk.Button(make, text=self.i18n("msg_cancel"),
                                   command=lambda: self.close_dialog(make), bootstyle="danger")
        cancel_button.grid(column=0, row=4, pady=5, padx=15)
        submit_button = ttk.Button(make, text=self.i18n("msg_confirm"), command=submit, bootstyle="info")
        submit_button.grid(column=2, row=4, pady=5, padx=0)
        submit_button.config(state=tk.DISABLED)
        # 窗口按内容实测尺寸再定一次：各语言的标签与右侧提示长短不同，
        # 固定尺寸会把提示挤掉（不低于设计尺寸，且不超出屏幕）
        make.update_idletasks()
        make.geometry("%dx%d+%d+%d" % (
            min(max(760 if self.wide else 700, make.winfo_reqwidth()),
                make.winfo_screenwidth() - 40),
            min(max(200, make.winfo_reqheight()), make.winfo_screenheight() - 80),
            self.size[0], self.size[1]))
        make.resizable(False, False)
        make.mainloop()

    def card_create(self):
        def change(*args):
            if len(name_txt.get()) == 0 or len(pins_txt.get()) < 8:
                submit_button.config(state=tk.DISABLED)
            else:
                submit_button.config(state=tk.NORMAL)

        def disable():
            if puks_var.get():
                puks_txt.delete(0, tk.END)
                puks_txt.config(state=tk.DISABLED)
                make.attributes('-topmost', False)
                messagebox.showinfo(self.i18n("msg_disable") + "PUK", self.i18n("msg_ban_puk_warn"))
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
            if not TPMSmartCard.isElevated():
                # 建卡必须提权，未提权时 tpmvscmgr 只会给出误导性的
                # "(0x80070002) 系统找不到指定的文件"
                make.attributes('-topmost', False)
                messagebox.showwarning(self.i18n("fail"), self.i18n("msg_need_admin"))
                make.attributes('-topmost', True)
            elif TPMSmartCard.isRemoteSession():
                # 远程桌面（终端服务）会话下 Windows 会拒绝建卡（0x800704d3），
                # 提前提示，避免跑满 5 分钟超时后再弹出难懂的错误
                make.attributes('-topmost', False)
                messagebox.showwarning(self.i18n("fail"), self.i18n("msg_remote_session"))
                make.attributes('-topmost', True)
            elif name_txt.get() == "":
                make.attributes('-topmost', True)
                messagebox.showwarning(self.i18n("fail"), self.i18n("msg_new_card_txt_e"))
            elif not 8 <= len(pins_txt.get()) <= 15:
                make.attributes('-topmost', True)
                messagebox.showwarning(self.i18n("fail"), self.i18n("msg_new_card_pin_e"))
            elif len(puks_txt.get()) > 0 and not 16 <= len(puks_txt.get()) <= 16:
                make.attributes('-topmost', True)
                messagebox.showwarning(self.i18n("fail"), self.i18n("msg_new_card_puk_e"))
            elif len(adks_txt.get()) != 48:
                make.attributes('-topmost', True)
                messagebox.showwarning(self.i18n("fail"), self.i18n("msg_new_card_key_e"))
            else:
                deals_process['value'] = 0
                deals_destroy = False
                # Tk 控件只能在主线程访问：先取值，工作线程只做耗时操作
                pin = pins_txt.get()
                puk = puks_txt.get()
                adk = adks_txt.get()
                name = name_txt.get()

                def create(in_pin, in_puk, in_adk, in_name):
                    try:
                        result = TPMSmartCard.makeCards(in_pin, in_puk, in_adk, in_name)
                    except Exception as err:
                        print("Create Card Error:", err)
                        traceback.print_exc()
                        result = "Error: %s" % err
                    result = "\n".join(result.split("\n")[-12:])
                    out = "%s PIN: %s\n%s PUK: %s\n%s: %s" % (
                        self.i18n("msg_user"), in_pin,
                        self.i18n("msg_user"), in_puk,
                        self.i18n("mag_admin_key"), in_adk
                    )
                    # cid = result.find("ROOT")
                    # if cid >= 0:
                    #     out = result[cid:cid + 25] + "\n" + out
                    self.root.after(0, done, result, out)

                def done(result, out):
                    nonlocal deals_destroy
                    deals_destroy = True
                    deals_process['value'] = 100
                    self.load_status()
                    if make.winfo_exists():
                        self.close_dialog(make)
                        messagebox.showinfo(self.i18n("msg_create") + self.i18n("msg_result"), result)
                        pyperclip.copy(out)
                        messagebox.showinfo(self.i18n("msg_card") + self.i18n("msg_info"),
                                            out + self.i18n("msg_new_card_dones"))

                def update():
                    # 进度条动画用 after 回到主线程，避免跨线程操作 Tk
                    if deals_destroy or not make.winfo_exists():
                        return None
                    if deals_process['value'] < 95:
                        deals_process['value'] += 0.9
                    self.root.after(150, update)

                cancel_button.config(state=tk.DISABLED)
                submit_button.config(state=tk.DISABLED)
                process = threading.Thread(target=create, args=(pin, puk, adk, name), daemon=True)
                process.start()
                update()

        def cancel():
            self.close_dialog(make)

        make = ttk.Toplevel(self.root)
        make.protocol("WM_DELETE_WINDOW", cancel)
        make.geometry("660x250")
        make.geometry(f"+{self.size[0]}+{self.size[1]}")
        make.attributes('-topmost', True)
        make.title(self.i18n("msg_new_tpm_card"))

        # 在新窗口中添加输入部件
        cancel_button = ttk.Button(make, text=self.i18n("msg_cancel") + self.i18n("msg_create"),
                                   command=cancel, bootstyle="danger")
        cancel_button.grid(column=0, row=4, pady=5, padx=15)
        submit_button = ttk.Button(make, text=self.i18n("msg_create") + self.i18n("msg_card"),
                                   command=submit, bootstyle="info")
        submit_button.grid(column=2, row=4, pady=5, padx=0)
        submit_button.config(state=tk.DISABLED)

        name_var = tk.StringVar()
        name_tag = ttk.Label(make, text=self.i18n("card_name") + ": ", bootstyle="info")
        name_tag.grid(column=0, row=0, pady=10, padx=15)
        name_txt = ttk.Entry(make, bootstyle="info", width=60, textvariable=name_var)
        name_txt.insert(0, self.i18n("msg_card_def_name"))
        name_txt.grid(column=1, row=0, pady=10, padx=5)
        name_tip = ttk.Label(make, text="(1~63%s)" % self.i18n("msg_char"), bootstyle="info")
        name_tip.grid(column=2, row=0, pady=10, padx=5)
        name_var.trace('w', change)

        pins_var = tk.StringVar()
        pins_var.trace('w', change)
        pins_tag = ttk.Label(make, text=self.i18n("msg_card") + " PIN: ", bootstyle="info")
        pins_tag.grid(column=0, row=1, pady=10, padx=15)
        pins_txt = ttk.Entry(make, bootstyle="info", width=60, textvariable=pins_var, show="*")
        # for i in range(0, 8):
        #     pins_txt.insert(0, str(random.randint(0, 9)))
        pins_txt.grid(column=1, row=1, pady=10, padx=5)
        pins_tip = ttk.Label(make, text="(8~63%s)" % self.i18n("msg_char"), bootstyle="info")
        pins_tip.grid(column=2, row=1, pady=10, padx=5)

        puks_tag = ttk.Label(make, text=self.i18n("msg_card") + " PUK: ", bootstyle="info")
        puks_tag.grid(column=0, row=2, pady=10, padx=15)
        puks_txt = ttk.Entry(make, bootstyle="info", width=60)
        puks_txt.grid(column=1, row=2, pady=10, padx=5)
        puks_var = tk.BooleanVar()
        puks_tip = ttk.Checkbutton(make, text=self.i18n("msg_disable") + " PUK", bootstyle="info-round-toggle",
                                   variable=puks_var, command=disable)
        puks_tip.grid(column=2, row=2, pady=10, padx=5)
        for i in range(0, 16):
            puks_txt.insert(0, str(random.randint(0, 9)))

        adks_tag = ttk.Label(make, text=self.i18n("mag_admin_key") + ": ", bootstyle="info")
        adks_tag.grid(column=0, row=3, pady=10, padx=15)
        adks_txt = ttk.Entry(make, bootstyle="info", width=60)
        adks_txt.grid(column=1, row=3, pady=10, padx=5)
        adks_var = tk.BooleanVar()
        adks_tip = ttk.Checkbutton(make, text=self.i18n("mag_random_new"), bootstyle="info-round-toggle",
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
        # 窗口按内容实测尺寸再定一次：其他语言的标签/按钮文案更长（如各语言
        # 的「取消创建/创建卡片」拼接），固定 660x250 会把右侧按钮挤掉
        make.update_idletasks()
        make.geometry("%dx%d+%d+%d" % (
            min(max(660, make.winfo_reqwidth()), make.winfo_screenwidth() - 40),
            min(max(250, make.winfo_reqheight()), make.winfo_screenheight() - 80),
            self.size[0], self.size[1]))
        make.resizable(False, False)
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
            # 点右上角 × 也走 close_dialog：先取消主题订阅再销毁
            make.protocol("WM_DELETE_WINDOW", lambda: self.close_dialog(make))
            # 确认文案较长（且含卡片/证书名称），宽度按语言留足并自动折行
            dialog_w = 400 if self.wide else 340
            make.geometry("%dx%d" % (dialog_w, 240))
            make.resizable(False, False)
            make.geometry(f"+{self.size[0]}+{self.size[1]}")
            make.title(self.i18n("msg_remove") + self.i18n("msg_" + in_name))

            def submit():
                if in_name == "card" and not TPMSmartCard.isElevated():
                    # 删除卡同样需要管理员权限
                    make.attributes('-topmost', False)
                    messagebox.showwarning(self.i18n("fail"), self.i18n("msg_need_admin"))
                    make.attributes('-topmost', True)
                    return None
                if in_name == "card" and TPMSmartCard.isRemoteSession():
                    # 删卡同样受终端服务会话限制（0x800704d3）
                    make.attributes('-topmost', False)
                    messagebox.showwarning(self.i18n("fail"), self.i18n("msg_remote_session"))
                    make.attributes('-topmost', True)
                    return None
                if in_name == "card":
                    result = TPMSmartCard.dropCards(self.data.cards[self.pick[in_name]].sc_path)
                elif in_name == "cert":
                    result = TPMSmartCard.dropCerts(self.pick["cert"])
                self.deselectAll()
                self.load_status()
                self.close_dialog(make)
                if len(result) > 0:
                    if in_name == "cert":
                        result += self.i18n("delete_cert_reboot")
                    messagebox.showinfo(self.i18n("msg_remove") + self.i18n("msg_result"), result)

            def checks():
                if kill_var.get():
                    submit_b.config(state=tk.NORMAL)
                else:
                    submit_b.config(state=tk.DISABLED)

            # 长文案自动折行（原来是 place 固定坐标，其他语言会被裁掉）
            wrap = dialog_w - 40
            kill_tag = ttk.Label(make,
                                 text=self.i18n("delete_cert_titles") % (
                                     self.i18n("msg_" + in_name), self.pick[in_name]),
                                 justify=tk.LEFT, wraplength=wrap)
            kill_tag.grid(row=0, column=0, columnspan=2, padx=20, pady=(15, 0), sticky=W)

            detail = self.i18n("delete_cert_detail")
            if in_name == "card":
                # 删卡同时会让本工具的备份还原失效：备份里不含 TPM 内的密钥
                detail = "%s\n\n%s" % (detail, self.i18n("delete_card_backup"))
            kill_tip = ttk.Label(make, bootstyle="danger", justify=tk.LEFT, wraplength=wrap,
                                 text=detail)
            kill_tip.grid(row=1, column=0, columnspan=2, padx=20, pady=(12, 0), sticky=W)
            kill_var = tk.BooleanVar()
            kill_yes = ttk.Checkbutton(make, text=self.i18n("delete_cert_checks") % self.i18n("msg_" + in_name),
                                       bootstyle="dark", command=checks, variable=kill_var)
            kill_yes.state(['!alternate'])
            kill_yes.grid(row=2, column=0, columnspan=2, padx=20, pady=(12, 0), sticky=W)

            cancel_b = ttk.Button(make, text=self.i18n("msg_cancel"),
                                  command=lambda: self.close_dialog(make), bootstyle="success")
            cancel_b.grid(row=3, column=0, padx=20, pady=15, sticky=W)
            submit_b = ttk.Button(make, text=self.i18n("msg_remove"), command=submit, bootstyle="danger")
            submit_b.grid(row=3, column=1, padx=20, pady=15, sticky=E)
            submit_b.config(state=tk.DISABLED)
            make.columnconfigure(1, weight=1)
            # 折行行数随语言与名称长度变化，按内容实测高度再定位一次
            make.update_idletasks()
            make.geometry("%dx%d+%d+%d" % (dialog_w, max(240, make.winfo_reqheight()),
                                           self.size[0], self.size[1]))

    def cert_import(self, flag="pfx"):
        sub = CertImport(flag, self.root, self)
        self.load_status()
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
                    um_tip.config(text="0-65536%s" % self.i18n("msg_char"))
                else:
                    um_txt.delete(0, tk.END)
                    um_txt.config(state=tk.DISABLED)
                    um_txt.config(bootstyle="default")
                    um_tip.config(text=self.i18n("msg_ml_text"))
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
                date_now = open_dt.entry.get().strip().split(" ")[0]
                date_end = stop_dt.entry.get().strip().split(" ")[0]
                full_text += 'RequestType = Cert\n'
                full_text += 'NotBefore = "%s 00:00"\n' % (date_now or
                                                           datetime.today().strftime("%Y/%m/%d"))
                full_text += 'NotAfter = "%s 00:00"\n' % (date_end or
                                                          (datetime.today() + timedelta(days=365)).strftime(
                                                              "%Y/%m/%d"))
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
                                    self.i18n("msg_error_ut"),
                                    self.i18n("msg_error_it") + "\n%s" % keyData)
                                make.attributes('-topmost', True)
                                return None

            # print(full_text)
            make.attributes('-topmost', False)
            file_path = "%s\\%s.inf" % (os.path.expandvars("%APPDATA%"),
                                        hashlib.sha256(full_text.encode()).hexdigest())
            # print(file_path)
            with open(file_path, 'w', encoding="utf8") as file_file:
                file_file.write(full_text)
            save_path = filedialog.asksaveasfilename(
                defaultextension=".csr",  # 默认文件扩展名
                # 文件类型过滤器
                filetypes=[(self.i18n("msg_dlg_csr_files"), "*.csr"),
                           (self.i18n("msg_dlg_all_files"), "*.*")],
                initialdir=os.path.expanduser("~"),  # 初始目录（展开 ~）
                initialfile="%s.csr" % cn,  # 初始文件名
                title=self.i18n("msg_dlg_save_as")  # 对话框标题
            )
            result = TPMSmartCard.createCSR(file_path, save_path)
            messagebox.showinfo(self.i18n("b_csr") + self.i18n("msg_create"), result)
            # make.attributes('-topmost', True)
            self.load_status()
            self.close_dialog(make)

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
                # 自定义 CSP 下拉框会增减一行内容，窗口大小跟着内容走
                size_window()

        # 各语言文案长短差异很大（英文/俄语等的勾选项文案可达中文的 2~3 倍），
        # 窗口尺寸在排版完成后按控件实测尺寸决定（见下方 make.mainloop 之前），
        # dialog_w/dialog_h 只是保底尺寸。
        dialog_w = 960 if self.wide else 800
        dialog_h = 540
        make = ttk.Toplevel(self.root)
        # 本窗口有 CSP 下拉框（会订阅主题频道），关闭前先取消订阅
        make.protocol("WM_DELETE_WINDOW", lambda: self.close_dialog(make))
        make.geometry("%dx%d" % (dialog_w, dialog_h))
        make.resizable(False, False)
        make.attributes('-topmost', True)
        make.title(self.i18n("msg_create") + self.i18n("msg_cert"))

        def text_width(in_text):
            """量出文案的显示宽度（勾选组折行时用来判断一行能放几项）。"""
            probe = ttk.Label(make, text=in_text)
            width = probe.winfo_reqwidth()
            probe.destroy()
            return width if width > 1 else self.t_fonts['label_data'].measure(in_text)

        def char_cells(in_text):
            """文案占多少个半角字符宽（CJK 等全角字符按 2 个算）。"""
            return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
                       for ch in in_text)

        def fit_width(in_text, in_min):
            """给 ttk 的 width：短文案沿用原宽度，长文案按实际长度放宽，避免文字被裁掉。"""
            return max(in_min, char_cells(in_text) + 1)

        # 勾选组（密钥用途 / 扩展用途）登记表：折行统一在 size_window 里按窗口实际宽度算
        groups = []

        def check_group(in_items, in_vars, in_row, in_style="primary", in_min=10):
            """把一组勾选项放进独立容器，返回 {词条键: 控件}。

            宽度只按文案放宽（不再用固定宽度裁字）；一行放几项、要不要折行由
            flow_group 在窗口宽度确定后计算，避免折成很窄的多行、右侧留一大片空白。
            """
            box = ttk.Frame(make)
            items = []
            widgets = dict()
            for name, text in in_items:
                item = ttk.Checkbutton(box, bootstyle=in_style, width=fit_width(text, in_min),
                                       text=text, variable=in_vars[name])
                item.state(['!alternate'])
                items.append(item)
                widgets[name] = item
            box.grid(column=1, row=in_row, padx=5, pady=10, sticky=W, columnspan=7)
            groups.append((box, items))
            return widgets

        def label_width():
            """第 0 列标签占用的宽度（文字 + 冒号 + 内边距）。"""
            return max(text_width(self.i18n(key) + ": ") for key in
                       ("user_name", "user_area", "user_on_t", "pub_length",
                        "key_usages", "msg_domain", "msg_emails", "DESCRIPTION",
                        "is_sign", "is_ca_t")) + 30

        def flow_group(in_box, in_items, in_width):
            """按可用宽度给勾选组折行。

            宽语言（拉丁/西里尔）按窗口实际宽度折行：每行尽量多放、行数最少、
            各行列数尽量均衡，列宽按该列最宽的项对齐（整齐的网格）。
            CJK 文案短，维持原来的一行排布（窗口按需要放宽）。
            """
            gap = 10
            for column in range(len(in_items)):
                in_box.columnconfigure(column, minsize=0, weight=0, uniform="")
                in_items[column].grid_forget()
            widths = [item.winfo_reqwidth() for item in in_items]
            base = in_width if self.wide else make.winfo_screenwidth() - 80
            # 可用宽度 = 窗口宽度 - 第 0 列标签；宽语言再留一点余量，
            # 让「刚好差一点点」的组也能保持一行（窗口随后会按其需要微调）
            room = (max(in_width, base) - label_width() - 30) * (1.05 if self.wide else 1.0)
            best = None
            for count in range(len(in_items), 0, -1):
                columns = [0] * count
                for index, width in enumerate(widths):
                    columns[index % count] = max(columns[index % count], width)
                if sum(columns) + gap * count > room:
                    continue
                lines = -(-len(in_items) // count)
                ideal = -(-len(in_items) // lines)
                key = (lines, abs(count - ideal))
                if best is None or key < best[0]:
                    best = (key, count, columns)
            per_line, columns = (best[1], best[2]) if best else (len(in_items), widths)
            for index, item in enumerate(in_items):
                item.grid(row=index // per_line, column=index % per_line,
                          padx=(0, gap), pady=3, sticky=W)
            for column, width in enumerate(columns):
                in_box.columnconfigure(column, minsize=width, weight=0)
            return per_line

        def size_window():
            """按控件实测尺寸确定窗口大小并定位。

            各语言文案长短差异很大，固定尺寸会把内容挤在格子里居中甚至裁掉；
            尺寸不低于保底值，且不超出屏幕可用范围。
            """
            # 先按「除勾选组以外」的各行定出窗口宽度，再据此给勾选组折行，
            # 最后按折行后的内容高度定窗口高度
            make.update_idletasks()
            win_w = min(max(dialog_w, make.winfo_reqwidth()), make.winfo_screenwidth() - 40)
            for box, items in groups:
                flow_group(box, items, win_w)
            make.update_idletasks()
            # 折行后勾选组可能比第一遍略宽（如 CJK 语言本来刚好一行），宽度再放一次，
            # 保证任何语言都不会被裁掉
            win_w = min(max(win_w, make.winfo_reqwidth()), make.winfo_screenwidth() - 40)
            win_h = min(max(dialog_h, make.winfo_reqheight()), make.winfo_screenheight() - 80)
            make.geometry("%dx%d+%d+%d" % (win_w, win_h, self.size[0], self.size[1]))

        cn_var = tk.StringVar()
        cn_var.trace('w', change)
        cn_tag = ttk.Label(make, text=self.i18n("user_name") + ": ")
        cn_tag.grid(column=0, row=0, pady=10, padx=15, sticky=W)
        cn_txt = ttk.Entry(make, bootstyle="info", width=83, textvariable=cn_var)
        # 输入框铺满所在列（其他语言下标签列更宽，固定宽度会在右侧留空白）
        cn_txt.grid(column=1, row=0, pady=10, padx=5, columnspan=6, sticky="ew")
        cn_tip = ttk.Label(make, text="%s1-64%s" % (self.i18n("msg_must_in"), self.i18n("msg_char")))
        cn_tip.grid(column=7, row=0, pady=10, padx=5, sticky=W)

        st_tag = ttk.Label(make, text=self.i18n("user_area") + ": ")
        st_tag.grid(column=0, row=1, pady=10, padx=15, sticky=W)
        st_txt = ttk.Entry(make, bootstyle="info", width=25)
        st_txt.grid(column=1, row=1, pady=10, padx=5, sticky="ew", columnspan=2)

        ll_tag = ttk.Label(make, text=self.i18n("user_city") + ": ")
        ll_tag.grid(column=3, row=1, pady=10, padx=15, sticky=W)
        ll_txt = ttk.Entry(make, bootstyle="info", width=25)
        ll_txt.grid(column=4, row=1, pady=10, padx=5, sticky="ew", columnspan=2)

        cc_tag = ttk.Label(make, text=self.i18n("user_code") + ": ")
        cc_tag.grid(column=6, row=1, pady=10, padx=15, sticky=W)
        cc_txt = ttk.Combobox(make, bootstyle="info", width=7, values=list(self.conf['cncode'].keys()))
        cc_txt.grid(column=7, row=1, pady=10, padx=5, sticky="ew", columnspan=2)
        cc_txt.set("N/A")

        on_tag = ttk.Label(make, text=self.i18n("user_on_t") + ": ")
        on_tag.grid(column=0, row=2, pady=10, padx=15, sticky=W)
        on_txt = ttk.Entry(make, bootstyle="info", width=35)
        on_txt.grid(column=1, row=2, pady=10, padx=5, sticky="ew", columnspan=3)

        ou_tag = ttk.Label(make, text=self.i18n("msg_ou_full") + ": ")
        ou_tag.grid(column=4, row=2, pady=10, padx=15, sticky=W)
        ou_txt = ttk.Entry(make, bootstyle="info", width=38)
        ou_txt.grid(column=5, row=2, pady=10, padx=5, sticky="ew", columnspan=3)

        kl_tag = ttk.Label(make, text=self.i18n("pub_length") + ": ")
        kl_tag.grid(column=0, row=3, pady=10, padx=15, sticky=W)
        kl_txt = ttk.Combobox(make, bootstyle="info", width=7, values=["RSA1024", "RSA2048"])
        kl_txt.grid(column=1, row=3, pady=10, padx=5, sticky=W)
        kl_txt.set("RSA2048")

        kl_sha = ttk.Combobox(make, bootstyle="info", width=7, values=["SHA1", "SHA256"])
        kl_sha.grid(column=2, row=3, pady=10, padx=5, sticky=W)
        kl_sha.set("SHA256")

        ks_tag = ttk.Label(make, text=self.i18n("msg_ks_full"))
        ks_tag.grid(column=3, row=3, pady=10, padx=15, sticky=W)
        v_sign = tk.IntVar()
        v_sign.set(1)
        v_sign.trace('w', change)
        # 固定宽度只按中文文案（8 个字宽）设计，英文等文案更长会被裁掉，
        # 这里按文案实际长度放宽
        k_sign = ttk.Checkbutton(make, bootstyle="success",
                                 width=fit_width(self.i18n('msg_sign'), 8),
                                 text=self.i18n('msg_sign'), variable=v_sign)
        k_sign.grid(column=4, row=3, pady=10, padx=5, sticky=W)
        k_sign.state(['!alternate'])
        k_sign.config(state=tk.DISABLED)
        v_data = tk.IntVar()
        v_data.set(1)
        v_data.trace('w', change)
        k_data = ttk.Checkbutton(make, bootstyle="success",
                                 width=fit_width(self.i18n('msg_data'), 8),
                                 text=self.i18n('msg_data'), variable=v_data)
        k_data.grid(column=5, row=3, pady=10, padx=5, sticky=W)
        k_data.state(['!alternate'])

        ml_tag = ttk.Label(make, text=self.i18n("msg_ml_lite"))
        ml_tag.grid(column=6, row=3, pady=10, padx=15, sticky=W)
        um_var = tk.IntVar()
        um_var.trace('w', change)
        m_sign = ttk.Checkbutton(make, bootstyle="info-round-toggle", text=self.i18n('msg_ml_full'),
                                 variable=um_var)
        m_sign.grid(column=7, row=3, pady=10, padx=5, sticky=W)

        ku_tag = ttk.Label(make, text=self.i18n("key_usages") + ": ")
        ku_tag.grid(column=0, row=4, pady=10, padx=15, sticky=W)
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
        ku_dat = check_group([(name, self.i18n(name)) for name in ku_key], ku_out, 4)

        dn_tag = ttk.Label(make, text=self.i18n("msg_domain") + ": ")
        dn_tag.grid(column=0, row=5, pady=10, padx=15, sticky=W)
        dn_txt = ttk.Entry(make, bootstyle="info", width=83)
        dn_txt.grid(column=1, row=5, pady=10, padx=5, columnspan=6, sticky="ew")
        dn_tip = ttk.Label(make, text="%s" % self.i18n("msg_splits"))
        dn_tip.grid(column=7, row=5, pady=10, padx=0, sticky=W)

        um_tag = ttk.Label(make, text=self.i18n("msg_emails") + ": ")
        um_tag.grid(column=0, row=6, pady=10, padx=15, sticky=W)
        um_txt = ttk.Entry(make, bootstyle="default", width=83)
        um_txt.grid(column=1, row=6, pady=10, padx=5, columnspan=6, sticky="ew")
        um_tip = ttk.Label(make, text=self.i18n("msg_ml_text"))
        um_tip.grid(column=7, row=6, pady=10, padx=0, sticky=W)
        um_txt.config(state=tk.DISABLED)

        dt_tag = ttk.Label(make, text=self.i18n("DESCRIPTION") + ": ")
        dt_tag.grid(column=0, row=7, pady=10, padx=15, sticky=W)
        dt_txt = ttk.Entry(make, bootstyle="info", width=83)
        dt_txt.grid(column=1, row=7, pady=10, padx=5, columnspan=6, sticky="ew")
        dt_tip = ttk.Label(make, text="0-65536%s" % self.i18n("msg_char"))
        dt_tip.grid(column=7, row=7, pady=10, padx=0, sticky=W)

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
        tg_self = ttk.Label(make, text=self.i18n("is_sign") + ": ")
        tg_self.grid(column=0, row=8, pady=20, padx=15, sticky=W)
        is_self = ttk.Checkbutton(make, bootstyle="info-round-toggle", text=self.i18n('is_self'), variable=va_self)
        is_self.grid(column=1, row=8, pady=10, padx=5, sticky=W)

        open_pt = ttk.Label(make, text=self.i18n("cert_open") + ": ")
        open_pt.grid(column=2, row=8, pady=10, padx=15, sticky=W)
        # 固定 %Y/%m/%d：ttkbootstrap.DateEntry 默认用 %x，
        # 在 C locale 下是 "10/12/26"，既无法做年份运算，也不能直接写进 INF
        open_dt = ttk.DateEntry(make, dateformat="%Y/%m/%d", style='success.TCalendar', width=15)
        open_dt.grid(column=3, row=8, pady=10, padx=15, columnspan=2, sticky="ew")
        open_dt.entry.config(state=tk.DISABLED)
        open_dt.button.config(state=tk.DISABLED)
        stop_pt = ttk.Label(make, text=self.i18n("cert_stop") + ": ")
        stop_pt.grid(column=5, row=8, pady=10, padx=15, sticky=W)
        stop_dt = ttk.DateEntry(make, dateformat="%Y/%m/%d", style='success.TCalendar', width=15)
        stop_dt.grid(column=6, row=8, pady=10, padx=15, columnspan=2, sticky="ew")
        date_tp = open_dt.entry.get().strip().split(" ")[0]
        try:
            date_tp = datetime.strptime(date_tp, "%Y/%m/%d") + timedelta(days=365)
        except ValueError:
            date_tp = datetime.today() + timedelta(days=365)
        date_tp = date_tp.strftime("%Y/%m/%d")
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
                                  text=self.i18n('is_ca_t'),
                                  variable=va_ca_t)
        is_ca_t.grid(column=0, row=9, pady=10, padx=5, sticky=W)

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
        for ext_name in ext_list:
            ext_out[ext_name] = tk.BooleanVar()
        ext_dat = check_group([(name, self.i18n(name)) for name in ext_list], ext_out, 9)
        resign()

        cancel_button = ttk.Button(make, text=self.i18n("msg_cancel"),
                                   command=lambda: self.close_dialog(make), bootstyle="danger")
        cancel_button.grid(column=0, row=10, pady=5, padx=15, sticky=W)
        submit_button = ttk.Button(make, text=self.i18n("msg_create_csr"), command=submit, bootstyle="success")
        submit_button.grid(column=7, row=10, pady=5, padx=0, sticky=W)
        submit_button.config(state=tk.DISABLED)
        v_csp_ts = tk.IntVar()
        v_csp_ts.set(0)
        v_csp_ts.trace('w', csp_ts)
        csp_sets = ttk.Checkbutton(make, bootstyle="info-round-toggle", text=self.i18n('csp_set_'),
                                   variable=v_csp_ts)
        csp_data = ttk.Combobox(make, bootstyle="info", width=62, values=list())
        csp_sets.grid(column=1, row=10, pady=5, padx=15, sticky=W)
        # csp_data.grid(column=2, row=10, pady=5, padx=15, sticky=W, columnspan=4)
        # 开窗：按控件实测尺寸确定窗口大小（见 size_window）
        size_window()
        make.mainloop()


if __name__ == "__main__":
    # 双击 .tsb 关联文件 / 登录自启时的工作目录不是程序目录，先切回程序根目录，
    # 后面所有相对路径（含第三方库与 subprocess 调用）才和常规启动一致
    ensure_workdir()
    app = SmartCardAPP()
