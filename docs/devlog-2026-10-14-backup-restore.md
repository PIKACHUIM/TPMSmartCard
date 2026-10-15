# 开发记录：TPM 虚拟智能卡「备份 / 还原」能力落地

- 日期：2026-10-14
- 范围：`Module/TPMBackup.py`、`SmartCardAPP.py`、`Config/locales/*.json`、`Config/tsb.reg`、`install.iss`、`Builds/Test-VscStoreLoss.ps1`
- 目标：把「备份 / 还原虚拟智能卡」从"能导出一份数据"做成"换系统/文件丢失后能真的把卡片用回来"，并把能力边界讲清楚。

---

## 1. 结论速览（能力边界）

| 场景 | 是否支持 | 说明 |
|---|---|---|
| **B** 卡片 store 文件意外丢失 | ✅ 支持 | TPM 内的密钥还在，store 只是它的密文载体，还原密文即可 |
| **C** 系统重装、TPM 未清除 | ✅ 支持（需设备绑定修复，可能要重启一次） | 密钥在 TPM 里不随系统走；注册表里的"设备→store"绑定需还原后写回 |
| **A** 删卡（`tpmvscmgr destroy`）后再还原 | ❌ 默认不支持 | `destroy` 会删除 TPM 内该卡的 KSP 持久密钥，store 密文再也解不开 |
| 清除 TPM / 更换 TPM | ❌ 不可能 | 卡片密钥的父密钥在 TPM 内部，清除后无法恢复 |
| 用 AdminKey 解密 / 备份 TPM 私钥 | ❌ 不可行 | AdminKey 是卡级认证口令（用于忘记 PIN 时重置 PIN），不是密钥包装密钥 |

> 上述判定来自对 `tpmvsc.dll` 的符号级分析和本机实测，见第 2 节；A 的最终结论还需一次 CNG `ExportPolicy` 探测（见第 8 节）。

---

## 2. 逆向与实测：卡片数据的真实结构

### 2.1 `tpmvsc.dll`（10.0.26100.8457）关键符号

| 符号/字符串 | 含义 |
|---|---|
| `Microsoft Platform Crypto Provider`、`Failed to open TPM KSP`、`I_CreateKspKey` / `I_LoadKspKey` / `I_DeleteKspKey` / `I_AuthenticateKspKey` / `I_DuplicateKspKey` / `I_ImportKspKey` | 卡片密钥是 **TPM 支撑的 KSP（PCP）持久密钥** |
| `I_GenerateGuid`、`Unable to generate key name`、`protection key name`、`validation key name` | 这些持久密钥**以生成的 GUID 命名**（符号证据）——但**实测并非 store 目录名**：两张能正常签名的卡片，用 store GUID 直接 `CngKey.Open(..., MachineKey)` 同样返回 `0x80090016 密钥集不存在`，说明实际作用域/命名与 store GUID 不同（驱动以 LocalService 身份创建） |
| `NCryptCreatePersistedKey` / `NCryptOpenKey` / `NCryptSignHash` / `NCryptDecrypt` / `NCryptDeleteKey` | 卡上签名/解密**由 TPM 内的持久密钥完成**，不在软件里 |
| `I_KeyMapKeyIdToBlobFileName`、`I_PinMapCardRoleToBlobFileName`、`I_KeyMapSaveSymBlob`、`I_PinMapLoadAuthBlob` | `keymaps` / `pinmaps` 是「角色 / 密钥 ID → `blobs\<文件名>`」的映射表 |
| `KSP encryption failed`、`Unable to encrypt auth blob`、`I_EncryptSym/Asym/Locking`、`I_AuthenticatePinAndLoadAuth` | `blobs\*` 是**用 TPM KSP 加密的密钥/授权材料**，PIN 正确才解锁 |
| `TpmVCardDestroy` → `I_DeleteKspKey` / `NCryptDeleteKey` | **删卡会删除 TPM 内那颗持久密钥** |
| `I_VerifyTpmState`、`TPM verification key cannot be found. TPM ownership may have been changed.` | 清除 TPM / 重建所有权后卡片密钥必然失效 |

