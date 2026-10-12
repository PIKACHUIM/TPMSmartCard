import sys
import os
from cx_Freeze import setup, Executable

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
    executables=[
        client, server, tokens
    ],
)
