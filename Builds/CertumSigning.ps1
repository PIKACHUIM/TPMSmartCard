<#
 Builds/CertumSigning.ps1 —— Certum 云代码签名（Certum SimplySign）公共库
 ---------------------------------------------------------------------------
 本文件只提供函数，不直接执行任何操作；由下面几个入口脚本点源加载：
   · Builds\Sign-Windows.ps1      给文件/目录签名（cx_Freeze 产物、绿色版暂存目录…）
   · Builds\Build-Installer.ps1   调用 ISCC 编译安装包，并把签名工具注入 Inno
   · Builds\Sign-SetupCertum.ps1  准备环境（装 SimplySign Desktop / 注册表 / TOTP 登录 / 校验）

 参考实现：https://github.com/OpenListTeam/OpenList-Desktop
   · .github/scripts/install-simplysign.sh             安装 SimplySign Desktop
   · .github/scripts/configure-simplysign-registry.ps1 注册表预配置（登录框自动弹出）
   · .github/scripts/Connect-SimplySign-Enhanced.ps1   TOTP 自动登录并等待云证书就绪
   · src-tauri/tauri.windows.conf.json                 certificateThumbprint + sha256 + http://time.certum.pl
   本质：证书私钥不在本机、也不可导出，而是由 SimplySign Desktop 连接 Certum 云后
   以虚拟卡片的形式挂到证书库里；签名时 signtool 用 /sha1 <指纹> 引用它，
   摘要算法 sha256，时间戳走 Certum 的 TSA（http://time.certum.pl）。

 环境变量（与参考项目保持一致，便于直接复用同一批 Secrets）：
   CERTUM_CERTIFICATE_SHA1  证书指纹（= Tauri 的 certificateThumbprint）；不给则自动挑选 Certum 证书
   CERTUM_USERNAME          SimplySign 登录用户名（仅 Sign-SetupCertum.ps1 用）
   CERTUM_OTP_URI           otpauth:// URI，含 TOTP 密钥（仅 Sign-SetupCertum.ps1 用）
   CERTUM_EXE_PATH          可选，SimplySign Desktop 可执行文件路径
   CERTUM_TIMESTAMP_URL     可选，覆盖时间戳服务（默认 http://time.certum.pl）
   TPMSMART_SIGNTOOL        可选，显式指定 signtool.exe
   TPMSMART_SIGN_SKIP=1     跳过签名（构建仍继续，产物不带签名）
   TPMSMART_SIGN_REQUIRED=1 证书不可用或签名失败时直接失败（CI 用，避免静默出未签名产物）
 ---------------------------------------------------------------------------
#>

# 默认时间戳服务：Certum 的 TSA（与参考项目一致），失败时按顺序回退
$Script:CertumDefaultTimestampUrls = @(
    'http://time.certum.pl',
    'http://timestamp.digicert.com',
    'http://timestamp.sectigo.com'
)

function Write-SignLog {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [ValidateSet('INFO', 'OK', 'WARN', 'ERROR')][string]$Level = 'INFO'
    )
    $prefix = '[签名]'
    switch ($Level) {
        'OK'    { Write-Host "$prefix $Message" -ForegroundColor Green }
        'WARN'  { Write-Host "$prefix $Message" -ForegroundColor Yellow }
        'ERROR' { Write-Host "$prefix $Message" -ForegroundColor Red }
        default { Write-Host "$prefix $Message" }
    }
}

# 环境变量真假判断（'1'/'true'/'yes'/'on' 视为真）
function Test-SignEnvFlag {
    param([string]$Name, [bool]$Default = $false)
    $raw = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
    return @('1', 'true', 'yes', 'on') -contains $raw.Trim().ToLowerInvariant()
}

