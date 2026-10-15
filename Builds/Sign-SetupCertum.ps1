<#
 Builds/Sign-SetupCertum.ps1 —— 准备 Certum 云签名环境（SimplySign Desktop）
 ---------------------------------------------------------------------------
 把参考项目 OpenList-Desktop（https://github.com/OpenListTeam/OpenList-Desktop）里
 三步走的 Windows 云签名准备流程合并成一个脚本：

   1) -Install            下载并静默安装 SimplySign Desktop（对应 install-simplysign.sh）
   2) -ConfigureRegistry  写入 HKCU\Software\Certum\SimplySign，让登录框自动弹出
                          （对应 configure-simplysign-registry.ps1）
   3) -Connect            用 CERTUM_USERNAME + CERTUM_OTP_URI(TOTP) 自动登录，
                          并轮询证书库确认云证书（含私钥）已就绪
                          （对应 Connect-SimplySign-Enhanced.ps1）
   4) -Verify             只检查「证书是否已挂载且带私钥」，用于构建前确认

 不给任何开关时 = 全部执行（Install + ConfigureRegistry + Connect + Verify）。

 用法（本地或 CI 都一样）：
   $env:CERTUM_USERNAME = 'your-account'
   $env:CERTUM_OTP_URI  = 'otpauth://totp/Certum:your-account?secret=XXXX&algorithm=SHA256&digits=6&period=30'
   $env:CERTUM_CERTIFICATE_SHA1 = '929F16F67222DCFA6A3C15A774F5F460FA79FED1'
   .\Builds\Sign-SetupCertum.ps1            # 一条命令准备完毕
   .\Builds\Sign-SetupCertum.ps1 -Verify    # 之后只用确认证书还在

 说明：Certum 云证书的私钥不可导出，也无法用 PFX 分发，只能靠 SimplySign Desktop
 在本机把「虚拟卡片」挂进证书库，因此 CI 上必须跑一次登录；本地开发机登录一次即可
 （注册表里 UnregisterCertificatesOnDisconnect=0，断开后证书仍留在库里）。
 ---------------------------------------------------------------------------
#>
param(
    [switch]$Install,
    [switch]$ConfigureRegistry,
    [switch]$Connect,
    [switch]$Verify,
    [string]$OtpUri = $env:CERTUM_OTP_URI,
    [string]$UserId = $env:CERTUM_USERNAME,
    [string]$ExePath = $env:CERTUM_EXE_PATH,
    [string]$ExpectedCertificateSHA1 = $env:CERTUM_CERTIFICATE_SHA1,
    [int]$MaxAttempts = 10,
    [switch]$ForceInstall
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'CertumSigning.ps1')

if (-not ($Install -or $ConfigureRegistry -or $Connect -or $Verify)) {
    $Install = $true
    $ConfigureRegistry = $true
    $Connect = $true
    $Verify = $true
}

if (-not $ExePath) { $ExePath = 'C:\Program Files\Certum\SimplySign Desktop\SimplySignDesktop.exe' }

$RegistryPath = 'HKCU:\Software\Certum\SimplySign'
# 参考项目 configure-simplysign-registry.ps1 的最优自动化配置：
#   登录框自动弹、记住用户名、断开后不注销证书、CSP 里记住 PIN（签名时不再弹框）
$OptimalSettings = [ordered]@{
    'ShowLoginDialogOnStart'               = 1
    'ShowLoginDialogOnAppRequest'          = 1
    'RememberLastUserName'                 = 1
    'Autostart'                            = 0
    'UnregisterCertificatesOnDisconnect'   = 0
    'RememberPINinCSP'                     = 1
    'ForgetPINinCSPonDisconnect'           = 1
    'LangID'                               = 9
}

