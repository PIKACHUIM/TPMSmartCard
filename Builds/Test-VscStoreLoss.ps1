<#
  Test-VscStoreLoss.ps1
  ---------------------------------------------------------------------------
  验证场景 B / C：智能卡 store 文件意外丢失、或系统重装（TPM 未清除）之后，
  能否用本工具的 .tsb 备份把卡片救回来。

  做法（可逆）：
    1) 用本工具对目标卡做一份新的 .tsb 备份（快照就是当前状态，不会回退数据）；
    2) 停 SCardSvr，把卡片数据目录 Tpm 整体改名为 Tpm.bak-<时间戳>（模拟"文件丢失"）；
    3) 起服务，确认卡片已消失（这一步就是场景 B 的状态）；
    4) 用 .tsb 还原（调用工具自身的还原流程，含 TPM 校验 / 设备重新枚举）；
    5) 再次确认读卡器 / 卡片 / 私钥对象是否回来，可选做一次真实签名（需要 PIN）。

  安全性：只改名、不删数据；失败时按脚本最后的提示把 .bak 改回 Tpm 即可完全回滚。
  注意：当前版本是「整目录备份」，还原会把 Tpm 覆盖回快照那一刻的状态，
        所以本脚本第 1 步先做一份"现在"的备份，避免把其它卡的数据回退。

  用法（必须管理员 PowerShell，在程序目录下执行）：
      .\Builds\Test-VscStoreLoss.ps1 -Instance 0002 -Pin 12345678
      .\Builds\Test-VscStoreLoss.ps1 -Instance 2 -Backup "D:\bak\xxx.tsb" -Force
  ---------------------------------------------------------------------------
#>
param(
    [string]$Instance = "",                 # 卡片实例号，如 0002 / 2；省略则取第一张虚拟卡
    [string]$Backup = "",                   # 已存在的 .tsb；省略则脚本自己做一份新的
    [string]$Pin = "",                      # 可选：提供后做 PIN 校验 + 一次真实签名
    [string]$WorkDir = "$env:USERPROFILE\Desktop",
    [switch]$Force,                         # 跳过交互确认
    [switch]$SimulateOsReinstall            # 连设备节点与注册表也删掉，模拟「系统重装、TPM 未清除」
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$store = Join-Path $env:SystemRoot "ServiceProfiles\LocalService\AppData\Local\Microsoft\Windows\SmartCard\Tpm"
$opensc = Join-Path $root "OpenSC"

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "请用管理员权限运行（建卡/读 store 都需要）"
    }
}

function Get-Python {
    foreach ($c in @("python", "python3")) {
        try { $exe = (Get-Command $c -ErrorAction Stop).Source
              if ($exe -and (Test-Path $exe) -and $exe -notmatch "WindowsApps") { return $exe } } catch {}
    }
    foreach ($c in @("Python313", "Python314", "Python312", "Python311")) {
        $exe = Join-Path $env:LOCALAPPDATA "Programs\Python\$c\python.exe"
        if (Test-Path $exe) { return $exe }
    }
    throw "找不到可用的 python.exe（备份/还原步骤需要）"
}

function Invoke-Python([string]$code, [string[]]$pyArgs) {
    $f = Join-Path $env:TEMP ("vsc-test-" + [guid]::NewGuid().ToString("N") + ".py")
    [IO.File]::WriteAllText($f, $code, (New-Object Text.UTF8Encoding($false)))
    try { & $script:py $f @pyArgs } finally { Remove-Item $f -ErrorAction SilentlyContinue }
}

function Show-Readers([string]$title) {
    "----- $title -----"
    & (Join-Path $opensc "opensc-tool.exe") --list-readers
}

function Show-Keys([int]$reader) {
    "----- 读卡器 $reader 上的密钥/证书 -----"
    & (Join-Path $opensc "pkcs15-tool.exe") --reader $reader --list-keys 2>&1 | Select-Object -First 8
    & (Join-Path $opensc "pkcs15-tool.exe") --reader $reader --list-certificates 2>&1 | Select-Object -First 6
}

