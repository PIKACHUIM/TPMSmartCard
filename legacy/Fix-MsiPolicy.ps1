# Fix-MsiPolicy.ps1
# 诊断并清除阻止 MSI 安装的策略：HKLM\SOFTWARE\Policies\Microsoft\Windows\Installer\DisableMSI
#
# 症状：安装任何 MSI 报 1625「系统策略禁止这个安装」，外壳（Burn）报 0x80070659。
#       MSI 日志里有 "Machine policy value 'DisableMsi' is 1" 与
#       "Rejecting product ...: Non-assigned apps are disabled for non-admin users."
#
# 请通过 Fix-MsiPolicy.bat 运行（会自动请求管理员权限）。
# 直接运行也可以，但必须是管理员，否则只能看诊断、改不了。
#
# 参数：
#   -DeleteKey    不只删 DisableMSI 值，把整个 Installer 键删掉（更彻底）
#   -WhatIfReport 只诊断不修改

[CmdletBinding()]
param(
    [switch]$DeleteKey,
    [switch]$WhatIfReport
)

$ErrorActionPreference = 'Continue'

$SubKey = 'SOFTWARE\Policies\Microsoft\Windows\Installer'
$Parent = 'SOFTWARE\Policies\Microsoft\Windows'

function Write-Head($t) { Write-Host ""; Write-Host "===== $t =====" -ForegroundColor Cyan }
function Write-Ok($t)   { Write-Host "  [OK]   $t" -ForegroundColor Green }
function Write-Bad($t)  { Write-Host "  [!!]   $t" -ForegroundColor Red }
function Write-Info($t) { Write-Host "         $t" -ForegroundColor Gray }

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

Write-Head '运行环境'
Write-Info ("用户: {0}" -f $id.Name)
if ($isAdmin) {
    Write-Ok '当前是管理员权限'
} else {
    Write-Bad '当前不是管理员权限 —— 只能诊断，无法修改'
    Write-Info '请改用：右键 Fix-MsiPolicy.bat -> 以管理员身份运行'
}

# ---------------------------------------------------------------- 诊断
function Get-KeyView {
    param([string]$Hive, [string]$Path)
    try {
        $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
            [Microsoft.Win32.RegistryHive]::$Hive,
            [Microsoft.Win32.RegistryView]::Default)
        $k = $base.OpenSubKey($Path)
        if ($k -eq $null) { return $null }
        $names = @($k.GetValueNames())
        $out = @()
        foreach ($n in $names) {
            $v = $k.GetValue($n)
            $out += ('{0} = {1}' -f $n, $v)
        }
        $k.Close()
        return $out
    } catch {
        return @("ERROR: " + $_.Exception.Message)
    }
}

Write-Head '1) 直接读取 Installer 键'
$found64 = Get-KeyView -Hive LocalMachine -Path $SubKey
$found32 = $null
try {
    $base32 = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::LocalMachine,
        [Microsoft.Win32.RegistryView]::Registry32)
    $k32 = $base32.OpenSubKey($SubKey)
    if ($k32 -ne $null) { $found32 = @($k32.GetValueNames() | ForEach-Object { '{0} = {1}' -f $_, $k32.GetValue($_) }); $k32.Close() }
} catch { $found32 = @("ERROR: " + $_.Exception.Message) }

if ($found64 -eq $null) {
    Write-Bad 'HKLM (64位视图) 下该键不存在'
} else {
    Write-Ok 'HKLM (64位视图) 下该键存在：'
    $found64 | ForEach-Object { Write-Info $_ }
}
if ($found32 -eq $null) {
    Write-Info 'HKLM (32位视图) 下该键不存在'
} else {
    Write-Ok 'HKLM (32位视图) 下该键存在：'
    $found32 | ForEach-Object { Write-Info $_ }
}

