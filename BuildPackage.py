import os
import subprocess
import sys

from cx_Freeze import setup, Executable
from cx_Freeze.command.build_exe import build_exe as cx_build_exe

from Module.Version import VERSION

# 版本号统一来自 Module.Version（可由 CI 的环境变量 TPMSMART_VERSION 覆盖，
# 例如 .github/workflows/build.yml），确保安装包版本与「版本更新」检查一致
version = VERSION

# ADD FILES
files = [
    ("Config/", "Config/"),
    ("OpenSC/", "OpenSC/"),
    ("templates/", "templates/"),
    ("MoreConfig.exe", "MoreConfig.exe"),
    ("SSHCardAgent.exe", "SSHCardAgent.exe"),
]

# TARGET
client = Executable(
    script="SmartCardAPP.py",
    base="Win32GUI",
    icon="Config/iconer/icon02.ico",
    uac_admin=True
)
server = Executable(
    script="SmartCardWEB.py",
    # base="Win32GUI",
    icon="Config/iconer/icon04.ico",
    # uac_admin=True
)

tokens = Executable(
    script="SubApp/CertImport.py",
    base="Win32GUI",
    icon="Config/iconer/icon03.ico",
    uac_admin=True
)

# ---- CX FREEZE 构建后签名（Certum 云签名） ---------------------------------
# 签名细节全部在 Builds\Sign-Windows.ps1（证书解析 + signtool + Certum 时间戳），
# 这里只负责在 cx_Freeze 输出完成后调用它；证书不可用时优雅跳过，不影响本地构建。
#
#   CERTUM_CERTIFICATE_SHA1    证书指纹（不给则用证书库里未过期的 Certum 证书）
#   CERTUM_OTP_URI / USERNAME  仅 Builds\Sign-SetupCertum.ps1 连接云签名时用
#   TPMSMART_SIGN_SKIP=1       跳过签名
#   TPMSMART_SIGN_REQUIRED=1   拿不到证书 / 签名失败时构建直接失败（CI 用）
#   TPMSMART_SIGN_RECURSE=1    连 lib\ 里的 dll 一起签（默认只签顶层 exe）
#   TPMSMART_SIGN_EXTRA        额外要签的路径，os.pathsep 分隔
SIGN_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Builds", "Sign-Windows.ps1")


def _env_flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def sign_build_output(build_dir):
    if _env_flag("TPMSMART_SIGN_SKIP"):
        print("[签名] 已设置 TPMSMART_SIGN_SKIP=1，跳过签名")
        return
    if not os.path.isfile(SIGN_SCRIPT):
        print("[签名] 找不到签名脚本，跳过：" + SIGN_SCRIPT)
        return

    targets = [build_dir]
    targets += [p.strip() for p in os.environ.get("TPMSMART_SIGN_EXTRA", "").split(os.pathsep) if p.strip()]

    # 注意：-Path 只能出现一次（powershell.exe -File 下重复的同名参数不会被当成数组），
    # 多个目标用 ; 合并，由 Sign-Windows.ps1 自己拆分
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", SIGN_SCRIPT,
               "-Path", ";".join(targets)]
    if _env_flag("TPMSMART_SIGN_RECURSE"):
        command.append("-Recurse")

    print("[签名] " + " ".join(command))
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SystemExit("[签名] 签名失败（退出码 %d）" % result.returncode)


class build_exe_signed(cx_build_exe):
    """cx_Freeze 的 build_exe：构建完成后立刻给产物签名。"""

    def run(self):
        super().run()
        sign_build_output(os.path.abspath(self.build_exe))


# SETUP CX FREEZE
setup(
    name="TPM Virtual Smart Card Manager",
    version=version,
    description="TPM Virtual Smart Card Manager",
    author="Pikachu Ren",
    options={'build_exe': {
        'include_files': files
    }
    },
    # build_exe 换成带签名的子类：cx_Freeze 输出完成后调用 Builds\Sign-Windows.ps1
    cmdclass={'build_exe': build_exe_signed},
    executables=[
        client, server, tokens
    ],
)
