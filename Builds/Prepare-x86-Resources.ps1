<#
 Builds/Prepare-x86-Resources.ps1 —— 准备 32 位（x86）构建需要的随包二进制
 ---------------------------------------------------------------------------
 32 位包不能带 64 位的 OpenSC 工具和导入器（在 32 位系统上根本起不来），
 这个脚本在构建前把 32 位资源准备好并**逐个校验 PE 位宽**：

   1) 从仓库里已有的 OpenSC-0.25.1_win32-Light.msi 用 msiexec /a 解包出 32 位工具，
      摊平到 build\opensc-win32\（= BuildPackage.py 在 TPMSMART_ARCH=x86 时使用的
      TPMSMART_OPENSC_DIR），并校验每个 exe/dll 确实是 x86；
   2) 校验 Import\x86\ 里的 TPMImport 运行时是 32 位 —— 程序运行时会调用
      Import\TPMImport.exe，缺了或位宽不对功能就是坏的，因此这里直接失败；
      需要自己编译时：把 C# 工程按 win-x86 发布（dotnet publish -r win-x86），
      把 TPMImport.exe + *.dll + *.json 放进 Import\x86\；
   3) 可选：SSHCardAgent-x86.exe（WinCryptSSHAgent 的 32 位版，放在仓库根目录），
      有就校验位宽，没有只告警 —— 安装包里该组件本来就是可选项。

 用法（仓库根目录）：
     pwsh -File Builds\Prepare-x86-Resources.ps1
     pwsh -File Builds\Prepare-x86-Resources.ps1 -MsiName OpenSC-0.25.1_win32-Light.msi
 ---------------------------------------------------------------------------
#>
param(
    [string]$MsiName = 'OpenSC-0.25.1_win32-Light.msi',
    [string]$OutDir = 'build\opensc-win32',
    [string]$ImportDir = 'Import\x86',
    [string]$SshAgent = 'SSHCardAgent-x86.exe'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

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

function Assert-X86 {
    param([string]$Path, [string]$What)
    $arch = Get-PEMachine $Path
    if ($arch -ne 'x86') {
        throw "$What 不是 32 位（$arch）：$Path"
    }
}

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
    if ($file.Extension -in @('.exe', '.dll')) { Assert-X86 $file.FullName "OpenSC 工具 $($file.Name)" }
}
Write-Host "    解出 $($tools.Count) 个文件到 $OutDir，位宽校验通过"

Write-Host '==> 2/3 校验 32 位 TPMImport 运行时'
$importPath = Join-Path $repo $ImportDir
$importExe = Join-Path $importPath 'TPMImport.exe'
if (-not (Test-Path -LiteralPath $importExe)) {
    throw @"
缺少 32 位导入器：$ImportDir\TPMImport.exe
程序运行时会调用 Import\TPMImport.exe（见 Module/TPMSmartCard.py），所以 32 位包必须带 32 位版本。
准备办法：把 C# 工程按 win-x86 发布后，把 TPMImport.exe + *.dll + *.json 放进 $ImportDir\，
    例如：dotnet publish -c Release -r win-x86 --self-contained false -o $ImportDir
也可以直接把现成的 32 位运行时文件拷进该目录（只需顶层文件，不要源码工程）。
"@
}
Assert-X86 $importExe 'TPMImport.exe'
$importFiles = (Get-ChildItem -LiteralPath $importPath -File).Count
Write-Host "    $ImportDir 就绪（$importFiles 个文件），TPMImport.exe 是 32 位"

Write-Host '==> 3/3 检查可选的 32 位 SSH 密钥代理'
$agent = Join-Path $repo $SshAgent
if (Test-Path -LiteralPath $agent) {
    Assert-X86 $agent $SshAgent
    Write-Host "    $SshAgent 就绪（32 位），会随包分发"
} else {
    Write-Host "    没有 $SshAgent，32 位产物不含 SSH 密钥代理组件（安装包里该组件本来就可选）" -ForegroundColor Yellow
}
