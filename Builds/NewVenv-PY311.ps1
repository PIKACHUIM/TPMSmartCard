# NewVenv-PY311.ps1
# 用 Python 3.11 重建 TPMSmartCard 的虚拟环境（CI 与 install.aip 都要求 3.11）
#
# 背景：cx_Freeze~=7.2.0 / cx_Logging / pywinpty~=2.0.13 在 Python 3.13/3.14 上
#       没有预编译 wheel，pip 会退化成源码编译并要求 MSVC Build Tools；
#       且 install.aip / install.iss 硬编码 build\exe.win-amd64-3.11，
#       换版本后 cx_Freeze 产物目录名会变，打包脚本就找不到文件。
#
# 用法（在仓库根目录 D:\Codes\TPMSmartCard 下）：
#   .\Builds\NewVenv-PY311.ps1
#   .\Builds\NewVenv-PY311.ps1 -VenvDir D:\Venvs\TPMSmartCard-PY311
#   .\Builds\NewVenv-PY311.ps1 -Force        # 已存在时先删掉重建

[CmdletBinding()]
param(
    [string]$VenvDir = 'D:\Venvs\TPMSmartCard-PY311',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Warn2($msg) { Write-Host "!!  $msg" -ForegroundColor Yellow }

# 1) 找一个可用的 Python 3.11
Write-Step '查找 Python 3.11'
$py = $null
if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    $found = & py.exe -3.11 -c "import sys;print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $found) { $py = $found.Trim() }
}
if (-not $py) {
    Write-Warn2 '没有找到 Python 3.11。请先安装：'
    Write-Host '    下载页: https://www.python.org/downloads/windows/  ->  Python 3.11.x  Windows installer (64-bit)'
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

Write-Step "安装 requirements.txt"
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
Write-Host '  构建产物:  build\exe.win-amd64-3.11  （与 install.aip / install.iss 一致）'
Write-Host '  打包:      python BuildPackage.py build   （用上面的解释器；需要管理员权限）'
