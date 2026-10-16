<#
 Builds/Prepare-ArchResources.ps1 —— 准备非 x64 构建的随包二进制并逐个校验 PE 位宽
 ---------------------------------------------------------------------------
 各架构的资源来源不同，这个脚本在构建前统一处理好：

   -Arch x86（Python 3.10 x86，目标 Windows 8.1 x86 / Win10 ARM64 的 x86 仿真）
     1) 从仓库里的 OpenSC-0.25.1_win32-Light.msi 用 msiexec /a 解包 32 位工具，
        摊平到 build\opensc-win32\（= BuildPackage.py 的 TPMSMART_OPENSC_DIR），
        并校验每个 exe/dll 确实是 x86（OpenSC\ 里那份是 x64，不能用于 32 位包）；
     2) 校验 Import\x86\TPMImport.exe 是 32 位 —— 程序运行时会调用它，缺了功能就是坏的；
     3) 可选：SSHCardAgent-x86.exe（WinCryptSSHAgent 的 32 位版），有就校验，没有只告警。

   -Arch arm64（Python 3.13 arm64，目标 Windows 11 ARM64）
     OpenSC 官方**没有** Windows arm64 构建（0.25.1 只有 win32/win64 与 macOS dmg），
     所以随包仍用仓库里的 x64 工具 —— 在 Windows 11 ARM64 上靠 x64 仿真运行
     （Windows 10 ARM64 只有 x86 仿真，跑不了 x64 工具，因此 arm64 包面向 Win11）：
     1) 校验 OpenSC\ 下的工具就绪（不重新解包，也不改架构）；
     2) 校验 Import\arm64\TPMImport.exe 是 arm64（dotnet publish -r win-arm64 的产物）；
     3) SSH 代理没有 arm64 版，该组件直接跳过。

 用法（仓库根目录）：
     pwsh -File Builds\Prepare-ArchResources.ps1 -Arch x86
     pwsh -File Builds\Prepare-ArchResources.ps1 -Arch arm64
 ---------------------------------------------------------------------------
