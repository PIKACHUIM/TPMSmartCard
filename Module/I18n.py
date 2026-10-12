# -*- coding: utf-8 -*-
"""多语言（i18n）核心模块 —— 桌面端（Tkinter）与 Web 端（Flask）共用一套语言包。

设计约定
--------
* 语言包目录：``Config/locales/<语言代码>.json``，一个语言一个文件。
* 语言代码使用 BCP-47 风格：``zh-Hans`` / ``zh-Hant`` / ``en`` / ``ja`` / ``ko`` /
  ``fr`` / ``de`` / ``es`` / ``it`` / ``pt`` / ``ru`` ...（大小写与 ``_`` 会被自动规范化）。
* 文件内容是一张扁平表：键 -> 字符串（也可以是字符串数组，按顺序拼接，方便排版多行文案）。
* 以 ``_`` 开头的键是元数据，不参与翻译查找：

  ``_name``     语言自身的显示名（如 ``Nederlands``），显示在语言选择框里
  ``_font``     该语言使用的界面字体（缺省沿用主程序字体）
  ``_wide``     该语言是否需要更宽的窗口（布尔值，缺省按 CJK 判断）
  ``_extends``  继承的语言代码，先加载被继承的语言再用本文件的键覆盖

查找顺序（逐级回退，保证任何语言缺词条时都不会把内部键名显示给用户）::

    用户选择 > TPMSMART_LANG 环境变量 > 系统语言 > 默认语言(zh-Hans) > 英文(en) > 键名本身

扩展翻译
--------
新增一种语言：把 ``xx.json`` 放进 ``Config/locales/``，程序与语言选择框会自动发现，
无需改动任何代码。也可以只写差异部分并声明 ``"_extends": "en"`` 增量翻译。
另可用 ``TPMSMART_LOCALE_DIR`` 指向外部语言包目录，``TPMSMART_HOME`` 指向程序根目录。

命令行自检::

    python -m Module.I18n            # 列出所有语言与词条数量
    python -m Module.I18n --check     # 检查各语言相对默认语言缺失/多余的词条
"""

from __future__ import annotations

import json
import locale
import os
import sys
import threading
import warnings

# 默认语言（词条最完整，作为最终回退）与兜底语言
DEFAULT_LANGUAGE = "zh-Hans"
FALLBACK_LANGUAGE = "en"

# 内置语言的展示顺序（未出现在此表中的新语言按代码排序追加在后面）
LANGUAGE_ORDER = [
    "zh-Hans", "zh-Hant", "en", "ja", "ko", "fr", "de", "es", "it", "pt", "ru",
]

# 语言的本地名称，用于语言选择框（语言包可用 _name 覆盖）
LANGUAGE_LABELS = {
    "zh-Hans": "简体中文",
    "zh-Hant": "繁體中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "it": "Italiano",
    "pt": "Português",
    "ru": "Русский",
}

# CJK 语言（字形为全角，界面留白可以更紧凑）
CJK_LANGUAGES = ("zh-Hans", "zh-Hant", "ja", "ko")

# 语言代码别名 / 常见区域变体 -> 规范化语言代码
_ALIASES = {
    "zh": "zh-Hans", "zh-cn": "zh-Hans", "zh-sg": "zh-Hans", "zh-my": "zh-Hans",
    "zh-hans": "zh-Hans", "cn": "zh-Hans", "chs": "zh-Hans", "chinese": "zh-Hans",
    "zh-tw": "zh-Hant", "zh-hk": "zh-Hant", "zh-mo": "zh-Hant",
    "zh-hant": "zh-Hant", "cht": "zh-Hant", "tw": "zh-Hant",
    "ja-jp": "ja", "jp": "ja",
    "ko-kr": "ko", "kr": "ko",
    "en-us": "en", "en-gb": "en", "en-au": "en", "en-ca": "en",
    "fr-fr": "fr", "fr-ca": "fr",
    "de-de": "de", "de-at": "de", "de-ch": "de",
    "es-es": "es", "es-mx": "es", "es-ar": "es",
    "it-it": "it",
    "pt-br": "pt", "pt-pt": "pt",
    "ru-ru": "ru",
}

# Windows 下 locale.getlocale() 返回的是显示名（如 "Chinese (Traditional)_Taiwan"）
_DISPLAY_NAME_HINTS = (
    ("chinese (traditional)", "zh-Hant"),
    ("chinese (simplified)", "zh-Hans"),
    ("chinese", "zh-Hans"),
    ("japanese", "ja"),
    ("korean", "ko"),
    ("french", "fr"),
    ("german", "de"),
    ("spanish", "es"),
    ("italian", "it"),
    ("portuguese", "pt"),
    ("russian", "ru"),
    ("english", "en"),
)