### 2.2 `Tpm\<GUID>\` 目录语义（由备份包内容 + 符号推出）

```
Tpm\<GUID>\
├─ keymaps      密钥映射：密钥 ID → blobs 里的文件名
├─ pinmaps      PIN 映射：卡内角色 → blobs 里的文件名
├─ pinpolicy    PIN 策略（长度、重试）
├─ blobs\auth   PIN 校验用的授权材料（KSP 加密）
├─ blobs\key-80 UserPIN（ref 0x80）对应的密钥材料（KSP 加密）
└─ fs\a000000397425446590401\{a000,a010…a014,b080,b081}\fcp|df1f|df20…
                卡的 ISO7816 文件系统（MF/DF/EF + fcp），PKCS#15 对象
                （证书位于 a010\df24；私钥对象只有元数据，key ref 0x81）
```

### 2.3 「设备实例 ↔ store 目录」的绑定（本次最大的发现）

实测 `ROOT\SMARTCARDREADER\<实例>` 的设备属性里有一条：

```
{2065F23D-D989-4F8F-B769-4A3D779FAF0B} 2 = C:\WINDOWS\ServiceProfiles\LocalService\AppData\
                                            Local\Microsoft\Windows\SmartCard\Tpm\<GUID>\
{2065F23D-D989-4F8F-B769-4A3D779FAF0B} 3 = C:\WINDOWS\System32\tpmvsc.dll
```

- 它存在 `Enum\...\<实例>\Properties` 子键里，该子键 ACL 受保护：**连管理员的 `reg export` 都读不到**，所以按旧实现的注册表备份里**没有这一条** ⇒ 还原后设备节点即使被创建，驱动也不知道去哪个 store，卡片自然起不来。
- 读得到吗？读得到：PnP 属性接口 `CM_Get_DevNode_PropertyW` 不受该 ACL 限制（已验证）；写回用 `CM_Set_DevNode_PropertyW`（需要管理员）。
- 注意：`Properties` 子键的缺失与否，也可能影响 PnP 是否愿意在运行期创建该设备节点（0001 就是"有 Enum 注册表项、没有设备节点"的状态）。

### 2.4 本机实测映射（时间戳 + 属性双证据）

| 实例 | store GUID | 设备 InstallDate | 依据 |
|---|---|---|---|
| 0000 | `ddf8e0c5-…` | 2026-10-05 23:27:23 | 设备属性 + 该 GUID 目录文件 mtime 一致 |
| 0001 | `cbcbb75c-…` | —（无设备） | 排除法；只剩 Enum 注册表项，`Properties` 缺失 |
| 0002 | `ccc06b19-…` | 2026-10-14 00:28:53 | 设备属性 + 该 GUID 目录文件 mtime 一致 |

`0002` 的 `LastRemovalDate` 为空、`FirstInstallDate` = 建卡时刻 ⇒ 它的设备从未被移除，"签名成功"不能用来证明 A 场景。

---

## 3. 还原失败的根因链（按修复顺序）

1. **写不进去**（`[Errno 13] Permission denied: …\keymaps`）
   store 位于 LocalService 配置文件下，部分条目 ACL 只授予 SYSTEM，即使管理员也写不进；只读属性、同名目录占位同样会报 errno 13。
   → 写入助手改为「清只读属性 → 清理占位条目 → `takeown`+`icacls` 修复 ACL → 重试」。
2. **服务占用**：写文件前先 `sc stop SCardSvr`，写完再启动（`finally` 保证）。
3. **设备节点不在 PnP 内存树里**：`reg import` 只写磁盘；运行期必须重新枚举（等价设备管理器「扫描检测硬件改动」= `CM_Reenumerate_DevNode`），并对已存在的节点也强制重新枚举一次（让驱动重新加载）。
4. **设备 ↔ store 绑定缺失**（见 2.3）：还原后检查该属性，为空时用备份里的 `store.guid` 写回并重新枚举。
5. **读卡器列表来自 PnP 设备，不是 `Calais\Readers` 注册表**（实测：Calais 里 0/1/2 三条都在，但只有设备存在的 0/2 被列出）⇒ 只重启 SCardSvr 不可能让卡片出现。

