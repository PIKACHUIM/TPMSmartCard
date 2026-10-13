import hashlib
import os
import json
import re
import sys
import time
import random
import tkinter
import traceback
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
from Module.TPMSmartCard import TPMSmartCard
from Module import Theme
from Module import TPMBackup
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from SubApp.CertImport import CertImport
from SubApp.MoreConfig import MoreConfig
from SubApp.SystemSettings import SystemSettings

# 界面默认字体；语言包里的 _font 可为特定语言覆盖（如韩语需要 Hangul 字体）
FONT_NAME_DEFAULT = "MapleMono SC NF"

# 界面主题与配色来自 Config/themes.json（可在「系统设置 - 外观」里切换），
# 下面的常量是配置缺省或读取失败时的兜底值
THEME_NAME = os.environ.get("TPMSMART_THEME") or "yeti"
COLOR_HEAD_BG = "#eef2f7"      # 表格表头背景
COLOR_HEAD_FG = "#3c4a5a"      # 表格表头文字
COLOR_MUTED = "#66788a"        # 分组框标题等次要文字
FRAME_PAD = 13                 # 分组框内边距（内容区相对框体的内缩量）
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


class SmartCardAPP:
    def __init__(self):
        self.root = tk.Tk()
        self.conf = dict()
        self.read_config()
        # 界面语言：用户设置 > TPMSMART_LANG > 系统语言 > 默认（语言包见 Config/locales）
        self.i18n_data = get_i18n()
        self.lang = self.i18n_data.language
        # 设置主窗口宽度和高度
        self.root.geometry("1080x540")
        self.root.iconbitmap("Config/iconer/icon02.ico")
        self.size = self.get_screens()
        self.root.geometry(f"+{self.size[0]}+{self.size[1]}")
        self.data = SmartCardAPI()
        self.tpms = TPMSmartCard()
        pyglet.font.add_file("Config/myfont/MapleMono-SC-NF-Regular.ttf")
        pyglet.font.add_file("Config/myfont/NotoSerifCJKsc-Regular.otf")
        self.pick = {
            "card": "",
            "cert": ""
        }
        self.setup_fonts()
        self.build_ui()
        self.check_datas()
        self.load_status()
        self.root.mainloop()

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
        if self.tables["cert_main"][0] is not None:
            self.tables["cert_main"][0].bind('<<TreeviewSelect>>', self.cert_select)
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
        self.hints = {
            "card_info": self.view_hint("card_info", "msg_hint_card"),
            "cert_info": self.view_hint("cert_info", "msg_hint_cert"),
        }

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
            child.destroy()
        self.lang = self.i18n_data.language
        self.pick = {
            "card": "",
            "cert": ""
        }
        self.setup_fonts(in_create=False)
        self.build_ui()
        self.load_status()

    def check_datas(self):
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
        # 界面文案已独立到 Config/locales，这里的配置只负责布局与表格列
        for conf_name in ["tables", "frames", "button",
                          "labels", "cncode"]:
            with open("Config/%s.json" % conf_name, "r",
                      encoding="utf8") as conf_file:
                conf_data = conf_file.read()
                self.conf[conf_name] = json.loads(conf_data)

    def load_status(self):
        self.data.readInfo()
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
        self.toggle_frame("cert_user", False)
        self.toggle_frame("cert_last", False)
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
                else:
                    cert_name = self.i18n("msg_no_cert")
                    # 证书解析失败(sc_cert 为 None)或无 CN(SAN 证书)时保持默认文案
                    owners = getattr(self.data.certs[cert_now].sc_cert, "OwnersInfo", None)
                    if owners and owners.get("CN"):
                        cert_name = owners["CN"]
                self.tables["cert_main"][0].insert("", tk.END, values=(
                    cert_now.split(' ')[-1],
                    cert_name,
                    self.data.certs[cert_now].sc_exec,
                    self.data.certs[cert_now].sc_keys
                ))

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
        """取某个块的上下边界；``table:``/``frame:`` 对应已有控件，``end:`` 为框内底部。"""
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
            return frame.winfo_y() + frame.winfo_height() - FRAME_PAD
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

    def toggle_frame(self, in_name, in_visible):
        """显示/隐藏某个分组框（未选中证书时「使用者/颁发者」整体不显示）。"""
        frame_now = self.frames.get(in_name)
        conf_now = (self.conf.get('frames') or {}).get(in_name)
        if frame_now is None or not conf_now:
            return None
        if in_visible:
            frame_now.place(x=conf_now[2], y=conf_now[3])
        else:
            frame_now.place_forget()
        return None

    def card_select(self, event):
        treeview = event.widget
        selected_item = treeview.selection()
        # 有选中卡片才显示详情标签，否则只留一行提示
        self.toggle_labels("card_info", len(selected_item) > 0)
        if len(selected_item) > 0:
            selected_name = treeview.set(selected_item[0], '#2')
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
        out_dir = filedialog.askdirectory(title=self.i18n("msg_bak_dir"),
                                          initialdir=os.path.expanduser("~"))
        if not out_dir:
            return None
        try:
            report = TPMBackup.create_backup(out_dir,
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
        result = self.i18n("msg_bak_ok") % (report["dir"],
                                           str(report["file_count"]),
                                           TPMBackup.human_size(report["size"]),
                                           str(report["reg_count"]))
        if report.get("warning"):
            result += "\n\n" + report["warning"]
        messagebox.showinfo(self.i18n("msg_bak_title"), result)
        return None

    def card_restore(self):
        """从备份目录还原虚拟智能卡（回写卡片数据目录并导入注册表）。

        注意：卡片私钥由 TPM 保护，备份只在同一台电脑且同一 TPM（未清除）上可还原。
        """
        if not TPMBackup.is_admin():
            messagebox.showwarning(self.i18n("warn"), self.i18n("msg_bak_admin"))
            return None
        package = filedialog.askdirectory(title=self.i18n("msg_rec_dir"),
                                          initialdir=os.path.expanduser("~"))
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
        try:
            report = TPMBackup.restore_backup(package)
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
        messagebox.showinfo(self.i18n("msg_rec_title"), result)
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
                        initialdir="~",  # 初始目录，对于Windows系统，你可能想要设置为os.path.expanduser('~')
                        initialfile="%s.crt" % str(now_cert.sc_cert.SerialNums),  # 初始文件名
                        title=self.i18n("msg_dlg_save_as")  # 对话框标题
                    )
                else:
                    in_path = "%s\\%s.crt" % (in_path, str(now_cert.sc_cert.SerialNums))
                if in_path is None or len(in_path) <= 0:
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

    def cert_select(self, event):
        treeview = event.widget
        selected_item = treeview.selection()
        for item_name in ["cert_info", "cert_user", "cert_last"]:
            for fill_name in self.labels[item_name]:
                self.labels[item_name][fill_name][1].config(text="")
        # 有选中证书才显示详情，否则只留一行提示（使用者/颁发者整体不显示）
        has_cert = len(selected_item) > 0
        for toggle_name in ["cert_info", "cert_user", "cert_last"]:
            self.toggle_labels(toggle_name, has_cert)
        self.toggle_frame("cert_user", has_cert)
        self.toggle_frame("cert_last", has_cert)
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

                        "key_usages": str(cert_now.MainUsages)[:86] + "..." \
                            if len(str(cert_now.MainUsages)) >= 86 else cert_now.MainUsages,
                        "sub_usages": str(cert_now.SubsUsages)[:86] + "..." \
                            if len(str(cert_now.SubsUsages)) >= 86 else cert_now.SubsUsages,
                        "key_identy": str(cert_now.MainHashID).replace(":", ""),
                        "sub_identy": str(cert_now.SubsHashID).replace(":", ""),
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
            card_uid = self.pick["card"].split(" ")[-1]
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
                make.destroy()

        make = ttk.Toplevel(self.root)
        make.geometry("700x200")
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

        cancel_button = ttk.Button(make, text=self.i18n("msg_cancel"), command=make.destroy, bootstyle="danger")
        cancel_button.grid(column=0, row=4, pady=5, padx=15)
        submit_button = ttk.Button(make, text=self.i18n("msg_confirm"), command=submit, bootstyle="info")
        submit_button.grid(column=2, row=4, pady=5, padx=0)
        submit_button.config(state=tk.DISABLED)
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
                        make.destroy()
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
            make.destroy()

        make = ttk.Toplevel(self.root)
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
                make.destroy()
                if len(result) > 0:
                    if in_name == "cert":
                        result += self.i18n("delete_cert_reboot")
                    messagebox.showinfo(self.i18n("msg_remove") + self.i18n("msg_result"), result)

            def checks():
                if kill_var.get():
                    submit_b.config(state=tk.NORMAL)
                else:
                    submit_b.config(state=tk.DISABLED)

            kill_tag = ttk.Label(make,
                                 text=self.i18n("delete_cert_titles") % (
                                     self.i18n("msg_" + in_name), self.pick[in_name]))
            kill_tag.place(x=20, y=10)

            kill_tip = ttk.Label(make, bootstyle="danger",
                                 text=self.i18n("delete_cert_detail"))
            kill_tip.place(x=20, y=80)
            kill_var = tk.BooleanVar()
            kill_yes = ttk.Checkbutton(make, text=self.i18n("delete_cert_checks") % self.i18n("msg_" + in_name),
                                       bootstyle="dark", command=checks, variable=kill_var)
            kill_yes.state(['!alternate'])
            kill_yes.place(x=20, y=130)

            cancel_b = ttk.Button(make, text=self.i18n("msg_cancel"), command=make.destroy, bootstyle="success")
            cancel_b.place(x=20, y=180)
            submit_b = ttk.Button(make, text=self.i18n("msg_remove"), command=submit, bootstyle="danger")
            submit_b.place(x=230, y=180)
            submit_b.config(state=tk.DISABLED)

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
                initialdir="~",  # 初始目录
                initialfile="%s.csr" % cn,  # 初始文件名
                title=self.i18n("msg_dlg_save_as")  # 对话框标题
            )
            result = TPMSmartCard.createCSR(file_path, save_path)
            messagebox.showinfo(self.i18n("b_csr") + self.i18n("msg_create"), result)
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
        make.title(self.i18n("msg_create") + self.i18n("msg_cert"))

        cn_var = tk.StringVar()
        cn_var.trace('w', change)
        cn_tag = ttk.Label(make, text=self.i18n("user_name") + ": ")
        cn_tag.grid(column=0, row=0, pady=10, padx=15)
        cn_txt = ttk.Entry(make, bootstyle="info", width=83, textvariable=cn_var)
        cn_txt.grid(column=1, row=0, pady=10, padx=5, columnspan=6)
        cn_tip = ttk.Label(make, text="%s1-64%s" % (self.i18n("msg_must_in"), self.i18n("msg_char")))
        cn_tip.grid(column=7, row=0, pady=10, padx=5)

        st_tag = ttk.Label(make, text=self.i18n("user_area") + ": ")
        st_tag.grid(column=0, row=1, pady=10, padx=15, sticky=W)
        st_txt = ttk.Entry(make, bootstyle="info", width=25)
        st_txt.grid(column=1, row=1, pady=10, padx=5, sticky=W, columnspan=2)

        ll_tag = ttk.Label(make, text=self.i18n("user_city") + ": ")
        ll_tag.grid(column=3, row=1, pady=10, padx=15, sticky=W)
        ll_txt = ttk.Entry(make, bootstyle="info", width=25)
        ll_txt.grid(column=4, row=1, pady=10, padx=5, sticky=W, columnspan=2)

        cc_tag = ttk.Label(make, text=self.i18n("user_code") + ": ")
        cc_tag.grid(column=6, row=1, pady=10, padx=15)
        cc_txt = ttk.Combobox(make, bootstyle="info", width=7, values=list(self.conf['cncode'].keys()))
        cc_txt.grid(column=7, row=1, pady=10, padx=5, sticky=W, columnspan=2)
        cc_txt.set("N/A")

        on_tag = ttk.Label(make, text=self.i18n("user_on_t") + ": ")
        on_tag.grid(column=0, row=2, pady=10, padx=15, sticky=W)
        on_txt = ttk.Entry(make, bootstyle="info", width=35)
        on_txt.grid(column=1, row=2, pady=10, padx=5, sticky=W, columnspan=3)

        ou_tag = ttk.Label(make, text=self.i18n("msg_ou_full") + ": ")
        ou_tag.grid(column=4, row=2, pady=10, padx=15, sticky=W)
        ou_txt = ttk.Entry(make, bootstyle="info", width=38)
        ou_txt.grid(column=5, row=2, pady=10, padx=5, sticky=W, columnspan=3)

        kl_tag = ttk.Label(make, text=self.i18n("pub_length") + ": ")
        kl_tag.grid(column=0, row=3, pady=10, padx=15)
        kl_txt = ttk.Combobox(make, bootstyle="info", width=7, values=["RSA1024", "RSA2048"])
        kl_txt.grid(column=1, row=3, pady=10, padx=5, sticky=W)
        kl_txt.set("RSA2048")

        kl_sha = ttk.Combobox(make, bootstyle="info", width=7, values=["SHA1", "SHA256"])
        kl_sha.grid(column=2, row=3, pady=10, padx=5, sticky=W)
        kl_sha.set("SHA256")

        ks_tag = ttk.Label(make, text=self.i18n("msg_ks_full"))
        ks_tag.grid(column=3, row=3, pady=10, padx=15)
        v_sign = tk.IntVar()
        v_sign.set(1)
        v_sign.trace('w', change)
        k_sign = ttk.Checkbutton(make, bootstyle="success", width=8, text=self.i18n('msg_sign'),
                                 variable=v_sign)
        k_sign.grid(column=4, row=3, pady=10, padx=5, sticky=W)
        k_sign.state(['!alternate'])
        k_sign.config(state=tk.DISABLED)
        v_data = tk.IntVar()
        v_data.set(1)
        v_data.trace('w', change)
        k_data = ttk.Checkbutton(make, bootstyle="success", width=8, text=self.i18n('msg_data'),
                                 variable=v_data)
        k_data.grid(column=5, row=3, pady=10, padx=5, sticky=W)
        k_data.state(['!alternate'])

        ml_tag = ttk.Label(make, text=self.i18n("msg_ml_lite"))
        ml_tag.grid(column=6, row=3, pady=10, padx=15)
        um_var = tk.IntVar()
        um_var.trace('w', change)
        m_sign = ttk.Checkbutton(make, bootstyle="info-round-toggle", text=self.i18n('msg_ml_full'),
                                 variable=um_var)
        m_sign.grid(column=7, row=3, pady=10, padx=5, sticky=W)

        ku_tag = ttk.Label(make, text=self.i18n("key_usages") + ": ")
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
            ku_dat[ku_inf] = ttk.Checkbutton(make, bootstyle="primary", width=10, text=self.i18n(ku_inf),
                                             variable=ku_out[ku_inf])
            ku_dat[ku_inf].grid(column=ku_num, row=4, padx=8 if ku_inf == "DecipherOnly" else 5)
            ku_num += 1
            ku_dat[ku_inf].state(['!alternate'])

        dn_tag = ttk.Label(make, text=self.i18n("msg_domain") + ": ")
        dn_tag.grid(column=0, row=5, pady=10, padx=15)
        dn_txt = ttk.Entry(make, bootstyle="info", width=83)
        dn_txt.grid(column=1, row=5, pady=10, padx=5, columnspan=6)
        dn_tip = ttk.Label(make, text="%s" % self.i18n("msg_splits"))
        dn_tip.grid(column=7, row=5, pady=10, padx=0)

        um_tag = ttk.Label(make, text=self.i18n("msg_emails") + ": ")
        um_tag.grid(column=0, row=6, pady=10, padx=15)
        um_txt = ttk.Entry(make, bootstyle="default", width=83)
        um_txt.grid(column=1, row=6, pady=10, padx=5, columnspan=6)
        um_tip = ttk.Label(make, text=self.i18n("msg_ml_text"))
        um_tip.grid(column=7, row=6, pady=10, padx=0)
        um_txt.config(state=tk.DISABLED)

        dt_tag = ttk.Label(make, text=self.i18n("DESCRIPTION") + ": ")
        dt_tag.grid(column=0, row=7, pady=10, padx=15)
        dt_txt = ttk.Entry(make, bootstyle="info", width=83)
        dt_txt.grid(column=1, row=7, pady=10, padx=5, columnspan=6)
        dt_tip = ttk.Label(make, text="0-65536%s" % self.i18n("msg_char"))
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
        tg_self = ttk.Label(make, text=self.i18n("is_sign") + ": ")
        tg_self.grid(column=0, row=8, pady=20, padx=15)
        is_self = ttk.Checkbutton(make, bootstyle="info-round-toggle", text=self.i18n('is_self'), variable=va_self)
        is_self.grid(column=1, row=8, pady=10, padx=5)

        open_pt = ttk.Label(make, text=self.i18n("cert_open") + ": ")
        open_pt.grid(column=2, row=8, pady=10, padx=15)
        # 固定 %Y/%m/%d：ttkbootstrap.DateEntry 默认用 %x，
        # 在 C locale 下是 "10/12/26"，既无法做年份运算，也不能直接写进 INF
        open_dt = ttk.DateEntry(make, dateformat="%Y/%m/%d", style='success.TCalendar', width=15)
        open_dt.grid(column=3, row=8, pady=10, padx=15, columnspan=2)
        open_dt.entry.config(state=tk.DISABLED)
        open_dt.button.config(state=tk.DISABLED)
        stop_pt = ttk.Label(make, text=self.i18n("cert_stop") + ": ")
        stop_pt.grid(column=5, row=8, pady=10, padx=15)
        stop_dt = ttk.DateEntry(make, dateformat="%Y/%m/%d", style='success.TCalendar', width=15)
        stop_dt.grid(column=6, row=8, pady=10, padx=15, columnspan=2)
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
            ext_dat[ext_name] = ttk.Checkbutton(make, bootstyle="primary", width=10, text=self.i18n(ext_name),
                                                variable=ext_out[ext_name])
            ext_dat[ext_name].grid(column=ext_num, row=9, padx=5)
            ext_num += 1
            ext_dat[ext_name].state(['!alternate'])
        resign()

        cancel_button = ttk.Button(make, text=self.i18n("msg_cancel"), command=make.destroy, bootstyle="danger")
        cancel_button.grid(column=0, row=10, pady=5, padx=15)
        submit_button = ttk.Button(make, text=self.i18n("msg_create_csr"), command=submit, bootstyle="success")
        submit_button.grid(column=7, row=10, pady=5, padx=0)
        submit_button.config(state=tk.DISABLED)
        v_csp_ts = tk.IntVar()
        v_csp_ts.set(0)
        v_csp_ts.trace('w', csp_ts)
        csp_sets = ttk.Checkbutton(make, bootstyle="info-round-toggle", text=self.i18n('csp_set_'),
                                   variable=v_csp_ts)
        csp_data = ttk.Combobox(make, bootstyle="info", width=62, values=list())
        csp_sets.grid(column=1, row=10, pady=5, padx=15, sticky=W)
        # csp_data.grid(column=2, row=10, pady=5, padx=15, sticky=W, columnspan=4)
        make.mainloop()


if __name__ == "__main__":
    app = SmartCardAPP()
