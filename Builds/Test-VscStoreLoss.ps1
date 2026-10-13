<#
 Test-VscStoreLoss.ps1
 ---------------------------------------------------------------------------
 验证场景 B / C：智能卡 store 文件意外丢失、或系统重装（TPM 未清除）之后，
 能否用本工具的 .tsb 备份把卡片救回来。

 做法（可逆）：
   1) 用本工具对目标卡做一份新的 .tsb 备份（快照就是当前状态，不会回退数据）；
   2) 停 SCardSvr，把卡片数据目录 Tpm 整体改名为 Tpm.bak-<时间戳>（模拟"文件丢失"）；
   3) 让设备重新加载（pnputil /restart-device）——必须做这一步：改名对已经加载的驱动
      没有影响（它把卡片数据放在内存里并持有句柄），只有驱动重新打开 store 才会真的没卡；
   4) 起服务，看读卡器（① 预期该卡消失或 Card=No）；
   5) 用 .tsb 还原（调用工具自身的还原流程，含 TPM 校验 / 设备重新枚举 / 服务刷新）；
   6) 再重载设备 + 起服务，看读卡器（② 预期回来且 Card=Yes），可选做一次真实签名（需 PIN）。

 -SimulateOsReinstall：在 B 的基础上再删掉设备节点与读卡器注册项（等价于"新系统、
 无设备残留"），最接近「系统重装、TPM 未清除」。只动 -Instance 指定的那张卡。

 证据强度：① 阶段该卡确实不可见（驱动重新加载过）时，② 阶段的签名成功才算
 「磁盘数据足以重建卡片并解封 TPM 私钥」的强证据；否则只是弱证据。

 安全性：B 只改名、不删数据；出错时 finally 一定会把 SCardSvr 起回来。
   · 回滚（B）: Stop-Service SCardSvr; Move-Item '<Tpm.bak-*>' '<...\Tpm>'; Start-Service SCardSvr
   · 回滚（C）: 再跑一次还原（幂等）即可把 store + 注册表 + 设备都建回来
 断点续跑：若发现 Tpm 目录已不存在（上次中断留下的状态），会自动跳过改名，直接做还原校验。

 用法（必须管理员 PowerShell，在程序目录下执行）：
     .\Builds\Test-VscStoreLoss.ps1 -Instance 0002 -Pin 12345678
     .\Builds\Test-VscStoreLoss.ps1 -Instance 0002 -Pin 12345678 -SimulateOsReinstall
     .\Builds\Test-VscStoreLoss.ps1 -Instance 0002 -Backup "D:\bak\xxx.tsb" -Force
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

