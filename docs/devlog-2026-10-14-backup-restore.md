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