function Get-SimplySignMsiUrl {
    # 从 Certum 软件页解析最新版 64 位 MSI，避免写死版本失效；失败则用参考项目的兜底地址
    $fallback = 'https://files.certum.eu/software/SimplySignDesktop/Windows/9.4.3.90/SimplySignDesktop-9.4.3.90-64-bit-pl.msi'
    $pageUrl = 'https://pomoc.certum.pl/pl/oprogramowanie/procertum-smartsign/'
    try {
        $page = (Invoke-WebRequest -Uri $pageUrl -UseBasicParsing -TimeoutSec 60).Content
        $pattern = 'https://(www\.)?files\.certum\.eu/software/SimplySignDesktop/Windows/[0-9.]+/SimplySignDesktop-[0-9.]+-64-bit[^"''\s]*\.msi'
        $candidates = @([regex]::Matches($page, $pattern) | ForEach-Object { $_.Value } | Sort-Object -Unique)
        if ($candidates.Count) {
            $latest = ($candidates |
                ForEach-Object { [pscustomobject]@{ Url = $_; Version = [version]([regex]::Match($_, '/Windows/([0-9.]+)/').Groups[1].Value) } } |
                Sort-Object -Property Version -Descending | Select-Object -First 1)
            $sameVersion = @($candidates | Where-Object { $_ -match "/Windows/$([regex]::Escape($latest.Version.ToString()))/" })
            foreach ($preferred in @('-64-bit-en.msi', '-64-bit-pl.msi')) {
                $hit = $sameVersion | Where-Object { $_ -like "*$preferred" } | Select-Object -First 1
                if ($hit) { return $hit }
            }
            return $sameVersion[0]
        }
    } catch {
        Write-SignLog "解析 Certum 软件页失败（$($_.Exception.Message)），改用兜底地址。" 'WARN'
    }
    return $fallback
}

function Install-SimplySignDesktop {
    if ((Test-Path -LiteralPath $ExePath) -and -not $ForceInstall) {
        Write-SignLog "SimplySign Desktop 已安装：$ExePath"
        return $true
    }

    $url = Get-SimplySignMsiUrl
    $msi = Join-Path $env:TEMP 'SimplySignDesktop.msi'
    $log = Join-Path $env:TEMP 'simplysign-install.log'
    Write-SignLog "下载 SimplySign Desktop：$url"
    try {
        Invoke-WebRequest -Uri $url -OutFile $msi -UseBasicParsing -TimeoutSec 600
    } catch {
        Write-SignLog "下载失败：$($_.Exception.Message)" 'ERROR'
        return $false
    }
    Write-SignLog ("已下载 {0}（{1:N1} MB）" -f $msi, ((Get-Item -LiteralPath $msi).Length / 1MB))

    Write-SignLog '静默安装 SimplySign Desktop（msiexec /quiet）…'
    $install = Start-Process -FilePath 'msiexec.exe' -PassThru -Wait -ArgumentList @(
        '/i', $msi, '/quiet', '/norestart', '/l*v', $log, 'ALLUSERS=1', 'REBOOT=ReallySuppress'
    )
    $ok = @(0, 1638, 1639, 3010, 1641) -contains $install.ExitCode
    if ($ok -and (Test-Path -LiteralPath $ExePath)) {
        Write-SignLog "SimplySign Desktop 安装完成（退出码 $($install.ExitCode)）。" 'OK'
        return $true
    }
    Write-SignLog "安装失败（退出码 $($install.ExitCode)）。安装日志：$log" 'ERROR'
    if (Test-Path -LiteralPath $log) {
        Get-Content -LiteralPath $log -Tail 15 | ForEach-Object { Write-SignLog "  $_" 'ERROR' }
    }
    return $false
}