---

## 4. 代码改动清单

### 4.1 `Module/TPMBackup.py`

- **备份包改为 `.tsb`（zip）单文件**
  - `BACKUP_SUFFIX`、`_backup_path()`、`_discard()`；`create_backup(dest_path, name, uid)` 边读边打包，先写 `<目标>.part` 再 `os.replace`，失败不留半成品。
  - 包内结构：`tpmvsc-backup.json`（清单）、`store-index.txt`、`files/<Tpm 相对结构>`、`registry/*.reg`。
  - `_PackageReader` 只接受 `.tsb`；`read_manifest(package, reader)` 复用已打开的包；`_collect_files(prefix)`、`_file_entry()` 支持包内前缀。
  - 还原端从压缩包读数据（`hashlib` 校验 sha256），注册表先落临时文件再 `reg import`。
- **单卡备份（按 GUID）**
  - `device_store_path(uid)`：读设备属性里的 store 路径（`CM_Get_DevNode_PropertyW`）。
  - `card_store_guid(uid)`：取 store 目录名（GUID）。
  - `locate_card_entries()`：优先按 GUID 精确匹配，其次才退回"名称/实例"模糊匹配 ⇒ 备份只含选中卡，不再整目录覆盖其它卡。
  - 清单新增 `store.guid`，备份日志打印 `卡片 store 目录: <GUID>`。
- **还原健壮性**
  - `_clear_readonly()` / `_remove_entry()` / `_take_control()` / `_write_data()`（写入前停服务、ACL 修复、占位清理、重试）。
  - `_service(action)`、`_rescan_devices(uid)`（根节点重新枚举 + 该节点强制重新枚举 + 状态判定）、`_reader_state(uid)`（用 OpenSC 判断读卡器/卡片是否出现）。
- **TPM 与私钥自检**
  - `tpm_identity()`：`Get-TpmEndorsementKeyInfo -HashAlgorithm Sha256` → EK 公钥 SHA-256 + 厂商证书信息，写入清单 `tpm`。
  - `check_tpm(manifest)` → `match / mismatch / unknown`；`restore_backup(package, force=False)` 在不一致且未强制时**先中止、不做任何系统改动**，界面确认后可强制还原。
  - `tpm_key_state(guid)`：打开 TPM 内以 GUID 命名的 KSP 持久密钥 → `exists / missing / unknown`，写进还原日志与报告（`key_state`）。
  - `set_device_store_path(uid, store_path)`：写回设备属性，修复"设备→store"绑定。
- **文档字符串**：补充 `.tsb` 格式、设备重新枚举机制。

### 4.2 `SmartCardAPP.py`

- 备份：`asksaveasfilename`（默认 `卡片名-实例.tsb`），弹窗显示备份**文件路径**。
- 还原：`askopenfilename` 只选 `.tsb`；`card_restore(package=None)` 支持外部传入路径；还原前调用 `check_tpm`，不一致时用新词条 `msg_rec_tpm_diff` 警告，确认后 `force=True`。
- 双击 `.tsb`：`open_backup()`（启动参数）延迟 300 ms 进入还原流程；配合文件类型关联的 `open` 命令。
- 删卡确认框追加 `delete_card_backup`（提示备份不含 TPM 内的密钥）。

### 4.3 多语言（11 个语言包）

- 新增：`delete_card_backup`、`msg_dlg_tsb_files`、`msg_rec_tpm_diff`。
- 修改：`msg_bak_ok`（改为"备份文件 + 明确说明只含卡片数据与设备注册表、不含 TPM 内密钥；删除卡片/换机/清 TPM 后可能无法还原"）、`msg_bak_dir` / `msg_rec_dir`（改为保存/选择 `.tsb`）。
- `python -m Module.I18n --check`：11 种语言 **265 词条全部一致**。

### 4.4 `Config/tsb.reg` + `install.iss`

