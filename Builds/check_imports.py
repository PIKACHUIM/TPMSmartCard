# -*- coding: utf-8 -*-
"""打包前的依赖自查：项目里 import 的第三方模块，当前解释器里必须都能导入。

背景：cx_Freeze 遇到缺失模块只会打印告警，构建照常成功，产物运行到那一行才抛
ModuleNotFoundError（例如 requirements.txt 少写 requests）。所以在 CI 里先跑这个
脚本，把「漏写依赖」在构建阶段就拦下来。

用法：
    python Builds/check_imports.py          # 在装好依赖的解释器里执行
返回码：0 = 全部可导入；1 = 有模块缺失（会列出对应需要补的发行包名）。
"""

import ast
import os
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

    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    missing = []
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
        if spec is None:
            dists = metadata.packages_distributions().get(module) or []
            if not dists and module in DIST_ALIASES:
                dists = [DIST_ALIASES[module]]
            missing.append((module, dists, sorted(imports[module])))

    print("检查 %d 个项目内 import 的第三方模块（%s）" % (checked, sys.executable))
    if not missing:
        print("依赖检查通过：所有第三方模块均可导入。")
        return 0

    print("\n以下模块在当前环境导入失败，打包出来的程序会在运行时崩溃：")
    for module, dists, where in missing:
        hint = "、".join(dists) if dists else "（未能确定发行包名）"
        print("  - %s  → 需要安装 %s" % (module, hint))
        print("      被引用于：%s" % "、".join(where))
    print("\n请把这些发行包补进 requirements.txt，再重新安装依赖后构建。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
