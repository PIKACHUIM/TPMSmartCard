# -*- coding: utf-8 -*-
"""Nuitka 打包 —— 与 cx_Freeze（BuildPackage.py）并行、互不干扰的第二套方案。

为什么要另做一套
----------------
cx_Freeze 是把解释器 + ``.pyc`` 一起分发、运行到那一行才导入模块，冷启动慢
（第三方包多、资源目录大）。Nuitka 把 Python 代码编译成 C 再生成原生 exe，
冷启动明显更快，代价是构建时间长（CI 上约 20~40 分钟）。

两套并存，互不影响：
* cx_Freeze 继续出正式包（``build/exe.win-amd64-*`` 与 ``install.iss`` 的路径约定都不动）；
* Nuitka 单独一条流水线（``.github/workflows/build-client-nuitka.yml``），
  产物落在 ``build/nuitka/``，发布到单独的 ``nuitka-beta`` 预发布标签。

产物布局（standalone 目录模式，刻意不用 --onefile）
---------------------------------------------------
::

    build/nuitka/TPMSmartCard/
        SmartCardAPP.exe        主程序（GUI + requireAdministrator 清单）
        SmartCardWEB.exe        WEB 上传服务（控制台）
        CertImport.exe          证书导入对话框（GUI + requireAdministrator 清单）
        Config/  OpenSC/  templates/  static/  Import/
        SSHCardAgent.exe
        BUILD_INFO.txt

exe 与 ``Config/`` 同级，所以 ``Module/Paths.py`` 的 ``project_root()`` 走的是
「``sys.frozen`` + exe 同级有 ``Config`` 目录」那条分支，程序根目录判定与
cx_Freeze 产物完全一致。``--onefile`` 会把资源解到临时目录，该分支失效
（退化成 ``os.getcwd()``），因此这里不用 onefile。

Nuitka 一次只能出一个 exe，三个入口要各编译一次：先编主程序（依赖最全），
其余两个编完把 ``*.dist`` 目录并进来（同一个 pip 环境，同名 DLL/pyd 内容一致）。

用法
----
::

    pip install -r requirements-nuitka.txt
    python BuildNuitka.py                     # 全部构建到 build/nuitka/TPMSmartCard
    python BuildNuitka.py --clean             # 先删掉上次产物
    python BuildNuitka.py --targets app,web   # 只构建部分入口（排错时省时间）
    python BuildNuitka.py --keep-intermediate # 保留各入口的 *.dist（排错用）

签名沿用 cx_Freeze 那套环境变量（由 ``Builds/Sign-Windows.ps1`` 完成）：

* ``TPMSMART_SIGN_SKIP=1``      跳过签名（等价于 ``--no-sign``）
* ``TPMSMART_SIGN_REQUIRED=1``  拿不到证书 / 签名失败即构建失败（CI 用）
* ``CERTUM_CERTIFICATE_SHA1``   指定证书指纹（不给则用证书库里未过期的 Certum 证书）
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 版本号与 cx_Freeze 方案同源（Module/Version.py，可被 TPMSMART_VERSION 覆盖）
from Module.Version import VERSION  # noqa: E402

# Nuitka 的中间输出目录；最终产物是它下面的 TPMSmartCard/（与 exe 同级放资源）
OUT_ROOT = os.path.join(ROOT, "build", "nuitka")
DIST_DIR = os.path.join(OUT_ROOT, "TPMSmartCard")

# 随程序分发、与工作目录无关的资源：Nuitka 只管 exe，这些直接拷到产物根目录。
# 参考 BuildPackage.py 的 include_files（Config/OpenSC/templates/
# SSHCardAgent.exe），外加 SmartCardWEB 用到的 static/。
RESOURCE_DIRS = ("Config", "OpenSC", "templates", "static", "Fido")
RESOURCE_FILES = ("SSHCardAgent.exe",)

# Import 只取顶层运行时文件（与 install.iss 的 [Files] 一致，避免把 Import\TPMImport
# 的 C# 源码工程一起打进去）。程序运行时会用相对路径调用 Import\TPMImport.exe。
IMPORT_DIR = "Import"
IMPORT_EXTS = (".dll", ".json")
IMPORT_FILES = ("TPMImport.exe",)

# 三个入口（与 BuildPackage.py 的 client / server / tokens 一一对应）
TARGETS = (
    {
        "key": "app",
        "script": "SmartCardAPP.py",
        "exe": "SmartCardAPP.exe",
        "gui": True,
        "admin": True,
        "icon": "Config/iconer/icon02.ico",
        "description": "TPM Virtual Smart Card Manager",
    },
    {
        "key": "web",
        "script": "SmartCardWEB.py",
        "exe": "SmartCardWEB.exe",
        "gui": False,
        "admin": False,
        "icon": "Config/iconer/icon04.ico",
        "description": "TPM Virtual Smart Card Manager Web Uploader",
    },
    {
        "key": "certimport",
        "script": os.path.join("SubApp", "CertImport.py"),
        "exe": "CertImport.exe",
        "gui": True,
        "admin": True,
        "icon": "Config/iconer/icon03.ico",
        "description": "TPM Virtual Smart Card Manager Certificate Import",
    },
)

SIGN_SCRIPT = os.path.join(ROOT, "Builds", "Sign-Windows.ps1")


def log(message):
    print("[Nuitka] %s" % message, flush=True)


def env_flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def version4(text, fallback="1.7.0.0"):
    """把版本号转成 exe 版本资源要求的 4 段数字（缺位补 0）。"""
    parts = [item for item in re.split(r"[^0-9]+", str(text or "")) if item]
    if not parts:
        return fallback
    parts = parts[:4]
    while len(parts) < 4:
        parts.append("0")
    return ".".join(parts)


def nuitka_version():
    """当前解释器里的 Nuitka 版本；没装时给出可执行的安装提示。"""
    probe = subprocess.run([sys.executable, "-m", "nuitka", "--version"],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        raise SystemExit(
            "[Nuitka] 当前解释器里没有 Nuitka：%s\n"
            "         请先安装：%s -m pip install -r requirements-nuitka.txt"
            % (sys.executable, sys.executable))
    text = (probe.stdout or probe.stderr or "").strip()
    # 输出形如 "Nuitka:        2.7.12"，取冒号后的版本号
    return text.split(":", 1)[-1].strip() if ":" in text else text


def build_command(target, build_version4):
    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        # CI 上没人能回答交互提问（需要下载 ccache/依赖时会问）
        "--assume-yes-for-downloads",
        # 编译完删掉 *.build 中间目录（几 GB，产物只需要 *.dist）
        "--remove-output",
        "--output-dir=" + OUT_ROOT,
        # C 编译并行度：Nuitka 默认单线程，给满 CPU 明显更快
        "--jobs=%d" % (os.cpu_count() or 2),
        # tkinter / ttkbootstrap 的数据（Tcl/Tk、主题）靠这个插件带出来
        "--enable-plugin=tk-inter",
        # Module 是没有 __init__.py 的隐式命名空间包（PEP 420），静态分析之外
        # 再显式声明一次；SubApp 是普通包，一并带上
        "--include-package=Module",
        "--include-package=SubApp",
        # winpty(pywinpty) 带原生 winpty.dll / winpty-agent.exe，必须连数据一起收
        "--include-package=winpty",
        # ttkbootstrap 的 style.py 用「from ttkbootstrap import utility」这种包内
        # 子模块导入，静态分析容易只看名字不看包，干脆整包收进来（cx_Freeze
        # 线踩过这个坑：漏收 utility.pyc 会报 cannot import name 'utility'）
        "--include-package=ttkbootstrap",
        "--include-package-data=winpty",
        "--include-package-data=certifi",
        "--include-package-data=ttkbootstrap",
        "--include-package-data=babel",
        "--include-package-data=tkcalendar",
        "--include-package-data=pytz",
        "--include-package-data=pyglet",
        # exe 版本资源（与 install.iss 的 VersionInfo* 对齐）
        "--company-name=Pikachu Ren",
        "--product-name=TPM Virtual Smart Card Manager",
        "--file-description=" + target["description"],
        "--file-version=" + build_version4,
        "--product-version=" + build_version4,
        "--copyright=Copyright (C) Pikachu Ren",
    ]
    if target["gui"]:
        cmd.append("--windows-console-mode=disable")
    if target["admin"]:
        cmd.append("--windows-uac-admin")
    cmd.append("--windows-icon-from-ico=" + target["icon"])
    cmd.append(target["script"])
    return cmd


def build_target(target, build_version4):
    """编译一个入口，返回它自己的 *.dist 目录。"""
    dist = os.path.join(OUT_ROOT, os.path.splitext(target["exe"])[0] + ".dist")
    if os.path.isdir(dist):
        shutil.rmtree(dist, ignore_errors=True)

    cmd = build_command(target, build_version4)
    log("编译 %s ← %s" % (target["exe"], target["script"]))
    print("       " + subprocess.list2cmdline(cmd), flush=True)

    started = time.time()
    code = subprocess.run(cmd, cwd=ROOT).returncode
    minutes = (time.time() - started) / 60.0

    if code != 0:
        raise SystemExit("[Nuitka] %s 构建失败（退出码 %d，用时 %.1f 分钟）"
                         % (target["exe"], code, minutes))
    if not os.path.isdir(dist):
        raise SystemExit("[Nuitka] %s 已编译但找不到产物目录：%s" % (target["exe"], dist))

    log("%s 完成，用时 %.1f 分钟" % (target["exe"], minutes))
    return dist


def merge_dist(source_dist, dest_dist):
    """把副入口的 *.dist 并进主产物目录（同名文件保留先到的）。"""
    added = 0
    for base, _dirs, names in os.walk(source_dist):
        rel = os.path.relpath(base, source_dist)
        target_dir = dest_dist if rel == "." else os.path.join(dest_dist, rel)
        os.makedirs(target_dir, exist_ok=True)
        for name in names:
            src = os.path.join(base, name)
            dst = os.path.join(target_dir, name)
            # 同一个 pip 环境、同一个 Python 编译出来的 python3xx.dll / *.pyd
            # 内容一致，重复的直接跳过
            if os.path.exists(dst):
                continue
            shutil.copy2(src, dst)
            added += 1
    log("并入 %s：新增 %d 个文件" % (os.path.basename(source_dist), added))


def copy_resources(dist):
    """把 exe 之外的随包资源拷到产物根目录（与 cx_Freeze 的 include_files 等价）。"""
    for name in RESOURCE_DIRS:
        src = os.path.join(ROOT, name)
        if not os.path.isdir(src):
            log("警告：资源目录不存在，已跳过 %s" % name)
            continue
        shutil.copytree(src, os.path.join(dist, name), dirs_exist_ok=True)
        log("资源目录 %s/ 已复制" % name)

    for name in RESOURCE_FILES:
        src = os.path.join(ROOT, name)
        if not os.path.isfile(src):
            log("警告：资源文件不存在，已跳过 %s" % name)
            continue
        shutil.copy2(src, os.path.join(dist, name))

    copy_import(dist)


def copy_import(dist):
    """Import\\TPMImport.exe 及同目录运行时的 dll/json（不递归，不要源码工程）。"""
    src = os.path.join(ROOT, IMPORT_DIR)
    if not os.path.isdir(src):
        log("警告：找不到 %s\\，TPM 导入功能在产物里会缺失" % IMPORT_DIR)
        return

    dst = os.path.join(dist, IMPORT_DIR)
    os.makedirs(dst, exist_ok=True)
    copied = 0
    for name in sorted(os.listdir(src)):
        path = os.path.join(src, name)
        if not os.path.isfile(path):
            continue
        if name in IMPORT_FILES or name.lower().endswith(IMPORT_EXTS):
            shutil.copy2(path, os.path.join(dst, name))
            copied += 1
    log("%s/ 已复制 %d 个运行时文件" % (IMPORT_DIR, copied))


def write_build_info(dist, build_version):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    server = os.environ.get("GITHUB_SERVER_URL", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    lines = [
        "packager=nuitka",
        "nuitka=%s" % nuitka_version(),
        "python=%s" % sys.version.split()[0],
        "version=%s" % (build_version or VERSION),
        "commit=%s" % os.environ.get("GITHUB_SHA", ""),
        "ref=%s" % os.environ.get("GITHUB_REF_NAME", ""),
        "run=%s" % ("%s/%s/actions/runs/%s" % (server, repo, run_id) if server and repo else ""),
        "built_at=%s UTC" % stamp,
    ]
    path = os.path.join(dist, "BUILD_INFO.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    log("已写入 %s" % os.path.basename(path))


def sign_build_output(dist):
    """构建完成后签名（证书不可用时优雅跳过，CI 上由 TPMSMART_SIGN_REQUIRED 兜底）。"""
    if env_flag("TPMSMART_SIGN_SKIP"):
        log("已设置 TPMSMART_SIGN_SKIP=1，跳过签名")
        return
    if not os.path.isfile(SIGN_SCRIPT):
        log("找不到签名脚本，跳过：" + SIGN_SCRIPT)
        return

    # 只签顶层 exe（与 cx_Freeze 一致）；Import 组件由打包阶段单独签，避免把
    # lib 里成百上千个文件都送去云签名
    command = ["powershell.exe", "-NoProfile", "-NonInteractive",
               "-ExecutionPolicy", "Bypass", "-File", SIGN_SCRIPT,
               "-Path", dist]
    print("[签名] " + " ".join(command), flush=True)
    code = subprocess.run(command).returncode
    if code != 0:
        raise SystemExit("[签名] 签名失败（退出码 %d）" % code)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Nuitka 打包（cx_Freeze 之外的第二套方案，产物在 build/nuitka）")
    parser.add_argument("--targets", default="",
                        help="只构建部分入口：app,web,certimport（逗号分隔，默认全部）")
    parser.add_argument("--clean", action="store_true",
                        help="构建前删除 build/nuitka")
    parser.add_argument("--keep-intermediate", action="store_true",
                        help="保留各入口自己的 *.dist 中间产物（排错用）")
    parser.add_argument("--no-sign", action="store_true",
                        help="等价于设置 TPMSMART_SIGN_SKIP=1")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.no_sign:
        os.environ["TPMSMART_SIGN_SKIP"] = "1"

    wanted = [item.strip().lower() for item in args.targets.split(",") if item.strip()]
    unknown = [item for item in wanted if item not in [t["key"] for t in TARGETS]]
    if unknown:
        raise SystemExit("未知的 --targets：%s（可选：%s）"
                         % ("、".join(unknown), ", ".join(t["key"] for t in TARGETS)))

    targets = [t for t in TARGETS if not wanted or t["key"] in wanted]
    build_version = os.environ.get("TPMSMART_VERSION", "").strip() or VERSION
    build_version4 = version4(build_version)

    log("Nuitka 版本：%s" % nuitka_version())
    log("Python：%s" % sys.executable)
    log("版本号：%s（exe 资源 %s）" % (build_version, build_version4))
    log("入口：%s" % "、".join(t["key"] for t in targets))

    if args.clean and os.path.isdir(OUT_ROOT):
        log("清理 %s" % OUT_ROOT)
        shutil.rmtree(OUT_ROOT, ignore_errors=True)
    if os.path.isdir(DIST_DIR):
        # 上次的产物必须清掉：否则会混入旧 exe / 旧模块，掩盖真实结果
        shutil.rmtree(DIST_DIR, ignore_errors=True)

    started = time.time()
    primary, secondary = targets[0], targets[1:]

    primary_dist = build_target(primary, build_version4)
    os.makedirs(OUT_ROOT, exist_ok=True)
    shutil.move(primary_dist, DIST_DIR)
    log("主产物目录：%s" % DIST_DIR)

    intermediate = []
    for target in secondary:
        dist = build_target(target, build_version4)
        merge_dist(dist, DIST_DIR)
        intermediate.append(dist)

    copy_resources(DIST_DIR)
    write_build_info(DIST_DIR, build_version)
    sign_build_output(DIST_DIR)

    if not args.keep_intermediate:
        for dist in intermediate:
            shutil.rmtree(dist, ignore_errors=True)

    total = (time.time() - started) / 60.0
    exes = sorted(name for name in os.listdir(DIST_DIR) if name.lower().endswith(".exe"))
    log("完成，总用时 %.1f 分钟" % total)
    log("产物：%s" % DIST_DIR)
    for name in exes:
        size = os.path.getsize(os.path.join(DIST_DIR, name)) / 1024.0 / 1024.0
        log("  %-20s %.1f MB" % (name, size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