# 各语言建议的界面字体（Windows 自带字体优先，避免缺字显示成方框）
_DEFAULT_FONT_OVERRIDES = {
    # Hangul 不在主程序自带字体里，缺省用系统韩文字体
    "ko": "Malgun Gothic",
}

_LOCK = threading.RLock()
_CACHE = {}          # 语言代码 -> 已合并（含 _extends）的词条字典
_LOADING = set()     # 正在加载的语言，用于阻断 _extends 循环
_I18N = None         # 当前语言管理器（单例）


# --------------------------------------------------------------------------- #
# 路径与设置
# --------------------------------------------------------------------------- #
def project_root():
    """程序根目录（存在 Config 子目录的那个目录）。"""
    override = os.environ.get("TPMSMART_HOME")
    if override and os.path.isdir(override):
        return os.path.abspath(override)
    if getattr(sys, "frozen", False):
        # cx_Freeze / PyInstaller 打包后以可执行文件所在目录为准
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        if os.path.isdir(os.path.join(exe_dir, "Config")):
            return exe_dir
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    if os.path.isdir(os.path.join(root, "Config")):
        return root
    return os.getcwd()


def locales_dir():
    """语言包目录，可用环境变量 TPMSMART_LOCALE_DIR 覆盖以加载外部翻译。"""
    override = os.environ.get("TPMSMART_LOCALE_DIR")
    if override and os.path.isdir(override):
        return os.path.abspath(override)
    return os.path.join(project_root(), "Config", "locales")


def legacy_locales_file():
    """旧版把 zh/en 放在 Config/global.json 中，语言包目录缺失时回退到它。"""
    return os.path.join(project_root(), "Config", "global.json")


def settings_path():
    """用户配置文件（记录语言偏好），写在用户目录，避免受安装目录权限影响。"""
    base = os.environ.get("APPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "TPMSmartCard", "settings.json")


def read_user_settings():
    try:
        with open(settings_path(), "r", encoding="utf-8") as handle:
            data = json.loads(handle.read())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_user_settings(settings):
    path = settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(settings, ensure_ascii=False, indent=2))
        return True
    except Exception as err:
        print("I18n: 保存语言设置失败:", err)
        return False


def read_user_language():
    return normalize_language(read_user_settings().get("language"))


def write_user_language(code):
    settings = read_user_settings()
    settings["language"] = code
    return write_user_settings(settings)


# --------------------------------------------------------------------------- #
# 语言代码
# --------------------------------------------------------------------------- #
def normalize_language(code):
    """把任意写法的语言代码规范化成语言包使用的形式；无法识别时返回空字符串。"""
    if not code:
        return ""
    text = str(code).strip().replace("_", "-").lower()
    if not text:
        return ""
    if text in _ALIASES:
        return _ALIASES[text]
    for known in LANGUAGE_ORDER:
        if known.lower() == text:
            return known
    # 未内置的语言：按 "xx-YY" 形式保留，供外部语言包使用
    parts = [part for part in text.split("-") if part]
    if not parts:
        return ""
    base = parts[0]
    if len(parts) == 1:
        return _ALIASES.get(base, base)
    if base == "zh":
        return "zh-Hant" if parts[1] in ("tw", "hk", "mo", "hant") else "zh-Hans"
    return _ALIASES.get(text, "%s-%s" % (base, parts[1].upper()))


def _match_language(raw):
    """把系统语言（可能是显示名、POSIX 代码或区域代码）匹配成语言代码。"""
    if not raw:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    lowered = text.lower()
    for hint, code in _DISPLAY_NAME_HINTS:
        if hint in lowered:
            return code
    return normalize_language(text.split(".")[0].split("@")[0])