# 定位 signtool.exe：TPMSMART_SIGNTOOL → SIGNTOOL → PATH → Windows Kits（取最新 SDK）
function Get-SignToolPath {
    $explicit = @($env:TPMSMART_SIGNTOOL, $env:SIGNTOOL) | Where-Object { $_ -and $_.Trim() }
    foreach ($candidate in $explicit) {
        if (Test-Path -LiteralPath $candidate) { return (Resolve-Path -LiteralPath $candidate).Path }
    }

    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }

    $roots = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'),
        (Join-Path $env:ProgramFiles 'Windows Kits\10\bin')
    )
    $best = $null
    $bestVersion = $null
    foreach ($root in $roots) {
        if (-not $root -or -not (Test-Path -LiteralPath $root)) { continue }
        foreach ($dir in @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue)) {
            foreach ($candidate in @((Join-Path $dir.FullName 'x64\signtool.exe'), (Join-Path $root 'x64\signtool.exe'))) {
                if (-not (Test-Path -LiteralPath $candidate)) { continue }
                $version = $null
                try { $version = [version]$dir.Name } catch { $version = [version]'0.0' }
                if (-not $bestVersion -or $version -gt $bestVersion) {
                    $best = $candidate
                    $bestVersion = $version
                }
            }
        }
    }
    return $best
}

# 时间戳服务列表：显式指定优先，否则 Certum → DigiCert → Sectigo
function Get-TimestampUrls {
    param([string]$Url)
    if ($Url) { return @($Url) }
    if ($env:CERTUM_TIMESTAMP_URL) { return @($env:CERTUM_TIMESTAMP_URL) }
    if ($env:TPMSMART_SIGN_TIMESTAMP_URL) { return @($env:TPMSMART_SIGN_TIMESTAMP_URL) }
    return $Script:CertumDefaultTimestampUrls
}

# 是否为 Certum 签发的证书（云签名证书都挂在 Certum 的 CA 链下）
function Test-CertumCertificate {
    param($Cert)
    if (-not $Cert) { return $false }
    return ($Cert.Issuer -match 'Certum') -or ($Cert.Subject -match 'Certum')
}

