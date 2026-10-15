<#
 Builds/Build-Installer.ps1 —— 编译 Inno Setup 安装包（带 Certum 云签名）
 ---------------------------------------------------------------------------
 Inno 的签名工具不能写在 [Setup] 里（SignTool= 只接受「工具名」，命令要通过
 IDE 或 ISCC /S<name>=<command> 注入），所以这里统一做三件事：

   1) 解析 signtool.exe 与 Certum 云证书（证书不在就直接不签名，或在 CI 上失败）
   2) 生成签名工具命令行，把 $f（待签文件）交给 Builds\Sign-Windows.ps1
   3) 运行 ISCC，注入 /S 定义与 TPMSMART_SIGNTOOL 环境变量

 这样 install.iss 里只用：
     #define InnoSignTool GetEnv("TPMSMART_SIGNTOOL")
     #if Len(InnoSignTool) > 0
       SignTool={#InnoSignTool}
       SignedUninstaller=yes
     #endif
 Inno 会用它给「卸载器 uninst.e32 / 安装包 setup.exe / [Files] 里标了 SignTool 的条目」
 签名，并**自行校验**签名结果（签名工具必须真的产出签名，否则编译直接失败）。

 用法：
   .\Builds\Build-Installer.ps1                       # 有证书就签，没有就出未签名安装包
   .\Builds\Build-Installer.ps1 -NoSign               # 强制不签名
   $env:TPMSMART_SIGN_REQUIRED=1; .\Builds\Build-Installer.ps1   # 没证书/签名失败即失败（CI 用）
 ---------------------------------------------------------------------------
#>
param(
    [string]$IssFile = 'install.iss',
    [string]$Iscc = '',
    [string[]]$IsccArgs = @(),
    [string]$SetupDir = 'dist',   # 编译产物目录（与 install.iss 的 OutputDir 一致），用于汇报签名结果
    [switch]$NoSign,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'CertumSigning.ps1')

function Find-Iscc {
    if ($Iscc -and (Test-Path -LiteralPath $Iscc)) { return (Resolve-Path -LiteralPath $Iscc).Path }
    foreach ($candidate in @($env:ISCC, $env:TPMSMART_ISCC)) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    foreach ($root in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, (Join-Path $env:LOCALAPPDATA 'Programs'))) {
        if (-not $root -or -not (Test-Path -LiteralPath $root)) { continue }
        $hit = Get-ChildItem -LiteralPath $root -Directory -Filter 'Inno Setup*' -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName 'ISCC.exe' } |
            Where-Object { Test-Path -LiteralPath $_ } |
            Select-Object -First 1
        if ($hit) { return $hit }
    }
    return $null
}

$isccPath = Find-Iscc
if (-not $isccPath) {
    Write-SignLog '找不到 ISCC.exe（Inno Setup 命令行编译器）。' 'ERROR'
    exit 1
}
$issPath = if (Test-Path -LiteralPath $IssFile) { (Resolve-Path -LiteralPath $IssFile).Path }
           else { Join-Path $repoRoot $IssFile }
if (-not (Test-Path -LiteralPath $issPath)) {
    Write-SignLog "找不到安装包脚本：$IssFile" 'ERROR'
    exit 1
}

$required = Test-SignEnvFlag 'TPMSMART_SIGN_REQUIRED'
$signToolName = 'certum'
$signToolDefinition = ''
$cert = $null
$importStageDir = ''

if (-not $NoSign -and -not (Test-SignEnvFlag 'TPMSMART_SIGN_SKIP')) {
    $signtool = Get-SignToolPath
    $cert = Resolve-SigningCertificate
    if ($signtool -and $cert) {
        $signScript = Join-Path $PSScriptRoot 'Sign-Windows.ps1'
        $signToolDefinition = 'powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden' +
            " -File `$q$signScript`$q" +
            " -Path `$f -Thumbprint $($cert.Thumbprint) -Quiet"
        Write-SignLog "安装包签名证书：$($cert.Subject)"
        Write-SignLog "证书指纹      ：$($cert.Thumbprint)"
    } elseif (-not $signtool) {
        Write-SignLog '找不到 signtool.exe：请安装 Windows SDK（或通过 TPMSMART_SIGNTOOL 指定路径）。' 'ERROR'
    } else {
        Write-SignLog '证书库里没有可用的 Certum 云证书。' 'ERROR'
        Write-CertumGuidance
    }
}

if (-not $signToolDefinition) {
    if ($required) {
        Write-SignLog '要求强制签名（TPMSMART_SIGN_REQUIRED=1）但签名条件不满足，终止。' 'ERROR'
        exit 1
    }
    Write-SignLog '本次编译不带签名（产物为未签名安装包）。' 'WARN'
} elseif (-not $Quiet) {
    Write-SignLog '已启用安装包签名（卸载器 + setup.exe）。' 'OK'
}