def _default_locale_name():
    """locale.getdefaultlocale() 在 3.15 起被移除，这里屏蔽告警后继续复用其探测能力。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return locale.getdefaultlocale()[0]


def detect_system_language():
    """按 环境变量 > 当前 locale > 默认 locale 的顺序推断系统语言。"""
    explicit = os.environ.get("TPMSMART_LANG")
    if explicit:
        code = normalize_language(explicit)
        if code:
            return code
    candidates = []
    for getter in (lambda: locale.getlocale()[0], _default_locale_name):
        try:
            candidates.append(getter())
        except Exception:
            pass
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name)
        if value:
            candidates.append(value)
    for raw in candidates:
        code = _match_language(raw)
        if code:
            return code
    return DEFAULT_LANGUAGE


# --------------------------------------------------------------------------- #
# 语言包加载
# --------------------------------------------------------------------------- #
def locale_path(code):
    code = normalize_language(code)
    if not code:
        return ""
    path = os.path.join(locales_dir(), "%s.json" % code)
    return path if os.path.isfile(path) else ""


def available_languages():
    """扫描语言包目录，返回可用的语言代码列表（顺序稳定，便于界面展示）。"""
    found = []
    directory = locales_dir()
    if os.path.isdir(directory):
        for name in os.listdir(directory):
            if not name.lower().endswith(".json"):
                continue
            code = normalize_language(name[:-5])
            if code and code not in found:
                found.append(code)
    if not found:
        # 兼容旧版：Config/global.json 里的顶层键即为语言代码
        legacy = legacy_locales_file()
        if os.path.isfile(legacy):
            try:
                with open(legacy, "r", encoding="utf-8") as handle:
                    found = [normalize_language(key) for key in json.loads(handle.read())]
                found = [code for code in found if code]
            except Exception as err:
                print("I18n: 读取旧版语言文件失败:", err)
                found = []
    if DEFAULT_LANGUAGE not in found:
        found.append(DEFAULT_LANGUAGE)
    known = [code for code in LANGUAGE_ORDER if code in found]
    others = sorted(code for code in found if code not in LANGUAGE_ORDER)
    return known + others


def _read_locale_file(code):
    path = locale_path(code)
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.loads(handle.read())
        if isinstance(data, dict):
            return data
        print("I18n: 语言包 %s 的顶层必须是对象" % path)
        return {}
    # 没有独立语言包时，退回旧版 Config/global.json
    legacy = legacy_locales_file()
    if os.path.isfile(legacy):
        try:
            with open(legacy, "r", encoding="utf-8") as handle:
                data = json.loads(handle.read())
            if isinstance(data, dict):
                for key, value in data.items():
                    if normalize_language(key) == code and isinstance(value, dict):
                        return value
        except Exception as err:
            print("I18n: 读取旧版语言文件失败:", err)
    return {}


def load_locale(code):
    """加载语言包（带缓存），并按 _extends 合并被继承语言的词条。"""
    code = normalize_language(code)
    if not code:
        return {}
    with _LOCK:
        if code in _CACHE:
            return _CACHE[code]
        if code in _LOADING:
            return {}
        _LOADING.add(code)
        try:
            raw = _read_locale_file(code)
            data = {}
            parent = normalize_language(raw.get("_extends"))
            if parent and parent != code:
                data.update(load_locale(parent))
            data.update(raw)
            _CACHE[code] = data
            return data
        except Exception as err:
            print("I18n: 加载语言包 %s 失败: %s" % (code, err))
            _CACHE[code] = {}
            return {}
        finally:
            _LOADING.discard(code)


def reload_locales():
    """清空缓存（修改语言包后无需重启即可生效，供调试/翻译使用）。"""
    with _LOCK:
        _CACHE.clear()


def available_keys(code=DEFAULT_LANGUAGE):
    return sorted(key for key in load_locale(code) if not key.startswith("_"))


def language_label(code):
    """语言在界面上的显示名：优先语言包里的 _name，其次内置名称，最后用代码。"""
    code = normalize_language(code)
    name = load_locale(code).get("_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return LANGUAGE_LABELS.get(code, code)


def is_cjk_language(code):
    if code in CJK_LANGUAGES:
        return True
    return str(normalize_language(code) or "").startswith("zh")


def is_wide_language(code):
    """是否需要更宽的行控件（拉丁/西里尔字母比汉字占位更宽）。"""
    meta = load_locale(code).get("_wide")
    if isinstance(meta, bool):
        return meta
    return not is_cjk_language(code)


def ui_font(code, default):
    """该语言建议的界面字体；语言包里的 _font 优先级最高，便于外部扩展。"""
    override = load_locale(code).get("_font")
    if isinstance(override, str) and override.strip():
        return override.strip()
    return _DEFAULT_FONT_OVERRIDES.get(normalize_language(code), default)


def language_from_header(header, default=None):
    """从 Accept-Language 请求头挑选最合适的语言（按 q 值排序），供 Web 端使用。"""
    available = available_languages()
    fallback = default or (available[0] if available else DEFAULT_LANGUAGE)
    if not header:
        return fallback
    candidates = []
    for index, part in enumerate(str(header).split(",")):
        part = part.strip()
        if not part:
            continue
        tag, _, params = part.partition(";")
        quality = 1.0
        for item in params.split(";"):
            name, _, value = item.partition("=")
            if name.strip().lower() == "q" and value.strip():
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        candidates.append((-quality, index, tag.strip()))
    for _, _, tag in sorted(candidates):
        if tag == "*":
            return fallback
        code = normalize_language(tag.split(".")[0])
        if code in available:
            return code
        # 区域变体（如 de-AT）退回基础语言
        base = normalize_language(str(tag).split("-")[0])
        if base in available:
            return base
    return fallback


def _fallback_chain(code):
    chain = []

    def add(candidate):
        candidate = normalize_language(candidate)
        if candidate and candidate not in chain:
            chain.append(candidate)

    add(code)
    text = str(code or "")
    if text.startswith("zh"):
        # 简繁互为回退：任一侧缺词条时仍能用中文显示
        add("zh-Hant" if text.startswith("zh-Hant") else "zh-Hans")
    add(text.split("-")[0] if "-" in text else "")
    add(FALLBACK_LANGUAGE)
    add(DEFAULT_LANGUAGE)
    return chain


# --------------------------------------------------------------------------- #
# 翻译器
# --------------------------------------------------------------------------- #
class Translator:
    """绑定到某一语言的翻译器，t()/tp() 会自动做多级回退。"""

    def __init__(self, language):
        self.language = normalize_language(language) or DEFAULT_LANGUAGE

    def raw(self, key, default=None):
        for code in _fallback_chain(self.language):
            data = load_locale(code)
            if key in data:
                return data[key]
        return default

    def t(self, key, default=None):
        value = self.raw(key, None)
        if value is None:
            return default if default is not None else key
        if isinstance(value, (list, tuple)):
            return "".join(str(item) for item in value)
        return str(value)

    def tp(self, key, *args):
        """带参数格式化；模板与参数不匹配时退回原文，避免二次异常。"""
        text = self.t(key)
        if not args:
            return text
        payload = args if len(args) > 1 else args[0]
        try:
            return text % payload
        except (TypeError, ValueError):
            return text

    def __call__(self, key, default=None):
        return self.t(key, default)


class I18n:
    """当前语言管理器：持有语言状态，是所有界面的翻译入口。"""

    def __init__(self, language=None):
        self._language = ""
        self.set_language(language or self._resolve_initial(), persist=False)

    # -- 语言状态 ---------------------------------------------------------- #
    @staticmethod
    def _resolve_initial():
        saved = read_user_language()
        if saved and saved in available_languages():
            return saved
        detected = detect_system_language()
        if detected in available_languages():
            return detected
        languages = available_languages()
        return DEFAULT_LANGUAGE if DEFAULT_LANGUAGE in languages else (languages[0] if languages else DEFAULT_LANGUAGE)

    @property
    def language(self):
        return self._language

    def set_language(self, language, persist=True):
        code = normalize_language(language)
        if not code or code not in available_languages():
            code = self._resolve_initial()
        self._language = code
        if persist:
            write_user_language(code)
        return code

    @staticmethod
    def available():
        """[(语言代码, 显示名)]，供语言选择界面直接使用。"""
        return [(code, language_label(code)) for code in available_languages()]

    # -- 翻译 -------------------------------------------------------------- #
    def translator(self):
        return Translator(self._language)

    def t(self, key, default=None):
        return self.translator().t(key, default)

    def tp(self, key, *args):
        return self.translator().tp(key, *args)

    def __call__(self, key, default=None):
        return self.t(key, default)

    # -- 语言相关的界面参数 ------------------------------------------------ #
    def is_cjk(self):
        return is_cjk_language(self._language)

    def is_wide(self):
        return is_wide_language(self._language)

    def font(self, default):
        return ui_font(self._language, default)


def get_i18n():
    """全局单例（桌面端启动时创建一次，之后各处共享同一个语言状态）。"""
    global _I18N
    with _LOCK:
        if _I18N is None:
            _I18N = I18n()
        return _I18N


def translator(language=None):
    """取某个语言（默认当前语言）的翻译器，供 Web 请求等多语言并存场景使用。"""
    if language is None:
        return get_i18n().translator()
    return Translator(language)


def set_language(code, persist=True):
    return get_i18n().set_language(code, persist)


def current_language():
    return get_i18n().language


def i18n(key, default=None):
    return get_i18n().t(key, default)


# --------------------------------------------------------------------------- #
# 命令行自检
# --------------------------------------------------------------------------- #
def _main(argv):
    if "--check" in argv:
        base = set(available_keys(DEFAULT_LANGUAGE))
        failed = False
        for code in available_languages():
            keys = set(available_keys(code))
            missing, extra = sorted(base - keys), sorted(keys - base)
            status = "OK" if not missing and not extra else "有差异"
            print("[%s] %-8s 词条 %3d  %s" % (code, language_label(code), len(keys), status))
            if missing:
                failed = True
                print("    缺少 %d 条: %s" % (len(missing), ", ".join(missing[:12]) + ("..." if len(missing) > 12 else "")))
            if extra:
                print("    多余 %d 条: %s" % (len(extra), ", ".join(extra[:12]) + ("..." if len(extra) > 12 else "")))
        return 1 if failed else 0
    print("语言包目录: %s" % locales_dir())
    for code in available_languages():
        print("  %-8s %-16s 词条 %3d  当前=%s" % (
            code, language_label(code), len(available_keys(code)),
            "是" if code == current_language() else ""))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