- 新增 `.tsb` 文件类型注册（与安装路径无关部分）：`HKCR\.tsb` → ProgID `TPMSmartCard.Backup`、Content Type、PerceivedType。
- `install.iss`：`[Registry]` 写入图标与 `shell\open\command`（`"{app}\SmartCardAPP.exe" "%1"`）、`[Run]` 用 `reg import` 合并 `Config\tsb.reg`、`[Setup]` 加 `ChangesAssociations=yes`、`[UninstallRun]` 卸载时清理关联。

### 4.5 `Builds/Test-VscStoreLoss.ps1`（新增，可逆实测脚本）

- B 场景：新建一份 `.tsb` → 停服务、把 `Tpm` 改名（模拟文件丢失）→ 起服务确认卡片消失 → 调工具还原 → 校验读卡器/卡片/PIN/真实签名。
- `-SimulateOsReinstall`：额外移除该卡的设备节点、Enum 注册表项、Calais 读卡器项（模拟系统重装），并在移除后再查一次 `tpm_key_state`，用于判断"移除设备是否连带删掉 TPM 密钥"。
- 全程只改名不删数据，失败可按脚本提示回滚。

---

## 5. 备份文件格式（`.tsb`）

```
tpmvsc-backup.json     清单：卡片信息、文件 sha256、注册表项、TPM 指纹、store.guid、注意事项
store-index.txt        备份时的数据目录清单（诊断用）
files/<Tpm 内相对结构>  卡片数据文件（单卡时只含该卡 GUID 目录）
registry/<SMARTCARDREADER-xxxx>.reg
registry/<CalaisReader-xxxx>.reg
```

`.tsb` 就是 zip，改后缀为 `.zip` 即可查看内容。

---

## 6. 本次验证记录（可复现）

| 项目 | 结果 |
|---|---|
| 旧备份包完整性 | 63 个数据文件 sha256 **全部通过**；清单 `computer` 与本机一致 |
| 在用的两张卡私钥可用性 | `pkcs15-tool --verify-pin` 通过 + `pkcs15-crypt --sign --sha-256 --pkcs1` 产出 **256 字节 RSA 签名**（两张都成功） |
| store GUID 读取（新代码，非管理员） | 0000 → `ddf8e0c5-…`、0002 → `ccc06b19-…`、0001 → 空（无设备节点） |
| `tpm_key_state`（非管理员） | 返回 `unknown` 并说明 `Access denied`，**不会误报 missing** |
| `set_device_store_path`（非管理员） | 返回 `code=51`（权限不足）且未破坏原值 ⇒ 调用形态正确 |
| 语法/语言包 | `py_compile` 通过；`Module.I18n --check` 11×265 一致 |

**未验证**：需要管理员的端到端还原（本机沙箱提权不可用：探针进程 exit=1、无输出文件），C 的真机重装，A 的最终判定。

---

## 7. 判定命令（管理员 PowerShell）

```powershell
# 私钥是否还能用（需要 PIN）
.\OpenSC\pkcs15-tool.exe  --reader <N> --verify-pin --pin <PIN>
[IO.File]::WriteAllBytes("data.bin", (1..32))
.\OpenSC\pkcs15-crypt.exe --reader <N> --sign --sha-256 --pkcs1 --input data.bin --output sig.bin --pin <PIN>

# B / C 实测（可逆）
.\Builds\Test-VscStoreLoss.ps1 -Instance 0002 -Pin <PIN>
.\Builds\Test-VscStoreLoss.ps1 -Instance <测试卡实例> -Pin <PIN> -SimulateOsReinstall

# A 的最终判定：TPM 里以 GUID 命名的机器级持久密钥是否还在、能否导出
certutil -csp "Microsoft Platform Crypto Provider" -key
$p = New-Object System.Security.Cryptography.CngProvider("Microsoft Platform Crypto Provider")
foreach ($n in @("<卡片 GUID>")) {
  try { $k=[System.Security.Cryptography.CngKey]::Open($n,$p,[System.Security.Cryptography.CngKeyOpenOptions]::MachineKey)
        "$n ExportPolicy=$($k.ExportPolicy)"; $k.Dispose() } catch { "$n -> $($_.Exception.Message)" }
}
```

---

## 8. 未决事项 / 下一步