Write-Head '2) 父键 Policies\Microsoft\Windows 的子键列表'
try {
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::LocalMachine,
        [Microsoft.Win32.RegistryView]::Default)
    $p = $base.OpenSubKey($Parent)
    if ($p -ne $null) {
        $subs = @($p.GetSubKeyNames())
        Write-Info ("子键总数: {0}" -f $subs.Count)
        if ($subs -contains 'Installer') {
            Write-Ok 'Installer 出现在这里（说明非管理员视图是被权限过滤掉的）'
        } else {
            Write-Info 'Installer 不在列表中'
        }
        Write-Info ($subs -join '|')
        $p.Close()
    }
} catch {
    Write-Info ('读取失败: ' + $_.Exception.Message)
}

# ---------------------------------------------------------------- 所有权 / ACL
Write-Head '3) 键的所有权与访问控制'
$takeOwned = $false
if ($found64 -ne $null -and -not $isAdmin) {
    Write-Info '非管理员，跳过'
} elseif ($found64 -ne $null) {
    try {
        $k = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey(
            $SubKey,
            [Microsoft.Win32.RegistryKeyPermissionCheck]::ReadWriteSubTree,
            [System.Security.AccessControl.RegistryRights]::TakeOwnership)
        $acl = $k.GetAccessControl([System.Security.AccessControl.AccessControlSections]::None)
        $owner = $acl.GetOwner([System.Security.Principal.SecurityIdentifier])
        Write-Info ("所有者: {0}" -f $owner.Value)
        $acl2 = $k.GetAccessControl()
        Write-Info '访问规则:'
        $acl2.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]) |
            ForEach-Object { Write-Info ("  {0} {1} {2}" -f $_.IdentityReference, $_.AccessControlType, $_.RegistryRights) }
        $k.Close()
    } catch {
        Write-Info ('读取 ACL 失败: ' + $_.Exception.Message)
    }
} else {
    $adminsSid = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
    $adminsName = try { $adminsSid.Translate([System.Security.Principal.NTAccount]).Value } catch { 'Administrators' }

    $needRepair = $false
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::LocalMachine,
        [Microsoft.Win32.RegistryView]::Default)
    try {
        # 用 TakeOwnership 权限试探：键存在但普通读被拒时，这里会成功
        $k = $base.OpenSubKey($SubKey,
            [Microsoft.Win32.RegistryKeyPermissionCheck]::ReadWriteSubTree,
            [System.Security.AccessControl.RegistryRights]::TakeOwnership)
        if ($k -ne $null) {
            $needRepair = $true
            Write-Bad '普通读取拿不到，但以 TakeOwnership 权限能打开 —— 键存在，只是 ACL 把非管理员（以及默认读）挡掉了'
            $acl = $k.GetAccessControl([System.Security.AccessControl.AccessControlSections]::None)
            $acl.SetOwner($adminsSid)
            $k.SetAccessControl($acl)
            Write-Ok ("已把所有者改为 {0} ({1})" -f $adminsName, $adminsSid.Value)
            $takeOwned = $true
            $k.Close()

            # 重新授权
            $k2 = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey(
                $SubKey,
                [Microsoft.Win32.RegistryKeyPermissionCheck]::ReadWriteSubTree,
                [System.Security.AccessControl.RegistryRights]::ChangePermissions)
            $acl2 = $k2.GetAccessControl()
            $rule = New-Object System.Security.AccessControl.RegistryAccessRule(
                $adminsSid, 'FullControl', 'Allow')
            $acl2.SetAccessRule($rule)
            $k2.SetAccessControl($acl2)
            Write-Ok '已授予 Administrators 完全控制'
            $k2.Close()

            $found64 = Get-KeyView -Hive LocalMachine -Path $SubKey
            if ($found64 -ne $null) {
                Write-Ok '现在可以读到内容了：'
                $found64 | ForEach-Object { Write-Info $_ }
            }
        } else {
            Write-Info '以 TakeOwnership 权限也打不开 —— 该键确实不存在（不是权限问题）'
        }
    } catch {
        Write-Info ('所有权处理失败: ' + $_.Exception.Message)
    }
}