# 运行原生命令：stderr 不会变成终止错误（$ErrorActionPreference = "Stop" 下必须这样包一层），
# 返回 @{ Code = 退出码; Out = 合并后的输出 }。
function Invoke-Native([string]$exe, [string[]]$CommandArgs) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = @(& $exe @CommandArgs 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
        return [pscustomobject]@{ Code = $code; Out = (($out -join "`n").Trim()) }
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Show-NativeResult([string]$title, $result) {
    "$title -> 退出码 $($result.Code)"
    if ($result.Out) {
        $result.Out -split "\r?\n" | Where-Object { $_.Trim() } |
            Select-Object -First 4 | ForEach-Object { "    " + $_.Trim() }
    }
}

function Invoke-Python([string]$code, [string[]]$pyArgs) {
    $f = Join-Path $env:TEMP ("vsc-test-" + [guid]::NewGuid().ToString("N") + ".py")
    [IO.File]::WriteAllText($f, $code, (New-Object Text.UTF8Encoding($false)))
    try { & $script:py $f @pyArgs } finally { Remove-Item $f -ErrorAction SilentlyContinue }
}

function Get-Readers {
    & (Join-Path $opensc "opensc-tool.exe") --list-readers 2>&1
}

# 打印并返回读卡器列表（返回值供调用方过滤判断）
function Show-Readers([string]$title) {
    "----- $title -----"
    Get-Readers
}

# pcsc 列表每行形如：0    Yes    Microsoft Virtual Smart Card 0
function Get-ReaderIdx([string]$name) {
    $idx = -1
    foreach ($m in (Get-Readers)) {
        $matched = [regex]::Match($m, "^(\d+)\s.*" + [regex]::Escape($name) + "(?!\d)")
        if ($matched.Success) { $idx = [int]$matched.Groups[1].Value }
    }
    return $idx
}

function Show-Keys([int]$reader) {
    if ($reader -lt 0) { "----- 没有可用的读卡器编号，跳过密钥列表 -----"; return }
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

# 直接问 PnP（cfgmgr32）设备节点是否存在 / 是否已启动，作为"设备到底有没有"的硬判据。
function Get-DevNode([string]$uid) {
    $out = Invoke-Python @'
import ctypes, sys
uid = sys.argv[1]
kind = "missing"
try:
    cfg = ctypes.WinDLL("cfgmgr32.dll")
    node = ctypes.c_uint32(0)
    if cfg.CM_Locate_DevNodeW(ctypes.byref(node), "ROOT\\SMARTCARDREADER\\%s" % uid, 0) == 0:
        status = ctypes.c_uint32(0)
        problem = ctypes.c_uint32(0)
        if cfg.CM_Get_DevNode_Status(ctypes.byref(status), ctypes.byref(problem), node, 0) == 0:
            if status.value & 0x08:
                kind = "started"
            elif problem.value:
                kind = "problem(0x%X)" % problem.value
            else:
                kind = "present"
except Exception as err:
    kind = "unknown(%s)" % err
print("DEVNODE=%s" % kind)
'@ @($uid)
    $line = $out | Where-Object { $_ -match "^DEVNODE=" } | Select-Object -First 1
    if (-not $line) { return "unknown" }
    return ($line -replace "^DEVNODE=", "")
}

function Show-TpmKey([string]$guid) {
    if (-not $guid -or $guid -eq "(空)") { "----- TPM 私钥状态: 拿不到 GUID，跳过 -----"; return }
    "----- TPM 内私钥状态（按 store GUID 判定，仅供参考） -----"
    Invoke-Python @'
import sys, os
root, guid = sys.argv[1], sys.argv[2]
sys.path.insert(0, root); os.chdir(root)
from Module import TPMBackup as T
state, text = T.tpm_key_report(guid)
print("%s -> %s" % (state, text))
'@ @($root, $guid)
}

function Stop-CardService {
    Stop-Service SCardSvr -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

function Start-CardService {
    Start-Service SCardSvr -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

Assert-Admin
$script:py = Get-Python
"python : $script:py"
"程序目录: $root"
"卡片数据目录: $store"

# ---- 解析目标卡 ---------------------------------------------------------- #
Show-Readers "当前读卡器"
$readerNames = Get-Readers |
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
$devId = "ROOT\SMARTCARDREADER\$instance"
$readerIdx = Get-ReaderIdx $readerName
if ($readerIdx -lt 0) {
    "[警告] 当前读卡器列表里没有 '$readerName'（可能已经处于丢失/半损坏状态），继续往下走。"
} else {
    "目标: 实例 $instance / 读卡器 '$readerName'（pcsc 编号 $readerIdx）"
}
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
if (-not (Test-Path -LiteralPath $Backup)) { throw "备份文件不存在: $Backup" }

# ---- 2) 模拟"文件丢失"：把 Tpm 改名 -------------------------------------- #
$storePresent = Test-Path -LiteralPath $store
$bak = "$store.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")
$bakParent = Split-Path -Parent $store
$existingBak = @(Get-ChildItem -LiteralPath $bakParent -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "Tpm.bak-*" } | Sort-Object Name -Descending)
$pnputilHelp = (Invoke-Native pnputil @("/?")).Out

"`n即将执行（可回滚）:"
if ($storePresent) {
    "  · 停止 SCardSvr；把 '$store'"
    "    改名为 '$bak'"
} else {
    "  · 卡片数据目录已缺失（断点续跑）：跳过改名，直接用备份还原"
}
"  · 让设备重新加载（pnputil /restart-device），使『丢失』真正生效"
if ($SimulateOsReinstall) { "  · 再删掉设备节点 '$devId' 与读卡器注册项（模拟新系统）" }
"  · 用 '$Backup' 还原，然后起服务、重载设备、校验（含 PIN + 签名）"
if (-not $Force) {
    $a = Read-Host "确认继续？(y/N)"
    if ($a -ne "y" -and $a -ne "Y") { "已取消"; return }
}

$lostVisible = $false
try {
    if ($storePresent) {
        Stop-CardService
        try {
            Move-Item -LiteralPath $store -Destination $bak -ErrorAction Stop
        } catch {
            throw ("无法改名卡片数据目录（通常是被 SmartcardSimulator/WUDFRd 驱动占用）：{0}`n" -f $_.Exception.Message) +
                  "请先关闭本工具与设备管理器后重试；或用 -Backup 指定已有备份，手工改名后再跑本脚本。"
        }
        "已改名 -> $bak"
    }

    if ($SimulateOsReinstall) {
        "----- 追加模拟「系统重装」：移除设备节点与注册表残留（只动这张卡） -----"
        $removed = $false
        foreach ($verb in @("remove-device", "delete-device")) {
            if ($pnputilHelp -notmatch ("/" + [regex]::Escape($verb))) {
                "（本机 pnputil 不支持 /$verb，跳过）"
                continue
            }
            Show-NativeResult ("pnputil /$verb $devId") (Invoke-Native pnputil @("/$verb", $devId))
            if ((Get-DevNode $instance) -eq "missing") { $removed = $true; break }
        }
        if (-not $removed) {
            "[警告] 设备节点未移除（当前: $(Get-DevNode $instance)），本次「重装」模拟不完整，结论按弱证据看待。"
        }
        foreach ($key in @("HKLM\SYSTEM\CurrentControlSet\Enum\ROOT\SMARTCARDREADER\$instance",
                           "HKLM\SOFTWARE\Microsoft\Cryptography\Calais\Readers\$readerName")) {
            $r = Invoke-Native reg @("delete", $key, "/f")
            if ((Invoke-Native reg @("query", $key)).Code -eq 0) {
                "reg delete $key -> 退出码 $($r.Code)（键仍存在：通常是受 ACL 保护的子键，还原时会覆盖导入）"
            } else {
                "reg delete $key -> 已删除"
            }
        }
        Show-NativeResult "pnputil /scan-devices" (Invoke-Native pnputil @("/scan-devices"))
        Start-Sleep -Seconds 2
    } else {
        # 只改名而不重载驱动是无效测试：驱动会把卡片数据留在内存里继续用。
        if ($pnputilHelp -match "/restart-device") {
            Show-NativeResult "pnputil /restart-device $devId" (Invoke-Native pnputil @("/restart-device", $devId))
            Start-Sleep -Seconds 3
        } else {
            "[警告] 本机 pnputil 不支持 /restart-device，无法让驱动重新加载；请加 -SimulateOsReinstall，或重启系统验证。"
        }
    }

    Start-CardService
    $before = Show-Readers "① 还原前（预期：该卡消失或 Card=No；若仍是 Yes 说明驱动没重新加载，结论只能算弱证据）"
    $beforeLine = $before | Where-Object { $_ -match [regex]::Escape($readerName) } | Select-Object -First 1
    $lostVisible = (-not $beforeLine) -or ($beforeLine -notmatch "Yes")
    "设备节点状态（cfgmgr32）: $(Get-DevNode $instance)"

    # ---- 3) 还原 ---------------------------------------------------------- #
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

    # ---- 4) 校验 ---------------------------------------------------------- #
    if ($pnputilHelp -match "/restart-device") {
        # 让驱动重新打开还原后的 store：这样签名成功就证明数据确实是从 .tsb 重建的
        Show-NativeResult "pnputil /restart-device $devId" (Invoke-Native pnputil @("/restart-device", $devId))
    }
    Show-NativeResult "pnputil /scan-devices" (Invoke-Native pnputil @("/scan-devices"))
    Restart-Service SCardSvr -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3

    $after = Show-Readers "② 还原后（预期：读卡器回来且 Card=Yes）"
    $readerIdx = Get-ReaderIdx $readerName
    Show-Keys $readerIdx

    $verdict = "无法判定"
    $afterLine = $after | Where-Object { $_ -match [regex]::Escape($readerName) } | Select-Object -First 1
    if (-not $afterLine) {
        $verdict = "[FAIL] 读卡器没有回来：B/C 场景在这个环境下未通过（B 可用 Tpm.bak-* 回滚，或重启系统后再看）"
    } elseif ($afterLine -match "Yes") {
        $verdict = "[OK] 读卡器回来且卡片可识别：B/C 场景通过（私钥是否可用见下面 PIN 校验）"
    } else {
        $verdict = "[WARN] 读卡器回来了但没有卡片（Card=No）：数据未正确加载"
    }
    "设备节点状态（cfgmgr32）: $(Get-DevNode $instance)"

    if ($lostVisible) {
        "[证据强度] 强：还原前该卡已不可见（驱动重新加载过），签名成功说明数据确实是从 .tsb 重建的。"
    } else {
        "[证据强度] 弱：还原前读卡器仍在（驱动没有重新加载），不能排除『驱动内存旧状态』的影响。"
    }

    if ($Pin -and $readerIdx -ge 0) {
        "----- PIN 校验 + 真实签名（用卡上私钥） -----"
        & (Join-Path $opensc "pkcs15-tool.exe") --reader $readerIdx --verify-pin --pin $Pin
        $bin = Join-Path $env:TEMP "vsc-test-data.bin"
        [IO.File]::WriteAllBytes($bin, (1..32))
        Remove-Item -LiteralPath ($bin + ".sig") -ErrorAction SilentlyContinue
        & (Join-Path $opensc "pkcs15-crypt.exe") --reader $readerIdx --sign --sha-256 --pkcs1 `
            --input $bin --output ($bin + ".sig") --pin $Pin
        if (Test-Path ($bin + ".sig")) {
            "[OK] 签名成功（$(  (Get-Item ($bin + ".sig")).Length ) 字节）：TPM 内的私钥仍可用"
        } else {
            "[FAIL] 签名失败：TPM 内的密钥已不可用"
        }
    } else {
        "（未提供 -Pin 或没有读卡器编号，跳过私钥可用性判定；可手动执行："
        ".\OpenSC\pkcs15-crypt.exe --reader $readerIdx --sign --sha-256 --pkcs1 --input <32字节文件> --output sig.bin --pin <PIN>）"
    }

    "`n===== 结论 ====="
    $verdict
} catch {
    "[出错] " + $_.Exception.Message
    "当前状态: 设备节点=$(Get-DevNode $instance)，store 目录存在=$(Test-Path -LiteralPath $store)"
    "回滚（B）: Stop-Service SCardSvr; Move-Item '<Tpm.bak-*>' '$store'; Start-Service SCardSvr"
    "回滚（C）: 再跑一次本脚本（会自动跳过改名，用同一个 -Backup 还原即可，幂等）"
    throw
} finally {
    Start-Service SCardSvr -ErrorAction SilentlyContinue
    "（收尾）SCardSvr: $((Get-Service SCardSvr).Status)"
    if ($existingBak.Count) {
        "磁盘上保留的原始目录: " + (($existingBak | ForEach-Object { $_.FullName }) -join " | ")
    }
    if ($SimulateOsReinstall -and $bak) { "本次改名的目录（如未改名则不存在）: $bak" }
}