function Set-SimplySignRegistry {
    foreach ($path in @('HKCU:\Software\Certum', $RegistryPath)) {
        if (-not (Test-Path -LiteralPath $path)) { New-Item -Path $path -Force | Out-Null }
    }
    $failed = @()
    foreach ($name in $OptimalSettings.Keys) {
        try {
            Set-ItemProperty -Path $RegistryPath -Name $name -Value $OptimalSettings[$name] -Type DWord -ErrorAction Stop
        } catch {
            $failed += $name
            Write-SignLog "注册表 $name 写入失败：$($_.Exception.Message)" 'WARN'
        }
    }
    if ($failed.Count) {
        Write-SignLog "注册表配置不完整（失败 $($failed.Count) 项）。" 'ERROR'
        return $false
    }
    Write-SignLog "注册表已配置 $($OptimalSettings.Count) 项（HKCU\Software\Certum\SimplySign）。" 'OK'
    return $true
}

function Normalize-Sha1 {
    param([string]$Value)
    if (-not $Value) { return $null }
    return ($Value -replace '[^a-fA-F0-9]', '').ToUpperInvariant()
}

function Find-CertificateByThumbprint {
    param([string]$Thumbprint)
    if (-not $Thumbprint) { return @() }
    # 走 CertumSigning.ps1 里的 .NET 证书库读取（不依赖 PowerShell 的 Cert: 驱动器）
    return @(Get-StoreCertificateCandidates |
            Where-Object { (Normalize-Sha1 $_.Cert.Thumbprint) -eq $Thumbprint } |
            ForEach-Object { $_.Cert })
}

