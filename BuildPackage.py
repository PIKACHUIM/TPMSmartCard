import sys
import os
from cx_Freeze import setup, Executable

# ADD FILES
files = []

# TARGET
target = Executable(
    script="SmartCardAPP.py",
    # base="Win32GUI",
    # icon="PullRecovery.ico"
)

# SETUP CX FREEZE
setup(
    name="TPM Virtual Smart Card Manager",
    version="0.1a",
    description="TPM Virtual Smart Card Manager",
    author="Pikachu Ren",
    options={'build_exe': {'include_files': files}},
    executables=[target],
)