# 证书库里的全部候选证书（带来源存储标记，供 signtool 决定是否加 /sm）
# 注意：这里刻意用 .NET 的 X509Store，而不是 PowerShell 的 Cert:\ 驱动器 ——
# Cert: 由 Microsoft.PowerShell.Security 模块提供，当脚本是「由 ISCC、Python 等
# 精简环境拉起」时 PSModulePath 可能不完整，会出现
#   Cannot find drive. A drive with the name 'Cert' does not exist.
# 而 X509Store 只依赖 .NET，行为稳定。
function Get-StoreCertificateCandidates {
    $result = @()
    $locations = @(
        [pscustomobject]@{ Location = [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser; Machine = $false },
        [pscustomobject]@{ Location = [System.Security.Cryptography.X509Certificates.StoreLocation]::LocalMachine; Machine = $true }
    )
    foreach ($item in $locations) {
        $store = $null
        try {
            $store = New-Object System.Security.Cryptography.X509Certificates.X509Store('My', $item.Location)
            $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
            foreach ($cert in $store.Certificates) {
                $result += [pscustomobject]@{ Cert = $cert; Machine = $item.Machine }
            }
        } catch {
            Write-SignLog "枚举证书库失败（$($item.Location)\My）：$($_.Exception.Message)" 'WARN'
        } finally {
            if ($store) { $store.Close() }
        }
    }
    return $result
}

# 读取文件的签名状态：优先用 Get-AuthenticodeSignature（能给出信任/时间戳信息），
# 该 cmdlet 不可用时退回 .NET 的 CreateFromSignedFile（只要能读到签名者证书就够用）。
# 返回 @{ Signer = <证书或 $null>; Status = <字符串> }
function Get-SignatureState {
    param([Parameter(Mandatory = $true)][string]$File)
    try {
        $sig = Get-AuthenticodeSignature -LiteralPath $File -ErrorAction Stop
        if ($sig -and $sig.SignerCertificate) {
            return [pscustomobject]@{ Signer = $sig.SignerCertificate; Status = "$($sig.Status)"; Timestamper = $sig.TimeStamperCertificate }
        }
        return [pscustomobject]@{ Signer = $null; Status = 'NotSigned'; Timestamper = $null }
    } catch { }
    try {
        $cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromSignedFile($File)
        return [pscustomobject]@{ Signer = $cert; Status = 'Signed(通过 .NET 读取)'; Timestamper = $null }
    } catch { }
    return [pscustomobject]@{ Signer = $null; Status = 'NotSigned'; Timestamper = $null }
}

function Select-CertumCandidate {
    param($Candidates, [string]$Thumbprint, [switch]$AllowNonCertum)

    $usable = @($Candidates | Where-Object { $_.Cert.HasPrivateKey -and $_.Cert.NotAfter -gt (Get-Date) })
    if ($Thumbprint) {
        $want = ($Thumbprint -replace '[^0-9a-fA-F]', '').ToUpperInvariant()
        $usable = @($usable | Where-Object {
                ($_.Cert.Thumbprint -replace '[^0-9a-fA-F]', '').ToUpperInvariant() -eq $want })
    }
    elseif (-not $AllowNonCertum) {
        $usable = @($usable | Where-Object { Test-CertumCertificate $_.Cert })
    }

    if (-not $usable) { return $null }

    # 优先 Certum 签发的证书，其次有效期更长（自动挑选时避免误用本机测试证书）
    $ordered = @($usable | Sort-Object -Property @{
            Expression = { if (Test-CertumCertificate $_.Cert) { 1 } else { 0 } }
            Descending = $true
        }, @{
            Expression = { $_.Cert.NotAfter }
            Descending = $true
        })
    return $ordered[0]
}

# 解析要用的签名证书；返回 $null 表示没找到（调用方负责提示）
function Resolve-SigningCertificate {
    param(
        [string]$Thumbprint = '',
        [switch]$AllowNonCertum
    )
    if (-not $Thumbprint) { $Thumbprint = $env:CERTUM_CERTIFICATE_SHA1 }
    $candidates = Get-StoreCertificateCandidates
    $picked = Select-CertumCandidate -Candidates $candidates -Thumbprint $Thumbprint -AllowNonCertum:$AllowNonCertum
    if (-not $picked) { return $null }

    return [pscustomobject]@{
        Certificate = $picked.Cert
        Thumbprint  = ($picked.Cert.Thumbprint -replace '[^0-9a-fA-F]', '').ToUpperInvariant()
        Machine     = $picked.Machine
        Subject     = $picked.Cert.Subject
        Issuer      = $picked.Cert.Issuer
        NotAfter    = $picked.Cert.NotAfter
        IsCertum    = (Test-CertumCertificate $picked.Cert)
    }
}

# SimplySign Desktop 的状态信息（只读文件/进程，不触碰私钥，避免弹出登录框）
function Get-SimplySignState {
    $exe = $env:CERTUM_EXE_PATH
    if (-not $exe) { $exe = 'C:\Program Files\Certum\SimplySign Desktop\SimplySignDesktop.exe' }
    $process = Get-Process -Name 'SimplySignDesktop' -ErrorAction SilentlyContinue
    return [pscustomobject]@{
        ExePath   = $exe
        Installed = (Test-Path -LiteralPath $exe)
        Running   = [bool]$process
    }
}

# 证书不可用时的统一提示
function Write-CertumGuidance {
    param([string]$Thumbprint = '')
    $state = Get-SimplySignState
    if (-not $state.Installed) {
        Write-SignLog "本机没装 SimplySign Desktop（Certum 云签名客户端）：$($state.ExePath)" 'ERROR'
    } elseif (-not $state.Running) {
        Write-SignLog 'SimplySign Desktop 未运行，云证书未挂载到证书库。' 'ERROR'
    }
    Write-SignLog '请先连接 Certum 云签名：Builds\Sign-SetupCertum.ps1 -Connect' 'ERROR'
    Write-SignLog '   （该脚本会用 CERTUM_USERNAME + CERTUM_OTP_URI 里的 TOTP 自动登录；' 'ERROR'
    Write-SignLog '     也可以手动打开 SimplySign Desktop 登录一次，然后重新构建）' 'ERROR'
    if ($Thumbprint) { Write-SignLog "期望的证书指纹：$($Thumbprint -replace '[^0-9a-fA-F]', '')" 'ERROR' }
}

# 是否已经由同一张证书签过名（避免重复签名把文件越签越大）
function Test-AlreadySigned {
    param([string]$File, [string]$Thumbprint)
    if (-not $Thumbprint) { return $false }
    $state = Get-SignatureState -File $File
    if (-not $state.Signer) { return $false }
    $signed = ($state.Signer.Thumbprint -replace '[^0-9a-fA-F]', '').ToUpperInvariant()
    return $signed -eq $Thumbprint
}

# 展开待签名文件：目录默认只取该层（-Recurse 才递归），按扩展名过滤；显式给出的文件一律包含。
# 默认只签 .exe：产物目录里还混着 python*.dll、OpenSC\*.exe 这类第三方程序，
# 给它们套上本项目的签名没有意义（要签自己的 dll 时显式传 -Extensions .exe,.dll）。
function Get-SignTargetFiles {
    param(
        [string[]]$Paths = @(),
        [switch]$Recurse,
        [string[]]$Extensions = @('.exe')
    )
    $files = New-Object System.Collections.Generic.List[string]
    $seen = @{}
    foreach ($item in $Paths) {
        if (-not $item) { continue }
        if (Test-Path -LiteralPath $item -PathType Container) {
            $found = @(Get-ChildItem -LiteralPath $item -File -Recurse:$Recurse -ErrorAction SilentlyContinue |
                    Where-Object { $Extensions -contains $_.Extension.ToLowerInvariant() })
        } elseif (Test-Path -LiteralPath $item -PathType Leaf) {
            $found = @(Get-Item -LiteralPath $item)
        } else {
            Write-SignLog "路径不存在，跳过：$item" 'WARN'
            continue
        }
        foreach ($file in $found) {
            $full = $file.FullName
            if ($seen.ContainsKey($full)) { continue }
            $seen[$full] = $true
            $files.Add($full)
        }
    }
    return $files
}

# 用 signtool 给单个文件签名（Certum 云证书 + sha256 + Certum 时间戳），失败会按时间戳服务回退重试
function Invoke-SignFile {
    param(
        [Parameter(Mandatory = $true)][string]$SignTool,
        [Parameter(Mandatory = $true)][string]$File,
        [Parameter(Mandatory = $true)]$Certificate,   # Resolve-SigningCertificate 的返回值
        [string[]]$TimestampUrls = @(),
        [int]$RetryPerUrl = 2,
        [switch]$Quiet
    )

    # 不传时间戳服务 = 直接签一次（离线自测）；传了就按顺序回退重试
    $tsUrls = @($TimestampUrls)
    $baseArgs = @('sign', '/fd', 'sha256', '/sha1', $Certificate.Thumbprint)
    if ($Certificate.Machine) { $baseArgs += '/sm' }
    if (-not $tsUrls.Count) { $tsUrls = @('') }

    $lastOutput = ''
    foreach ($ts in $tsUrls) {
        for ($attempt = 1; $attempt -le $RetryPerUrl; $attempt++) {
            $signArgs = $baseArgs
            if ($ts) { $signArgs += @('/tr', $ts, '/td', 'sha256') }
            $signArgs += $File
            if (-not $Quiet) {
                $note = if ($attempt -gt 1) { "（第 $attempt 次尝试）" } else { '' }
                $tsNote = if ($ts) { "  时间戳：$ts" } else { '  时间戳：无' }
                Write-SignLog "签名 $([IO.Path]::GetFileName($File))$note$tsNote"
            }
            $output = @(& $SignTool @signArgs 2>&1 | ForEach-Object { "$_" })
            $code = $LASTEXITCODE
            if ($code -eq 0) {
                if (-not $Quiet) { Write-SignLog "已签名：$File" 'OK' }
                return $true
            }
            $lastOutput = ($output -join "`n").Trim()
            if (-not $Quiet) { Write-SignLog "signtool 退出码 $code：$lastOutput" 'WARN' }
            if ($attempt -lt $RetryPerUrl) { Start-Sleep -Seconds 3 }
        }
    }

    Write-SignLog "签名失败：$File" 'ERROR'
    if ($lastOutput) { Write-SignLog $lastOutput 'ERROR' }
    if ($Certificate.IsCertum) {
        Write-SignLog '若报错与云证书/私钥有关，通常是 SimplySign Desktop 掉线：重新执行 Builds\Sign-SetupCertum.ps1 -Connect 后再构建。' 'ERROR'
    }
    return $false
}