function Connect-Certum {
    param([int]$Attempts = 10)

    if (-not $OtpUri) { Write-SignLog '缺少 CERTUM_OTP_URI（otpauth:// 形式的 TOTP 密钥）。' 'ERROR'; return $false }
    if (-not $UserId) { Write-SignLog '缺少 CERTUM_USERNAME（SimplySign 登录账号）。' 'ERROR'; return $false }
    if (-not (Test-Path -LiteralPath $ExePath)) {
        Write-SignLog "找不到 SimplySign Desktop：$ExePath" 'ERROR'
        if (-not $Install) { Write-SignLog '可以加 -Install 先安装。' 'ERROR' }
        return $false
    }

    $normalizedExpected = Normalize-Sha1 $ExpectedCertificateSHA1
    if ($normalizedExpected -and $normalizedExpected.Length -ne 40) {
        Write-SignLog "CERTUM_CERTIFICATE_SHA1 规范化后长度不是 40：$normalizedExpected" 'ERROR'
        return $false
    }

    # ---- 解析 otpauth:// URI ----
    $uri = [Uri]$OtpUri
    try {
        $query = [System.Web.HttpUtility]::ParseQueryString($uri.Query)
    } catch {
        $query = @{}
        foreach ($part in $uri.Query.TrimStart('?') -split '&') {
            $kv = $part -split '=', 2
            if ($kv.Count -eq 2) { $query[$kv[0]] = [Uri]::UnescapeDataString($kv[1]) }
        }
    }
    $base32 = $query['secret']
    $digits = if ($query['digits']) { [int]$query['digits'] } else { 6 }
    $period = if ($query['period']) { [int]$query['period'] } else { 30 }
    $algorithm = if ($query['algorithm']) { $query['algorithm'].ToUpperInvariant() } else { 'SHA256' }
    if (-not $base32) { Write-SignLog 'otpauth URI 里没有 secret 参数。' 'ERROR'; return $false }
    if (@('SHA1', 'SHA256', 'SHA512') -notcontains $algorithm) {
        Write-SignLog "不支持的 TOTP 算法：$algorithm" 'ERROR'
        return $false
    }

    # ---- TOTP 生成（与参考项目 Connect-SimplySign-Enhanced.ps1 同一份实现）----
    # 同一个会话里重复调用时 Add-Type 会因为类型已存在而报错，这里先探测一次
    if (-not ('CertumTotp' -as [type])) {
        Add-Type -Language CSharp @"
using System;
using System.Security.Cryptography;

public static class CertumTotp
{
    private const string B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

    private static byte[] Base32Decode(string s)
    {
        s = s.TrimEnd('=').ToUpperInvariant();
        int byteCount = s.Length * 5 / 8;
        byte[] bytes = new byte[byteCount];
        int bitBuffer = 0, bitsLeft = 0, idx = 0;
        foreach (char c in s)
        {
            int val = B32.IndexOf(c);
            if (val < 0) throw new ArgumentException("Invalid Base32 char: " + c);
            bitBuffer = (bitBuffer << 5) | val;
            bitsLeft += 5;
            if (bitsLeft >= 8)
            {
                bytes[idx++] = (byte)(bitBuffer >> (bitsLeft - 8));
                bitsLeft -= 8;
            }
        }
        return bytes;
    }

    private static HMAC GetHmac(string algorithm, byte[] key)
    {
        switch (algorithm.ToUpper())
        {
            case "SHA1": return new HMACSHA1(key);
            case "SHA256": return new HMACSHA256(key);
            case "SHA512": return new HMACSHA512(key);
            default: throw new ArgumentException("Unsupported algorithm: " + algorithm);
        }
    }

    public static string Now(string secret, int digits, int period, string algorithm)
    {
        byte[] key = Base32Decode(secret);
        long counter = DateTimeOffset.UtcNow.ToUnixTimeSeconds() / period;
        byte[] cnt = BitConverter.GetBytes(counter);
        if (BitConverter.IsLittleEndian) Array.Reverse(cnt);

        byte[] hash;
        using (var hmac = GetHmac(algorithm, key)) { hash = hmac.ComputeHash(cnt); }

        int offset = hash[hash.Length - 1] & 0x0F;
        int binary =
            ((hash[offset] & 0x7F) << 24) |
            ((hash[offset + 1] & 0xFF) << 16) |
            ((hash[offset + 2] & 0xFF) << 8) |
            (hash[offset + 3] & 0xFF);
        int otp = binary % (int)Math.Pow(10, digits);
        return otp.ToString(new string('0', digits));
    }
}
"@
    }

    # ---- 窗口聚焦（无人值守时登录框可能不在前台，SendKeys 会投递到前台窗口）----
    if (-not ('CertumWin32' -as [type])) {
        Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class CertumWin32
{
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    [DllImport("user32.dll")] public static extern bool AllowSetForegroundWindow(int dwProcessId);
    public const int SW_RESTORE = 9;
}
"@
    }

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        Write-SignLog "=== SimplySign 登录尝试 $attempt / $Attempts ==="
        $otp = [CertumTotp]::Now($base32, $digits, $period, $algorithm)

        Get-Process -Name 'SimplySignDesktop' -ErrorAction SilentlyContinue |
            Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2

        $proc = Start-Process -FilePath $ExePath -PassThru
        Start-Sleep -Seconds 10
        [CertumWin32]::AllowSetForegroundWindow($proc.Id) | Out-Null

        $wshell = New-Object -ComObject WScript.Shell
        $focused = $false
        $proc.Refresh()
        $handle = $proc.MainWindowHandle
        if ($handle -ne $null -and $handle -ne [IntPtr]::Zero) {
            [CertumWin32]::ShowWindow($handle, 9) | Out-Null
            [CertumWin32]::SetForegroundWindow($handle) | Out-Null
            $focused = $true
        }
        if (-not $focused) {
            $hwnd = [CertumWin32]::FindWindow($null, 'SimplySign Desktop')
            if ($hwnd -ne [IntPtr]::Zero) {
                [CertumWin32]::ShowWindow($hwnd, 9) | Out-Null
                [CertumWin32]::SetForegroundWindow($hwnd) | Out-Null
                $focused = $true
            }
        }
        for ($i = 0; (-not $focused) -and ($i -lt 20); $i++) {
            Start-Sleep -Seconds 1
            $proc.Refresh()
            if ($proc.MainWindowHandle -ne [IntPtr]::Zero) {
                [CertumWin32]::ShowWindow($proc.MainWindowHandle, 9) | Out-Null
                [CertumWin32]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
                $focused = $true
                break
            }
            $focused = $wshell.AppActivate($proc.Id)
            if (-not $focused) { $focused = $wshell.AppActivate('SimplySign Desktop') }
            if (-not $focused) { $focused = $wshell.AppActivate('SimplySign') }
        }
        if (-not $focused) {
            Write-SignLog '未能把 SimplySign Desktop 窗口切到前台，仍继续注入凭据（可能以后台/托盘进程存在）。' 'WARN'
        }

        Start-Sleep -Milliseconds 400
        Write-SignLog '注入凭据：用户名 → TAB → 动态口令 → 回车'
        $wshell.SendKeys($UserId)
        Start-Sleep -Milliseconds 200
        $wshell.SendKeys('{TAB}')
        Start-Sleep -Milliseconds 200
        $wshell.SendKeys($otp)
        Start-Sleep -Milliseconds 200
        $wshell.SendKeys('{ENTER}')
        Start-Sleep -Seconds 5

        if (-not $normalizedExpected) {
            Write-SignLog '未提供 CERTUM_CERTIFICATE_SHA1，无法校验证书，按已提交登录处理。' 'WARN'
            return $true
        }

        # 轮询证书库，确认云证书已挂载且带私钥（= 云端解锁成功）
        for ($i = 0; $i -lt 15; $i++) {
            $matched = Find-CertificateByThumbprint -Thumbprint $normalizedExpected
            if ($matched.Count -gt 0 -and ($matched | Where-Object { $_.HasPrivateKey }).Count -gt 0) {
                Write-SignLog "证书已就绪：$($matched[0].Subject)" 'OK'
                return $true
            }
            Start-Sleep -Seconds 2
        }

        Write-SignLog "第 $attempt 次登录后仍未看到可用证书（可能验证码已过期或账号/密钥不对）。" 'WARN'
        Get-Process -Id $proc.Id -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        if ($attempt -lt $Attempts) { Start-Sleep -Seconds 5 }
    }

    Write-SignLog "连续 $Attempts 次登录都没能挂载云证书。" 'ERROR'
    return $false
}