function Get-CardGuid([string]$uid) {
    $out = Invoke-Python @'
import sys, os
root, uid = sys.argv[1], sys.argv[2]
sys.path.insert(0, root); os.chdir(root)
from Module import TPMBackup as T
print("GUID=%s" % (T.card_store_guid(uid) or "(空)"))
'@ @($root, $uid)
    return (($out | Where-Object { $_ -match "^GUID=" } | Select-Object -First 1) -replace "^GUID=", "")
}

function Show-TpmKey([string]$guid) {
    if (-not $guid -or $guid -eq "(空)") { "----- TPM 私钥状态: 拿不到 GUID，跳过 -----"; return }
    "----- TPM 内私钥状态（按 store GUID 判定） -----"
    Invoke-Python @'
import sys, os
root, guid = sys.argv[1], sys.argv[2]
sys.path.insert(0, root); os.chdir(root)
from Module import TPMBackup as T
state, text = T.tpm_key_report(guid)
print("%s -> %s" % (state, text))
'@ @($root, $guid)
}

Assert-Admin
$script:py = Get-Python
"python : $py"
"程序目录: $root"
"卡片数据目录: $store"
if (-not (Test-Path $store)) { throw "找不到卡片数据目录，先在设备上建一张卡再测" }

# ---- 解析目标卡 ---------------------------------------------------------- #
Show-Readers "当前读卡器"
$readerNames = & (Join-Path $opensc "opensc-tool.exe") --list-readers 2>&1 |
    Where-Object { $_ -match "Microsoft Virtual Smart Card\s+(\d+)" } |
    ForEach-Object { [regex]::Match($_, "Microsoft Virtual Smart Card\s+(\d+)").Groups[1].Value }
if (-not $readerNames) { throw "当前没有虚拟读卡器，先在设备上建一张卡" }
if (-not $Instance) {
    $Instance = $readerNames[0]
    "未指定 -Instance，自动选中: $Instance"
}
$instanceNum = [int]($Instance -replace "\D", "")
$instance = "{0:D4}" -f $instanceNum
$readerName = "Microsoft Virtual Smart Card $instanceNum"
$readerIdx = -1
$idx = 0
foreach ($m in (& (Join-Path $opensc "opensc-tool.exe") --list-readers 2>&1)) {
    if ($m -match [regex]::Escape($readerName)) { $readerIdx = $idx }
    elseif ($m -match "^\d+\s") { $idx++ }
}
if ($readerIdx -lt 0) { throw "找不到读卡器 '$readerName'（实例 $instance）" }
"目标: 实例 $instance / 读卡器 '$readerName'（pcsc 编号 $readerIdx）"
$guid = Get-CardGuid $instance
"卡片 store GUID: $guid"
Show-Keys $readerIdx
Show-TpmKey $guid

# ---- 1) 备一份当前状态的 .tsb -------------------------------------------- #
if (-not $Backup) {
    $Backup = Join-Path $WorkDir ("vsc-test-$instance-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".tsb")
    "----- 生成新的备份: $Backup -----"
    Invoke-Python @'
import sys, os
root, tsb, uid = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root); os.chdir(root)
from Module import TPMBackup as T
print("admin=%s store=%s" % (T.is_admin(), T.store_state()))
rep = T.create_backup(tsb, uid=uid)
print("BACKUP=%s files=%s reg=%s scope=%s" % (rep["file"], rep["file_count"], rep["reg_count"], rep["scope"]))
if rep.get("warning"):
    print("WARN=" + rep["warning"])
'@ @($root, $Backup, $instance)
} else {
    "使用已有备份: $Backup"
}
if (-not (Test-Path $Backup)) { throw "备份文件不存在: $Backup" }

# ---- 2) 模拟"文件丢失"：把 Tpm 改名 -------------------------------------- #
$bak = "$store.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")
"`n即将执行（可回滚）:"
"  · 停止 SCardSvr"
"  · 把 '$store'"
"    改名为 '$bak'"
"  · 用 '$Backup' 还原，最后再起服务并校验"
if (-not $Force) {
    $a = Read-Host "确认继续？(y/N)"
    if ($a -ne "y" -and $a -ne "Y") { "已取消"; return }
}

