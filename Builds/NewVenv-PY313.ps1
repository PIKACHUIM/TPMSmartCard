# NewVenv-PY313.ps1
# 建一个本地开发用的虚拟环境（默认 Python 3.13，即 x64 cx_Freeze 正式线所用的版本）
#
# 各条流水线用的 Python（与 .github/workflows/*.yml 保持一致）：
#   x64   cx_Freeze（win10）  Python 3.13   ← 本脚本默认；官方要求 Windows 8.1+
#   x64   Nuitka（win10）     Python 3.14   （Nuitka 支持到 3.14，且不依赖 cx_Freeze）
#   x86   cx_Freeze（win78）  Python 3.10   ← 低版本系统能用的最高版本，用 -PythonVersion 3.10
#   arm64 cx_Freeze（win11）  Python 3.13   （只能在 arm64 机器上构建，见 build-client-release-arm64.yml）
#
# 依赖按 Python 版本在 requirements.txt 里用环境标记分流，所以一个 venv 只对应一条线：
#   3.13/3.14 用 cx_Freeze 8.7 + cryptography>=46；3.10 用 cx_Freeze 7.2 + cryptography 43。
#   注意 3.14 下不会安装 cx_Freeze（cx_Logging 还没有 cp314 轮子），因此 3.14 venv 只能跑 Nuitka 打包。
#
# 用法（在仓库根目录）：
#   .\Builds\NewVenv-PY313.ps1
#   .\Builds\NewVenv-PY313.ps1 -PythonVersion 3.10 -VenvDir D:\Venvs\TPMSmartCard-PY310
#   .\Builds\NewVenv-PY313.ps1 -Force        # 已存在时先删掉重建

[CmdletBinding()]
param(
    [string]$PythonVersion = '3.13',
    [string]$VenvDir = '',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

if (-not $VenvDir) {
    $VenvDir = 'D:\Venvs\TPMSmartCard-PY' + ($PythonVersion -replace '\.', '')
}

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Warn2($msg) { Write-Host "!!  $msg" -ForegroundColor Yellow }

# 1) 找指定版本的 Python（x64）
Write-Step "查找 Python $PythonVersion"
$py = $null
if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    $found = & py.exe "-$PythonVersion" -c "import sys;print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $found) { $py = $found.Trim() }
}
if (-not $py) {
    Write-Warn2 "没有找到 Python $PythonVersion。请先安装："
    Write-Host '    下载页: https://www.python.org/downloads/windows/'
    Write-Host "    ->  Python $PythonVersion.x  Windows installer (64-bit)"
    Write-Host '    安装时务必：'
    Write-Host '      - 右键安装包 -> 以管理员身份运行'
    Write-Host '      - 首屏勾选 "Install for all users" 与 "Add python.exe to PATH"'
    Write-Host '        (本机有 DisableMSI=1 策略，未提权安装会被拒: MSI 1625)'
    Write-Host ''
    Write-Host '装好后重新运行本脚本。'
    exit 1
}
Write-Host "    使用: $py"
& $py -c "import sys;print('    ' + sys.version)"

# 2) 建 venv
$repo = Split-Path -Parent $PSScriptRoot
$req = Join-Path $repo 'requirements.txt'
if (-not (Test-Path $req)) { throw "找不到 requirements.txt: $req" }

if (Test-Path $VenvDir) {
    if (-not $Force) {
        Write-Warn2 "已存在: $VenvDir"
        Write-Host '    想重建请加 -Force（会删除该目录）'
        exit 1
    }
    Write-Step "删除旧环境 $VenvDir"
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
}

Write-Step "创建虚拟环境 $VenvDir"
& $py -m venv $VenvDir

$venvPy = Join-Path $VenvDir 'Scripts\python.exe'
if (-not (Test-Path $venvPy)) { throw "venv 创建失败: $venvPy" }

Write-Step '升级 pip'
& $venvPy -m pip install --upgrade pip

Write-Step '安装 requirements.txt（版本按 Python 版本自动分流）'
& $venvPy -m pip install -r $req
if ($LASTEXITCODE -ne 0) { throw "pip install 失败 (exit $LASTEXITCODE)" }

# 3) 依赖自查（和 CI 跑的是同一个脚本）
$check = Join-Path $repo 'Builds\check_imports.py'
if (Test-Path $check) {
    Write-Step '依赖自查 Builds/check_imports.py'
    & $venvPy $check
    if ($LASTEXITCODE -ne 0) { Write-Warn2 '自查未通过，见上面的提示' }
}

Write-Host ''
Write-Step '完成'
Write-Host "  venv:      $VenvDir"
Write-Host "  解释器:    $venvPy"
Write-Host '  PyCharm:   Settings -> Project -> Python Interpreter -> Add -> Existing，选上面这个 python.exe'
Write-Host '  构建产物:  build\exe.win-amd64-3.13（x64）/ exe.win32-3.10（x86）/ exe.win-arm64-3.13（arm64）'
Write-Host '  打包:      python BuildPackage.py build   （用上面的解释器；需要管理员权限）'
Write-Host '  其它架构:  需另建对应版本的 venv（-PythonVersion 3.10 等），见文件头说明'