function Test-CertumReady {
    if (-not $ExpectedCertificateSHA1) {
        Write-SignLog '未设置 CERTUM_CERTIFICATE_SHA1，跳过证书校验。' 'WARN'
        return $true
    }
    $normalized = Normalize-Sha1 $ExpectedCertificateSHA1
    $matched = Find-CertificateByThumbprint -Thumbprint $normalized
    if (-not $matched.Count) {
        Write-SignLog "证书库中找不到证书 $normalized。" 'ERROR'
        return $false
    }
    $withKey = @($matched | Where-Object { $_.HasPrivateKey })
    if (-not $withKey.Count) {
        Write-SignLog "证书 $normalized 存在但没有可用的私钥（云签名未连接）。" 'ERROR'
        return $false
    }
    Write-SignLog "证书可用：$($withKey[0].Subject)" 'OK'
    return $true
}

$failedSteps = @()
if ($Install) {
    if (-not (Install-SimplySignDesktop)) { $failedSteps += 'Install' }
}
if ($ConfigureRegistry) {
    if (-not (Set-SimplySignRegistry)) { $failedSteps += 'ConfigureRegistry' }
}
if ($Connect) {
    if (-not (Connect-Certum -Attempts $MaxAttempts)) { $failedSteps += 'Connect' }
}
if ($Verify) {
    if (-not (Test-CertumReady)) { $failedSteps += 'Verify' }
}

if ($failedSteps.Count) {
    Write-SignLog "以下步骤失败：$($failedSteps -join '、')" 'ERROR'
    exit 1
}
Write-SignLog 'Certum 云签名环境已就绪。' 'OK'
exit 0