1. **`Properties` 子键纳入备份**：目前靠 `store.guid` + `set_device_store_path` 运行时写回；若要在"设备节点尚未创建"时也能恢复绑定，需要在导出/导入前对该子键取得所有权（.NET 注册表 ACL）。
2. **C 场景真机验证**：重装 → 还原 →（可能需要）重启 → 再执行一次还原完成绑定。
3. **A 的最终判定**：`certutil -key` + `CngKey.ExportPolicy`；若可导出，才有"备份 TPM 密钥以支持 A"的可能。
   附：TPM 密钥的**作用域与命名**待确认（机器作用域按 store GUID 打不开）——可用管理员执行
   `certutil -csp "Microsoft Platform Crypto Provider" -key`，并查看 `C:\Windows\ServiceProfiles\LocalService\AppData\...\Microsoft\Crypto`
   是否有对应密钥元数据（若是"用户作用域 + OS 侧元数据"，则"系统重装（C）"还需要这部分元数据，
   会影响 C 的最终结论）。软件侧因此不对私钥是否存在做负面断言，只给"存在"或"无法判定"。
4. `list_cards()` 目前会把"只有注册表残留、没有设备"的实例当成正常卡列出，建议标注"设备缺失/不可用"。
5. 界面上展示三项自检结论（TPM 是否一致 / 私钥是否还在 / 设备是否已绑定），需要新增词条（11 语言同步）。
6. 运行期创建 ROOT 枚举设备在部分环境可能失败，此时需重启系统后再执行一次还原（工具已在日志中提示）。

---

## 9. 风险与限制

- 备份是「TPM 密文 + 设备注册表」的快照，**不是密钥备份**；对 BitLocker/EFS 这类依赖卡上私钥的数据，恢复方案必须是数据层的恢复密钥（BitLocker 恢复密钥、EFS DRA），不是卡。
- 同一台机器 + 同一颗 TPM（未清除）是硬前提；清除 TPM / 更换 TPM / 更换主板后，`.tsb` 无法救回私钥。
- 文档中卡片 GUID、主机名等已按前缀省略，完整值可从本地备份清单获得，请勿随仓库外发。

---

## 10. 2026-10-15 补充：用户实测「系统 A 备份 → 系统 B 还原，卡片没出现」

现场：系统 A 备份智能卡 → **未清除 TPM** 时切到系统 B（换系统，同机同 TPM）→ 还原 → 卡片没出现在列表里。
原实现的盲区是**失败了也看不出来**：`restore_backup` 全程只 `print` 日志，界面只弹一句
「还原完成，数据文件 N 个」，用户与开发者都拿不到「卡在哪一步」的信息。

### 10.1 本次修复

1. **`CM_Set_DevNode_PropertyW` 写入长度补上字符串结尾 NUL**（`Module/TPMBackup.py`）。
   写 `DEVPROP_TYPE_STRING` 时缓冲区长度必须含结尾 NUL（少 2 字节会被判 `CR_INVALID_DATA(0x1F)`；
   即使侥幸写入，没有终止符的路径也会被驱动读成乱码）。原实现传的是 `len(encoded)`，
   而 `set_device_store_path` 的失败分支**统一**报「设备节点还不存在」——把"属性写入被系统拒绝"
   误报成"节点不存在"，是误导性最强的一处。现改为返回 `(ok, text)` 并**回读校验**。
2. **不再"有绑定就跳过"**：新增 `_binding_ok(bound, guid)`，绑定目录不存在、或绑的是**别的**
   GUID（换系统后注册表里残留旧路径，例如指向另一个系统盘）时按备份写回。
3. **重新枚举加强**：`_rescan_devices` 改为「多次 `CM_Reenumerate_DevNode(根)` + 首次失败时
   `pnputil /scan-devices` 兜底 + 每次复核节点是否真的出现」。`reg import` 返回成功**不等于**
   设备已存在，这一点原先只靠 `CM_Locate_DevNode` 的返回值顺手判断。