# Import\TPMImport.exe（程序会以管理员身份调用它）先签好再打包：
# Inno 的 [Files] SignTool 参数要 6.5+，而且签名条目不压缩会撑大安装包，
# 所以在临时目录签好、再让 install.iss 从那里取文件，安装包本身仍正常压缩。
if ($signToolDefinition) {
    $importStageDir = Join-Path $env:TEMP ('TPMSmartCard-import-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $importStageDir | Out-Null
    Copy-Item -Path (Join-Path $repoRoot 'Import\*') -Destination $importStageDir -Recurse -Force

    $importTargets = @(foreach ($name in @('TPMImport.exe', 'TPMImport.dll')) {
            $candidate = Join-Path $importStageDir $name
            if (Test-Path -LiteralPath $candidate) { $candidate }
        })
    if ($importTargets.Count) {
        # -Path 只能出现一次（powershell.exe -File 不会把重复的同名参数当做数组），用 ; 合并
        $signArgs = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
            (Join-Path $PSScriptRoot 'Sign-Windows.ps1'),
            '-Path', ($importTargets -join ';'),
            '-Thumbprint', $cert.Thumbprint, '-Quiet')
        & powershell.exe @signArgs
        if ($LASTEXITCODE -ne 0) {
            Write-SignLog 'Import 下的程序签名失败，终止编译。' 'ERROR'
            Remove-Item -LiteralPath $importStageDir -Recurse -Force -ErrorAction SilentlyContinue
            exit 1
        }
        if (-not $Quiet) { Write-SignLog "已签名 Import 组件：$($importTargets.Count) 个" }
    }
    Write-SignLog "Import 来源目录：$importStageDir"
}

# 子进程（ISCC → 签名工具）需要知道：签名工具名，以及「拿不到证书必须报错」，
# 否则 Sign-Windows.ps1 会优雅跳过，而 Inno 又会因为「文件没有签名」而编译失败。
$previous = @{
    TPMSMART_SIGNTOOL      = $env:TPMSMART_SIGNTOOL
    TPMSMART_SIGN_REQUIRED = $env:TPMSMART_SIGN_REQUIRED
    TPMSMART_IMPORTDIR     = $env:TPMSMART_IMPORTDIR
}
try {
    if ($signToolDefinition) {
        $env:TPMSMART_SIGNTOOL = $signToolName
        $env:TPMSMART_SIGN_REQUIRED = '1'
        $env:TPMSMART_IMPORTDIR = $importStageDir
    } else {
        Remove-Item Env:\TPMSMART_SIGNTOOL -ErrorAction SilentlyContinue
    }

    $arguments = @()
    if ($signToolDefinition) { $arguments += "/S$signToolName=$signToolDefinition" }
    $arguments += $IsccArgs
    $arguments += $issPath

    Write-SignLog "运行 ISCC：$isccPath $(if ($signToolDefinition) { '(注入签名工具 /S' + $signToolName + '=…)' } else { '(不签名)' })"
    & $isccPath @arguments
    $code = $LASTEXITCODE
} finally {
    $env:TPMSMART_SIGNTOOL = $previous.TPMSMART_SIGNTOOL
    $env:TPMSMART_SIGN_REQUIRED = $previous.TPMSMART_SIGN_REQUIRED
    $env:TPMSMART_IMPORTDIR = $previous.TPMSMART_IMPORTDIR
    if ($importStageDir -and (Test-Path -LiteralPath $importStageDir)) {
        Remove-Item -LiteralPath $importStageDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($code -ne 0) {
    Write-SignLog "ISCC 编译失败（退出码 $code）。" 'ERROR'
    exit $code
}

# 汇报产物与签名校验结果
$distDir = if ([IO.Path]::IsPathRooted($SetupDir)) { $SetupDir } else { Join-Path $repoRoot $SetupDir }
$setup = Get-ChildItem -LiteralPath $distDir -Filter '*-setup.exe' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($setup) {
    $state = Get-SignatureState -File $setup.FullName
    if ($state.Signer) {
        Write-SignLog ("安装包：{0}（{1:N1} MB）· 签名者：{2} · 状态：{3}" -f `
                $setup.Name, ($setup.Length / 1MB), $state.Signer.Subject, $state.Status) 'OK'
    } else {
        Write-SignLog ("安装包：{0}（{1:N1} MB）· 未签名" -f $setup.Name, ($setup.Length / 1MB)) 'WARN'
    }
}
exit 0
