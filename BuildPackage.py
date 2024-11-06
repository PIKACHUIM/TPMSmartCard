import sys
import os
from cx_Freeze import setup, Executable

# ADD FILES
files = [
    ("templates/", "templates/"),
    ("SSHCardAgent.exe", "SSHCardAgent.exe"),
    ("Config/", "Config/"),
    ("OpenSC/", "OpenSC/"),
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
# SETUP CX FREEZE
setup(
    name="TPM Virtual Smart Card Manager",
    version="1.3.2024.1106",
    description="TPM Virtual Smart Card Manager",
    author="Pikachu Ren",
    options={'build_exe': {
        'include_files': files
    }
    },
    executables=[
        client, server
    ],
)
