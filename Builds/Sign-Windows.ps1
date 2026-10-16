<#
 Builds/Sign-Windows.ps1 —— 用 Certum 云签名（SimplySign）给 PE 文件签名
 ---------------------------------------------------------------------------
 给文件或目录里的 .exe/.dll 签名；证书来自证书库中 Certum 云证书（默认按
 CERTUM_CERTIFICATE_SHA1 指定，未指定时自动挑选 Certum 签发、未过期的证书）。

 用法：
   # 给 cx_Freeze 产物顶层 exe 签名（BuildPackage.py 构建后会自动调用）
   .\Builds\Sign-Windows.ps1 -Path 'build\exe.win-amd64-3.13'

   # 多个目标用 , 或 ; 分隔（也支持在 PowerShell 里传数组）
   .\Builds\Sign-Windows.ps1 -Path 'a.exe;b.exe'

   # 只看会签哪些文件、用哪张证书（不落笔）
   .\Builds\Sign-Windows.ps1 -Path 'build\exe.win-amd64-3.13' -ListOnly

 退出码：
   0  签名成功，或「没有可用证书且未要求强制签名」的跳过（本地开发机常见）
   1  证书可用但签名失败；或设置了 TPMSMART_SIGN_REQUIRED=1 却拿不到证书

 注意：Certum 云证书的私钥在云上，必须先用 SimplySign Desktop 登录（见
 Builds\Sign-SetupCertum.ps1），证书才会挂到本机证书库供 signtool 使用。
 ---------------------------------------------------------------------------
#>
param(
    [string[]]$Path = @(),
    [switch]$Recurse,
    [string]$Thumbprint = $env:CERTUM_CERTIFICATE_SHA1,
    [string]$TimestampUrl = '',
    [string[]]$Extensions = @('.exe'),
    [switch]$Force,        # 已由同一张证书签过名的文件也重新签
    [switch]$ListOnly,     # 只输出将要签名/使用的证书，不实际签名
    [switch]$NoTimestamp,  # 不加时间戳（离线环境自测用；正式产物务必带时间戳）
    [switch]$AllowNonCertum, # 允许用非 Certum 证书（仅用于本机链路自测）
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'CertumSigning.ps1')

$required = Test-SignEnvFlag 'TPMSMART_SIGN_REQUIRED'
$skip = Test-SignEnvFlag 'TPMSMART_SIGN_SKIP'

if ($skip -and -not $required) {
    Write-SignLog '已设置 TPMSMART_SIGN_SKIP=1，跳过签名。' 'WARN'
    exit 0
}

# -Path 允许多个目标。注意：用 powershell.exe -File 调进来时参数不会被拆成数组
# （"a,b" 会被当成一个字符串），因此这里统一再按 , ; 换行 拆一次，两种调用方式都成立。
$targets = @()
foreach ($item in $Path) {
    if (-not $item) { continue }
    foreach ($part in ($item -split '[,;\r\n]')) {
        $trimmed = $part.Trim().Trim('"')
        if ($trimmed) { $targets += $trimmed }
    }
}
if (-not $targets.Count) {
    Write-SignLog '没有指定要签名的文件/目录（-Path）。' 'ERROR'
    exit 1
}

$signTool = Get-SignToolPath
if (-not $signTool) {
    Write-SignLog '找不到 signtool.exe：请安装 Windows SDK（或通过 TPMSMART_SIGNTOOL 指定路径）。' 'ERROR'
    if ($required) { exit 1 }
    Write-SignLog '本次不做签名，继续构建。' 'WARN'
    exit 0
}

$cert = Resolve-SigningCertificate -Thumbprint $Thumbprint -AllowNonCertum:$AllowNonCertum
if (-not $cert) {
    Write-SignLog '证书库里找不到可用的签名证书。' 'ERROR'
    Write-CertumGuidance -Thumbprint $Thumbprint
    if ($required) { exit 1 }
    Write-SignLog '本次不做签名，继续构建（CI 上请确认 CERTUM_CERTIFICATE_SHA1 与 Certum 登录状态）。' 'WARN'
    exit 0
}

$files = Get-SignTargetFiles -Paths $targets -Recurse:$Recurse -Extensions $Extensions
if (-not $files.Count) {
    Write-SignLog "没有匹配到要签名的文件（扩展名：$($Extensions -join ' ')）。" 'WARN'
    if ($required) { exit 1 }
    exit 0
}

Write-SignLog "signtool   : $signTool"
Write-SignLog "签名证书   : $($cert.Subject)"
Write-SignLog "签发者     : $($cert.Issuer)"
Write-SignLog "证书指纹   : $($cert.Thumbprint)$(if ($cert.Machine) { '（本机存储，/sm）' } else { '' })"
Write-SignLog "有效期至   : $($cert.NotAfter.ToString('yyyy-MM-dd'))"
$timestampUrls = if ($NoTimestamp) { @() } else { Get-TimestampUrls -Url $TimestampUrl }
if ($timestampUrls.Count) {
    Write-SignLog "时间戳服务 : $($timestampUrls -join ' , ')"
} else {
    Write-SignLog '时间戳服务 : 无（-NoTimestamp）' 'WARN'
}
Write-SignLog "待签文件   : $($files.Count) 个"

if ($ListOnly) {
    foreach ($file in $files) {
        $already = Test-AlreadySigned -File $file -Thumbprint $cert.Thumbprint
        Write-SignLog "  $(if ($already) { '[已签名]' } else { '[待签名]' }) $file"
    }
    Write-SignLog '（-ListOnly：未实际签名）'
    exit 0
}

$failed = @()
$signedCount = 0
$skippedCount = 0
foreach ($file in $files) {
    if (-not $Force -and (Test-AlreadySigned -File $file -Thumbprint $cert.Thumbprint)) {
        $skippedCount++
        if (-not $Quiet) { Write-SignLog "已由同一证书签名，跳过：$file" }
        continue
    }
    if (Invoke-SignFile -SignTool $signTool -File $file -Certificate $cert `
            -TimestampUrls $timestampUrls -Quiet:$Quiet) {
        $signedCount++
    } else {
        $failed += $file
    }
}

Write-SignLog "结果：新签名 $signedCount 个，已是同一签名跳过 $skippedCount 个，失败 $($failed.Count) 个。"
if ($failed.Count) {
    foreach ($file in $failed) { Write-SignLog "  失败：$file" 'ERROR' }
    exit 1
}
exit 0