#>
param(
    [ValidateSet('x86', 'arm64')]
    [string]$Arch = 'x86',
    [string]$MsiName = 'OpenSC-0.25.1_win32-Light.msi',
    [string]$OutDir = 'build\opensc-win32',
    [string]$ImportDir = '',
    [string]$SshAgent = ''
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if (-not $ImportDir) {
    $ImportDir = if ($Arch -eq 'x86') { 'Import\x86' } else { 'Import\arm64' }
}
if (-not $SshAgent) {
    $SshAgent = if ($Arch -eq 'x86') { 'SSHCardAgent-x86.exe' } else { 'SSHCardAgent-arm64.exe' }
}

$naming = @{
    'x86'   = @{ Machine = 'x86';   Tag = '32 位' }
    'arm64' = @{ Machine = 'arm64'; Tag = 'arm64 位' }
}[$Arch]

function Get-PEMachine {
    param([string]$Path)
    try {
        $stream = [IO.File]::OpenRead($Path)
        try {
            $reader = New-Object IO.BinaryReader($stream)
            $stream.Position = 0x3C
            $offset = $reader.ReadInt32()
            $stream.Position = $offset + 4
            $machine = $reader.ReadUInt16()
        } finally {
            $stream.Dispose()
        }
    } catch {
        return 'unknown'
    }
    switch ($machine) {
        0x8664 { return 'x64' }
        0x014C { return 'x86' }
        0xAA64 { return 'arm64' }
        default { return ('0x{0:X}' -f $machine) }
    }
}

function Assert-Machine {
    param([string]$Path, [string]$What)
    $actual = Get-PEMachine $Path
    if ($actual -ne $naming.Machine) {
        throw "$What 不是 $($naming.Machine)（实际 $actual）：$Path"
    }
}

function Import-Hint {
    $publishRid = if ($Arch -eq 'x86') { 'win-x86' } else { 'win-arm64' }
    @"
缺少 $ImportDir\TPMImport.exe
程序运行时会调用 Import\TPMImport.exe（见 Module/TPMSmartCard.py），所以 $($naming.Tag)包必须带对应位宽的版本。
准备办法：把 C# 工程按 $publishRid 发布后，把 TPMImport.exe + *.dll + *.json 放进 $ImportDir\，
    例如：dotnet publish -c Release -r $publishRid --self-contained false -o $ImportDir
也可以直接把现成的运行时文件拷进该目录（只需顶层文件，不要源码工程）。
"@
}

if ($Arch -eq 'x86') {
    Write-Host '==> 1/3 从 win32 MSI 解包 32 位 OpenSC 工具'
    $msi = Join-Path $repo ('OpenSC\' + $MsiName)
    if (-not (Test-Path -LiteralPath $msi)) {
        throw "找不到 $MsiName（应为 $msi）。仓库里 OpenSC\ 下应同时有 win32 与 win64 的 Light MSI。"
    }

    $outPath = Join-Path $repo $OutDir
    Remove-Item -LiteralPath $outPath -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $outPath | Out-Null

    $stage = Join-Path $env:TEMP ('opensc-win32-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    try {
        $proc = Start-Process msiexec.exe -ArgumentList @('/a', $msi, '/qn', "TARGETDIR=$stage") -Wait -PassThru
        if ($proc.ExitCode -ne 0) { throw "msiexec /a 解包失败（退出码 $($proc.ExitCode)）" }

        # MSI 里的布局是 PFiles\OpenSC Project\OpenSC\{tools,pkcs11,minidriver}\；
        # 程序按「exe 与工具同级」的摊平布局调用 .\OpenSC\*.exe，所以只摊平 tools\
        $tools = Get-ChildItem -LiteralPath $stage -Recurse -Directory -Filter 'tools' |
            Select-Object -First 1
        if (-not $tools) { throw "解包结果里找不到 tools 目录：$stage" }
        Get-ChildItem -LiteralPath $tools.FullName -File | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $outPath -Force
        }
    } finally {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }

    $tools = Get-ChildItem -LiteralPath $outPath -File
    foreach ($file in $tools) {
        if ($file.Extension -in @('.exe', '.dll')) { Assert-Machine $file.FullName "OpenSC 工具 $($file.Name)" }
    }
    Write-Host "    解出 $($tools.Count) 个文件到 $OutDir，位宽校验通过"
} else {
    Write-Host '==> 1/3 检查 OpenSC 工具（arm64：沿用仓库里的 x64 工具，靠 Win11 的 x64 仿真运行）'
    $opensc = Join-Path $repo 'OpenSC'
    if (-not (Test-Path -LiteralPath $opensc)) { throw "仓库里找不到 OpenSC\ 目录：$opensc" }
    $toolCount = (Get-ChildItem -LiteralPath $opensc -File -Filter *.exe).Count
    if ($toolCount -eq 0) { throw "OpenSC\ 下没有任何工具：$opensc" }
    Write-Host "    OpenSC\ 下 $toolCount 个工具就绪（x64，官方没有 Windows arm64 构建）"
}

Write-Host "==> 2/3 校验 $($naming.Tag) TPMImport 运行时"
$importPath = Join-Path $repo $ImportDir
$importExe = Join-Path $importPath 'TPMImport.exe'
if (-not (Test-Path -LiteralPath $importExe)) { throw (Import-Hint) }
Assert-Machine $importExe 'TPMImport.exe'
$importFiles = (Get-ChildItem -LiteralPath $importPath -File).Count
Write-Host "    $ImportDir 就绪（$importFiles 个文件），TPMImport.exe 是 $($naming.Machine)"

Write-Host '==> 3/3 检查可选的 SSH 密钥代理'
$agent = Join-Path $repo $SshAgent
if (Test-Path -LiteralPath $agent) {
    Assert-Machine $agent $SshAgent
    Write-Host "    $SshAgent 就绪，会随包分发"
} elseif ($Arch -eq 'arm64') {
    Write-Host "    WinCryptSSHAgent 没有 arm64 版，arm64 产物不含 SSH 密钥代理组件" -ForegroundColor Yellow
} else {
    Write-Host "    没有 $SshAgent，32 位产物不含 SSH 密钥代理组件（安装包里该组件本来就可选）" -ForegroundColor Yellow
}