4. **可观测性**：新增 `devnode_state()`（`missing/started/present/problem`）、`reader_state()`
   （`card/reader_only/absent/unknown`）、`_restore_verdict()`、`_diagnostics()`；还原日志
   「结论 + 逐条日志 + 现场诊断」整体返回给界面，并落盘到
   `%APPDATA%\TPMSmartCard\logs\restore-<stamp>.log`（备份同理写 `backup-*.log`）。
   界面弹窗直接展示结论与日志路径。

### 10.2 结论：还原要成功需同时满足四件事

| # | 条件 | 判据 / 失败表现 |
|---|---|---|
| 1 | 注册表写进去了 | 日志 `已导入注册表` / `导入注册表失败` |
| 2 | PnP 真的建出了设备节点 | `devnode_state == missing` ⇒ 读卡器根本不会出现 |
| 3 | 「设备 → store 目录」绑定写回 | `reader_only`（Card=No）⇒ 驱动不知道卡片数据在哪 |
| 4 | 卡片数据与 TPM 密钥匹配 | 绑定正常仍 `Card=No` ⇒ 换机/清过 TPM，私钥不可恢复 |

**注意**：`§1` 表里「C 场景 ✅ 支持」是**设计预期**，当时未做管理员端到端验证（见 §6）。
第 2 条是当前最需要现场日志确认的环节——`reg import` 只写磁盘，设备节点要靠 PnP 重新枚举；
若实测发现**重启后设备节点仍不会创建**，就说明 `Enum\ROOT\SMARTCARDREADER\<uid>` 的 ROOT
设备不能只靠注册表恢复，届时的候选方案（按代价排序）：

- 把 `Enum\...\<uid>\Properties` 子键纳入备份（取得所有权后导出/导入，见 §8.1），
  让设备一被创建就自带 store 绑定；
- 用 SetupDi 在运行期注册设备（`SetupDiCreateDeviceInfo` + `DIF_REGISTERDEVICE`，
  即 `devcon install` 的做法），彻底去掉对重启的依赖。

两者都属未实测的高风险改动，等拿到现场日志再定。

---

## 11. 2026-10-15 实机定位：换系统还原为什么一定失败

拿到现场机器（VMware 虚拟机 Win10 19044，vTPM 2.0 已就绪；卡片在系统 A 备份、切到系统 B
还原）。通过 SSH + 在**交互会话**里跑探针逐项验证，结论如下。

### 11.1 第一个坑（已修）：设备节点根本没被创建

- 现场状态：`Enum\ROOT\SMARTCARDREADER\0000` **在**（`ConfigFlags=0`、`HardwareID`、
  `Service=WUDFRd`、`Device Parameters\WUDF\DriverList=SmartcardSimulator` 都在，
  只缺受 ACL 保护的 `Properties` 子键）；`Tpm\<GUID>` 数据文件**也都写回去了**
  （卡片 store 完好，21 个文件）。
- 但 `pnputil /enum-devices /class SmartCardReader` **找不到任何设备**：
  **PnP 从来没有创建这个设备节点**。
- **决定性实验**：在机器上跑 `pnputil /scan-devices`（"扫描检测硬件改动"）后，
  设备**依旧不存在**。⇒ `reg import` + 重新枚举**不可能**恢复 ROOT 设备。
  §8.6 里"重启系统后再执行一次还原"这条猜测也不成立（连扫描都不建，重启更没有理由建）。

### 11.2 已实现并实测可行的修复：用 SetupDi 注册设备

`devcon install` 用的那套才是创建 ROOT 设备的正规做法，实测有效：

1. 删掉没有设备节点的"孤儿" Enum 项（先 `reg export` 留底）；
2. `SetupDiCreateDeviceInfo("ROOT\SMARTCARDREADER\<uid>")`（显式实例号，保证读卡器名
   `Microsoft Virtual Smart Card <n>` 与备份一致）；
3. `SetupDiSetDeviceRegistryProperty(HardwareID=VirtualSmartcardReader\reader)`；
4. `SetupDiCallClassInstaller(DIF_REGISTERDEVICE)`；
5. `UpdateDriverForPlugAndPlayDevices(%SystemRoot%\inf\tpmvsc.inf, INSTALLFLAG_FORCE)`。

