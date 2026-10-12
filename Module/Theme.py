# -*- coding: utf-8 -*-
"""界面主题：可选「原版主题」与若干美化配色（配置见 Config/themes.json）。

* 主题以配置为准，新增一套配色只需在 themes.json 里加一个 profile；
* 用户选择保存在用户目录的 settings.json 中（与语言偏好同一个文件），
  切换主题后由主界面重建控件生效，无需重启程序。
"""

import json

from Module.I18n import read_user_settings, write_user_settings

# 主题配置文件（相对程序根目录，与 Config 下其它布局配置一致）
THEME_FILE = "Config/themes.json"

_cache = None


def load():
    """读取主题配置（带缓存），返回 ``(顺序列表, 主题字典)``。"""
    global _cache
    if _cache is None:
        order, profiles, default = [], {}, ""
        try:
            with open(THEME_FILE, "r", encoding="utf-8") as handle:
                data = json.loads(handle.read())
            profiles = data.get("profiles") or {}
            order = [key for key in (data.get("order") or sorted(profiles)) if key in profiles]
            default = data.get("default") or ""
        except Exception as err:
            print("Theme: 读取主题配置失败:", err)
        if not profiles:
            # 配置缺失时退回 ttkbootstrap 默认主题，保证程序可用
            profiles = {"default": {"name": "theme_yeti", "theme": "yeti"}}
            order = ["default"]
        if default not in profiles:
            default = order[0]
        _cache = (order, profiles, default)
    return _cache


def available():
    """``[(主题键, 主题配置)]``，顺序与配置文件一致。"""
    order, profiles, _ = load()
    return [(key, profiles[key]) for key in order]


def current_key():
    """当前主题键：用户设置 > 配置默认值。"""
    order, profiles, default = load()
    saved = read_user_settings().get("theme")
    if saved in profiles:
        return saved
    return default if default in profiles else order[0]


def current():
    """当前主题配置（额外带 ``key`` 字段）。"""
    order, profiles, _ = load()
    key = current_key()
    profile = dict(profiles.get(key, {}))
    profile["key"] = key
    return profile


def set_current(key):
    """记住用户选择的主题；失败时返回 False（不影响程序运行）。"""
    order, profiles, _ = load()
    if key not in profiles:
        return False
    settings = read_user_settings()
    settings["theme"] = key
    return write_user_settings(settings)
