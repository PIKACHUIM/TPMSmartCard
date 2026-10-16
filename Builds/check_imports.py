# -*- coding: utf-8 -*-
"""打包前的依赖自查，查两件事：

1. 导入检查：项目里 import 的第三方模块，在当前解释器里必须都能导入。
   cx_Freeze 遇到缺失模块只会打印告警、构建照常成功，产物运行到那一行才抛
   ModuleNotFoundError（例如 requirements.txt 少写 requests）。
2. 声明检查：这些模块对应的发行包必须写在 requirements.txt 里。
   本地 venv 里手装过（或被别的包顺带装上）却忘了写进 requirements 时，
   本地构建一切正常，CI 干净环境才缺 —— 这个检查能在本地就发现。

用法：
    python Builds/check_imports.py          # 在装好依赖的解释器里执行
返回码：0 = 通过；1 = 有模块导入失败，或有模块的发行包未声明。
"""

import ast
import os
import re
import sys
from importlib import metadata, util


def setup_output():
    """保证中文提示能打印出来。

    CI 的 Windows runner 控制台编码是 cp1252，直接 print 中文会抛
    UnicodeEncodeError（本地中文系统是 cp936，所以本地看不出来）。
    只有在当前编码装不下这些文字时才切到 UTF-8（GitHub 日志按 UTF-8 渲染）。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        encoding = getattr(stream, "encoding", None) or "utf-8"
        try:
            "检查中文".encode(encoding)
        except (UnicodeEncodeError, LookupError):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass


setup_output()

SKIP_DIRS = {
    ".git", ".github", ".idea", ".vscode", "__pycache__", "Caches",
    "build", "dist", "staging",
    # 随程序分发的第三方二进制/资源，不含本项目代码
    "Import", "TPMImport", "OpenSC", "Setups", "static", "templates", "Images",
}

# 模块名与发行包名不一致时的对照表（模块装不上时用来给出可执行的提示）
DIST_ALIASES = {
    "OpenSSL": "pyOpenSSL",
    "dateutil": "python-dateutil",
    "flask": "Flask",
    "flask_classful": "Flask-Classful",
    "winpty": "pywinpty",
    "PIL": "pillow",
    "yaml": "PyYAML",
    "win32api": "pywin32",
    "win32con": "pywin32",
    "win32com": "pywin32",
    "pythoncom": "pywin32",
    "pywintypes": "pywin32",
}

# 允许「导入了但不必写进 requirements.txt」的模块（一般是故意使用某个依赖的附带模块）。
# 留空表示要求全部显式声明。
ALLOW_UNLISTED = set()

# 可选依赖：装了就用、没装也能跑（代码里有 try/except 兜底），缺失时只告警不算失败。
#   winpty（pywinpty）—— 交互式控制台后端；该包只在 cp37 及更早发过 win32 wheel，
#   32 位构建里必然没有，缺了会自动退回 Module/ConsoleIO.py 的 ctypes 实现
#   （见 Module/PtyCompat.py）。
#   cx_Freeze —— 只有 cx_Freeze 那条打包线需要（BuildPackage.py 会被本脚本扫描到）。
#   Nuitka 线跑在 Python 3.14 上，而 cx_Freeze 的依赖 cx_Logging 没有 cp314 轮子，
#   那边本来就不装它，不该因此拦住构建。
OPTIONAL_MODULES = {"winpty", "cx_Freeze"}


def normalize(name):
    """规范化包名，便于跨写法比较（Flask-Classful == flask_classful）。"""
    return name.strip().lower().replace("_", "").replace("-", "")


def load_declared(root):
    """读取 requirements.txt 里声明的发行包名（兼容 UTF-16/UTF-8 与 BOM）。"""
    path = os.path.join(root, "requirements.txt")
    with open(path, "rb") as handle:
        raw = handle.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8-sig", errors="replace")

    declared = set()
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        # 去掉版本约束：Flask-Classful~=0.16.0 -> Flask-Classful
        name = re.split(r"[<>=!~\[\s;]", line, 1)[0].strip()
        if name:
            declared.add(normalize(name))
    return declared


def collect_imports(root):
    """返回 {顶层模块名: {出现的文件}}，以及本地模块名集合。"""
    imports = {}
    local_names = set()
    py_files = []
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        local_names.add(os.path.basename(base))
        for name in names:
            if name.endswith(".py"):
                py_files.append(os.path.join(base, name))
                local_names.add(os.path.splitext(name)[0])
    local_names.add(os.path.basename(os.path.abspath(root)))

    for path in py_files:
        rel = os.path.relpath(path, root)
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                tree = ast.parse(handle.read(), path)
        except SyntaxError as err:
            print("！语法解析失败，已跳过：%s（%s）" % (rel, err))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.setdefault(alias.name.split(".")[0], set()).add(rel)
            elif isinstance(node, ast.ImportFrom):
                # 只看绝对导入；相对导入属于项目内部
                if node.level == 0 and node.module and node.module != "__future__":
                    imports.setdefault(node.module.split(".")[0], set()).add(rel)
    return imports, local_names


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    imports, local_names = collect_imports(root)
    declared = load_declared(root)

    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    missing = []
    undeclared = []
    optional = []
    checked = 0
    for module in sorted(imports):
        if module in stdlib or module in local_names or module.startswith("_"):
            continue
        checked += 1
        if module in sys.builtin_module_names:
            continue
        try:
            spec = util.find_spec(module)
        except (ImportError, ValueError):
            spec = None

        dists = metadata.packages_distributions().get(module) or []
        if not dists and module in DIST_ALIASES:
            dists = [DIST_ALIASES[module]]

        if spec is None:
            if module in OPTIONAL_MODULES:
                optional.append((module, sorted(imports[module])))
            else:
                missing.append((module, dists, sorted(imports[module])))
        elif dists and module not in ALLOW_UNLISTED:
            if not any(normalize(dist) in declared for dist in dists):
                undeclared.append((module, dists, sorted(imports[module])))

    print("检查 %d 个项目内 import 的第三方模块（%s）" % (checked, sys.executable))
    print("requirements.txt 已声明 %d 个发行包" % len(declared))
    for module, where in optional:
        print("可选依赖缺失（不影响构建）：%s（被引用于 %s）" % (module, "、".join(where)))

    if not missing and not undeclared:
        print("依赖检查通过：模块都能导入，且发行包都已在 requirements.txt 中声明。")
        return 0

    if missing:
        print("\n以下模块在当前环境导入失败（CI 干净环境打包出来的程序会在运行时崩溃）：")
        for module, dists, where in missing:
            hint = "、".join(dists) if dists else "（未能确定发行包名）"
            print("  - %s  → 需要安装 %s" % (module, hint))
            print("      被引用于：%s" % "、".join(where))

    if undeclared:
        print("\n以下模块能导入，但其发行包没有写进 requirements.txt"
              "（本地手装过就会漏，CI 干净环境会缺）：")
        for module, dists, where in undeclared:
            print("  - %s  → 请补上 %s" % (module, "、".join(dists)))
            print("      被引用于：%s" % "、".join(where))

    print("\n请把上面列出的发行包补进 requirements.txt，重新安装依赖后再构建。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