现场结果：设备节点建成、`Status=OK / Problem=CM_PROB_NONE`、WUDF 宿主加载
（`WUDFHost.exe` PID 与 `WUDFDiagnosticInfo\HostPid` 一致）、
`Driver`、`Device Parameters\WUDF\DriverList`、`Properties` 等键由 INF 自动生成，
随后 `CM_Set_DevNode_Property(store)` 返回 **CONFIGRET=0**（这条也顺带验证了
`DEVPROP_TYPE_STRING` 必须把结尾 NUL 计入长度）。

注意：`SetupDi` 的 `SPDRP_FRIENDLYNAME` 不生成老式 `FriendlyName` REG_SZ，
所以代码里额外 `reg add ... /v FriendlyName` 补一份（界面读的是这个值）。

### 11.3 第二个坑（本次新发现，尚未验证修复）：TPM 密钥索引不在备份范围里

设备建好之后，读卡器**仍然没有出现在 PC/SC**：交互会话里 `SCardListReaders` 返回
`0x8010002E (SCARD_E_NO_READERS_AVAILABLE)`（两个作用域都一样），而
`Calais\Readers\Microsoft Virtual Smart Card 0` 的 `Device`/`Groups` 值被**系统自己清空**
——说明那串注册表是**派生状态**，不是配置，光 `reg import` 回来没有意义。

根因在于卡片的 TPM 密钥索引：

- `Tpm\<GUID>\keymaps` 的十六进制里能看到 KSP 密钥名是固定字符串 **`TPMVSC`**
  （`54 00 50 00 4D 00 56 00 53 00 43 00`），私钥材料是 KSP 加密后放在 `blobs\*`。
- 「KSP 密钥名 → TPM 持久对象」的映射（`*.PCPKEY`）存在**操作系统侧**：
  `C:\ProgramData\Microsoft\Crypto\PCPKSP\<id>\`、`C:\Windows\System32\config\systemprofile\
  AppData\Local\Microsoft\Crypto\PCPKSP\<id>\`、以及账号 profile 下（LocalService）。
  实测：新建一个机器作用域 PCP 密钥，就会在 `ProgramData\...\PCPKSP\<id>\` 多出一个
  `.PCPKEY`。
- 现场：`%SystemRoot%\ServiceProfiles\LocalService\...\Crypto\PCPKSP` **目录根本不存在**，
  `certutil -key -csp "Microsoft Platform Crypto Provider"` 也只列出本机自己的密钥。
  ⇒ 系统 B 上没有这张卡的密钥索引，驱动打不开卡片密钥，卡片起不来，读卡器不被发布。

**结论**：`store + 注册表` 的备份范围**不足以**支撑"换系统 / 重装（TPM 未清除）"场景，
必须把 TPM 密钥索引一起备份（§8.1 只提到了 `Properties` 子键，漏了这一块）。
本次已把 `PCPKSP` 候选目录纳入备份 / 还原（`VSC_PCP_DIRS` / `PCP_DIR`，
还原时同名文件不覆盖），**但"索引文件跨系统安装是否可移植"尚未验证** ——
需要按新代码在系统 A 重新备份一次再还原才能确认。
若验证通过，则 §1 表的 C 场景结论成立的前提是"备份里必须含 TPM 密钥索引"。

### 11.4 顺带记录的现场事实

- `tpmvscmgr create` 在 SSH 会话里报 `0x80070005 拒绝访问`（非控制台会话限制）；
  但**同一会话里机器作用域 PCP 密钥可以创建成功** ⇒ TPM 本身在系统 B 上完全可用
  （`Get-Tpm`: `TpmReady/TpmOwned=True`、`ManagedAuthLevel=Full`），
  所以这一条**不是** TPM 障碍。
- SSH 的 session 0 里 `SCardListReaders` 返回 `ERROR_ACCESS_DENIED(5)`，
  读卡器枚举必须在交互会话里查（用计划任务 `/it` 跑探针）。
- 现场机器上辅助测试留下的东西：计划任务 `ScProbe`（已禁用）、
  `C:\Windows\Temp\scprobe.ps1|scprobe.txt`（可删）。