# ---------------------------------------------------------------- 修
$hasDisableMsi = $false
if ($found64 -ne $null) {
    foreach ($line in $found64) { if ($line -like 'DisableMSI*') { $hasDisableMsi = $true } }
}

Write-Head '4) 处理结果'
if ($WhatIfReport) {
    Write-Info '-WhatIfReport：只诊断，未做修改'
} elseif (-not $isAdmin) {
    Write-Bad '非管理员，未做修改。请用 Fix-MsiPolicy.bat（管理员）重跑。'
} elseif ($found64 -eq $null -and -not $takeOwned) {
    Write-Bad '管理员视图下这个键也不存在 —— 那么 DisableMsi=1 不是从*这里*来的。'
    Write-Info '下一步（把下面命令的输出发我）：'
    Write-Info '  reg query "HKLM\SOFTWARE\Policies\Microsoft\Windows\Installer" /s /reg:64'
    Write-Info '  reg query "HKLM\SOFTWARE\Policies\Microsoft\Windows\Installer" /s /reg:32'
    Write-Info '  reg query "HKCU\SOFTWARE\Policies\Microsoft\Windows\Installer" /s'
    Write-Info '  gpresult /scope computer /r'
} else {
    try {
        if ($DeleteKey) {
            [Microsoft.Win32.Registry]::LocalMachine.DeleteSubKeyTree($SubKey, $false)
            Write-Ok '已删除整个 Installer 键'
        } elseif ($hasDisableMsi) {
            $k = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($SubKey, $true)
            $k.DeleteValue('DisableMSI', $false)
            $k.Close()
            Write-Ok '已删除 DisableMSI 值'
        } else {
            Write-Info '键里没有 DisableMSI 值（可能已被别的动作清掉）'
        }
    } catch {
        Write-Bad ('删除失败: ' + $_.Exception.Message)
        Write-Info '可改用 -DeleteKey，或在管理员 CMD 里执行：'
        Write-Info '  reg delete "HKLM\SOFTWARE\Policies\Microsoft\Windows\Installer" /v DisableMSI /f'
    }
}

# ---------------------------------------------------------------- 复验
Write-Head '5) 复验'
$after = Get-KeyView -Hive LocalMachine -Path $SubKey
if ($after -eq $null) {
    Write-Ok 'Installer 键已不存在（DisableMSI 也就没有了）'
} else {
    $after | ForEach-Object { Write-Info $_ }
    $still = $false
    foreach ($line in $after) { if ($line -like 'DisableMSI=1*' -or $line -like 'DisableMSI = 1*') { $still = $true } }
    if ($still) { Write-Bad 'DisableMSI 仍然是 1，没清掉' } else { Write-Ok 'DisableMSI 已不是 1' }
}

Write-Head '6) 顺带看一下本地组策略'
$pol = Join-Path $env:windir 'System32\GroupPolicy\Machine\Registry.pol'
if (Test-Path $pol) {
    $len = (Get-Item $pol).Length
    $txt = ''
    try {
        $bytes = [System.IO.File]::ReadAllBytes($pol)
        $txt = ([System.Text.Encoding]::Unicode.GetString($bytes) -replace '[^\x20-\x7E]', '')
    } catch { }
    Write-Info ("Registry.pol 大小: {0} 字节" -f $len)
    if ($len -le 16) {
        Write-Info '内容基本为空（本地没有注册表类策略）'
    } else {
        Write-Info ('内容片段: ' + $txt)
        Write-Info '其中 **del.XXX 表示"删除该值"；出现 DisableMSI 数值条目说明本地策略在设置它'
    }
} else {
    Write-Info '没有本地组策略文件'
}

Write-Host ""
Write-Host "完成后请重跑安装程序验证。如果仍报 1625，请把本脚本的完整输出发回来。" -ForegroundColor Yellow
if (-not $isAdmin) {
    Write-Host "（注意：这次不是管理员权限，所以什么都没改）" -ForegroundColor Yellow
}