Stop-Service SCardSvr -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Move-Item -LiteralPath $store -Destination $bak
"已改名 -> $bak"
if ($SimulateOsReinstall) {
    "----- 追加模拟「系统重装」：移除设备节点与注册表残留（请只在测试卡上执行） -----"
    $devId = "ROOT\SMARTCARDREADER\$instance"
    & pnputil /remove-device $devId 2>&1 | Select-Object -First 2
    if ($LASTEXITCODE -ne 0) { & pnputil /delete-device $devId 2>&1 | Select-Object -First 2 }
    & reg delete "HKLM\SYSTEM\CurrentControlSet\Enum\ROOT\SMARTCARDREADER\$instance" /f 2>&1 | Select-Object -First 2
    & reg delete "HKLM\SOFTWARE\Microsoft\Cryptography\Calais\Readers\$readerName" /f 2>&1 | Select-Object -First 2
    & pnputil /scan-devices | Out-Null
    Start-Sleep -Seconds 2
    "----- 移除设备后 TPM 私钥是否还在（若这里变 missing，说明移除设备本身也会删 TPM 密钥） -----"
    Show-TpmKey $guid
}
Start-Service SCardSvr -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Show-Readers "① 模拟文件丢失后（预期：该卡的读卡器消失）"

# ---- 3) 还原 -------------------------------------------------------------- #
"----- 用 .tsb 还原 -----"
Invoke-Python @'
import sys, os
root, tsb = sys.argv[1], sys.argv[2]
sys.path.insert(0, root); os.chdir(root)
from Module import TPMBackup as T
rep = T.restore_backup(tsb, force=True)
print("RESTORE files=%s reg=%s tpm=%s stale=%s" % (rep["file_count"], rep["reg_count"],
                                                   rep["tpm_state"], rep["stale"]))
'@ @($root, $Backup)

# ---- 4) 校验 -------------------------------------------------------------- #
Restart-Service SCardSvr -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
& pnputil /scan-devices | Out-Null
Start-Sleep -Seconds 3
Show-Readers "② 还原后（预期：读卡器回来且 Card=Yes）"
Show-Keys $readerIdx

$verdict = "无法判定"
$lines = & (Join-Path $opensc "opensc-tool.exe") --list-readers 2>&1
$line = $lines | Where-Object { $_ -match [regex]::Escape($readerName) } | Select-Object -First 1
if (-not $line) {
    $verdict = "❌ 读卡器没有回来：B/C 场景在这个环境下未通过（把 $bak 改回 $store 可回滚）"
} elseif ($line -match "Yes") {
    $verdict = "✅ 读卡器回来且卡片可识别：B/C 场景通过（私钥是否可用见下面 PIN 校验）"
} else {
    $verdict = "⚠ 读卡器回来了但没有卡片（Card=No）：数据未正确加载"
}

if ($Pin -and $readerIdx -ge 0) {
    "----- PIN 校验 + 真实签名（用卡上私钥） -----"
    & (Join-Path $opensc "pkcs15-tool.exe") --reader $readerIdx --verify-pin --pin $Pin
    $bin = Join-Path $env:TEMP "vsc-test-data.bin"
    [IO.File]::WriteAllBytes($bin, (1..32))
    & (Join-Path $opensc "pkcs15-crypt.exe") --reader $readerIdx --sign --sha-256 --pkcs1 `
        --input $bin --output ($bin + ".sig") --pin $Pin
    if (Test-Path ($bin + ".sig")) {
        "✅ 签名成功（$(  (Get-Item ($bin + ".sig")).Length ) 字节）：TPM 内的私钥仍可用"
    } else {
        "❌ 签名失败：TPM 内的密钥已不可用"
    }
} else {
    "（未提供 -Pin，跳过私钥可用性判定；可手动执行："
    ".\OpenSC\pkcs15-crypt.exe --reader $readerIdx --sign --sha-256 --pkcs1 --input <32字节文件> --output sig.bin --pin <PIN>）"
}

"`n===== 结论 ====="
$verdict
"回滚方法（如需）:  Stop-Service SCardSvr; Move-Item '$bak' '$store'; Start-Service SCardSvr"
"原数据目录保留在: $bak"
