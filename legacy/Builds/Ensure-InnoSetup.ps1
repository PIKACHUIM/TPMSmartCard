<#
 Builds/Ensure-InnoSetup.ps1 —— 找到（必要时装好）能编译 install.iss 的 ISCC.exe
 ---------------------------------------------------------------------------
 install.iss 要求 Inno Setup 6.5 或更高：脚本是 UTF-8 无 BOM，用到 x64compatible，
 并且 ChineseSimplified.isl 与编译器自带的 Default.isl 必须同为 "6.5.0+" 语言文件
 级别，否则编译会报语言文件版本不匹配。windows runner 一般都预装了 ISCC，但版本
 可能偏旧，所以这里统一做三件事：

   1) 按 PATH → Program Files → ProgramFiles(x86) → LOCALAPPDATA\Programs 找 ISCC.exe；
   2) 用编译器自带的 Default.isl 里的版本标记判断语言文件级别，缺失或低于 6.5 时用
      Chocolatey 装一份新的（CI runner 是管理员，无需额外提权）；
   3) 把 ISCC.exe 的绝对路径写到输出流（stdout 最后一行），日志走 Write-Host。

 用法：
     $iscc = & .\Builds\Ensure-InnoSetup.ps1 | Where-Object { $_ -match 'ISCC\.exe$' } |
             Select-Object -Last 1
     if (-not $iscc) { throw 'ISCC.exe not found' }

 说明：choco 自身的输出用 Out-Host 送走，避免混进脚本的输出流（调用方是直接赋值
 接收路径的，混进其它字符串会取到脏值）。

 退出码：拿不到可用 ISCC 时为 1（choco 缺失、安装失败、装完仍然找不到）。
 ---------------------------------------------------------------------------
#>
param(
    # 语言文件级别（= install.iss 要求的 Inno Setup 版本），低于它就用 choco 升级
    [version]$MinimumLevel = '6.5',
    # 只检查不安装：找不到/太旧时直接失败（本地不想被自动装软件时用）
    [switch]$NoInstall
)

$ErrorActionPreference = 'Stop'

function Find-Iscc {
    $found = @()
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $found += $cmd.Source }
    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, "$env:LOCALAPPDATA\Programs")) {
        if ([string]::IsNullOrWhiteSpace($root) -or -not (Test-Path $root)) { continue }
        Get-ChildItem -Path $root -Directory -Filter 'Inno Setup*' -ErrorAction SilentlyContinue |
            ForEach-Object { $found += (Join-Path $_.FullName 'ISCC.exe') }
    }
    $found | Where-Object { Test-Path $_ } | Select-Object -First 1
}

function Get-InnoLevel($isccPath) {
    # 编译器自带的 Default.isl 里带着它的语言文件级别（形如 "Inno Setup version 6.5.0"）
    $isl = Join-Path (Split-Path $isccPath) 'Default.isl'
    if (-not (Test-Path $isl)) { return $null }
    $match = Select-String -Path $isl -Pattern 'Inno Setup version ([0-9]+\.[0-9]+)' -List
    if (-not $match) { return $null }
    return [version]$match.Matches[0].Groups[1].Value
}

$iscc = Find-Iscc
$level = if ($iscc) { Get-InnoLevel $iscc } else { $null }

if ((-not $iscc) -or (-not $level) -or ($level -lt $MinimumLevel)) {
    if ($NoInstall) {
        throw "找不到可用的 ISCC.exe（当前：$iscc，级别：$level，要求：$MinimumLevel），且已指定 -NoInstall"
    }
    if ($iscc) {
        Write-Host "found $iscc (language level $level < $MinimumLevel), upgrading via Chocolatey..."
    } else {
        Write-Host 'ISCC.exe not found, installing Inno Setup via Chocolatey...'
    }
    if (-not (Get-Command choco.exe -ErrorAction SilentlyContinue)) {
        throw "需要 Inno Setup $MinimumLevel+ 但找不到 choco.exe，请手动安装后重试"
    }
    # choco 的日志走 Out-Host，别混进给调用方读的输出流
    choco install innosetup --no-progress -y | Out-Host
    if ($LASTEXITCODE -notin @(0, 1641, 3010)) {
        throw "choco install innosetup failed ($LASTEXITCODE)"
    }
    $iscc = Find-Iscc
    $level = if ($iscc) { Get-InnoLevel $iscc } else { $null }
}

if (-not $iscc) {
    throw "安装后仍然找不到 ISCC.exe，请检查 Inno Setup $MinimumLevel+ 是否装好"
}

Write-Host "using $iscc (language level $level)"
Write-Output $iscc
