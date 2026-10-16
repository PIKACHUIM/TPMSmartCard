# TPM 虚拟智能卡「备份 / 还原」技术报告

| 项 | 内容 |
|---|---|
| 主题 | TPM 虚拟智能卡（TPM Virtual Smart Card）跨系统 / 跨机备份还原 |
| 状态 | **备份侧**已通过真机端到端验收；**还原侧**机制已实测成功，自动化路径待用发布构建复测一次 |
| 代码范围 | `Module/TPMBackup.py`、`Module/DPAPI.py`（新增）、`SmartCardAPP.py`、`Config/locales/*` |
| 原始过程记录 | `docs/devlog-2026-10-14-backup-restore.md`（含全部命令行证据与逐条对账） |

---

## 1. 摘要

TPM 虚拟智能卡由**五个部分**共同构成，卡片私钥能否使用**取决于其中任何一个都不能缺**：

| # | 组成部分 | 位置 | 说明 |
|---|---|---|---|
| ① | PnP 设备节点 | `HKLM\SYSTEM\CurrentControlSet\Enum\ROOT\SMARTCARDREADER\<实例>` | 由 `tpmvsc.dll` + `smartcardsimulator.dll`（UMDF）驱动 |
| ② | 卡片数据目录（store） | `…\ServiceProfiles\LocalService\AppData\Local\Microsoft\Windows\SmartCard\Tpm\<store GUID>\` | 实测 21～48 个文件 |
| ③ | TPM 密钥索引 | `…\Crypto\PCPKSP\*\*.PCPKEY`（3 个候选目录） | 「KSP 密钥名 → TPM 持久对象」的映射 |
| ④ | 设备属性（卡片身份） | `Enum\…\<实例>\Properties`（**ACL 保护**，`reg export` 读不到） | `{2065F23D-…}` / `{2BEED4A8-…}` 两组 |
| ⑤ | 卡片密钥与 PIN 映射 | store 内 `keymaps` / `pinmaps` / `pinpolicy` / `blobs\*` | **DPAPI 保护**（用户作用域，描述 `TPMVSC`） |

**旧版备份只覆盖 ②**，因此"换系统 / 换机还原"在多个层面必然失败。本工作把 ②③④⑤ 全部纳入
备份，并解决了跨机时的密钥重绑定问题：

> **备份时在源机用 DPAPI 解密成明文收进包，还原时用目标机 DPAPI 按同一账户与作用域重新加密写回。**

主要结论：

* **备份侧已收全**五部分，真机端到端验收通过：
  `files=48`、`pcp=27`（16/7/4）、`dpapi=5`、`props=60`（其中卡片身份 6 项）、TPM 指纹已记录。
* **还原侧机制已实测成功**：目标机上读卡器出现、证书可列出、`certutil` **公钥匹配测试成功**
  （即卡上私钥真的完成了一次密码学运算）。
* **待确认**：若目标机是**另一颗 TPM**（不是同一 vTPM 克隆），卡上私钥能否恢复**尚未验证**（§8.1）。

---

## 2. 背景与目标

* 场景：在原系统（记为 **A**）上有一张可正常使用的 TPM 虚拟智能卡；需要在另一系统（记为 **B**、
  或重装后的同一台机器）上把这张卡恢复出来继续用。
* 旧实现：把卡片数据目录（store）与设备注册表导出成 `.tsb`，还原时写回 + 重新枚举设备。
* 现象：还原后"看起来成功了"，但**卡片始终不出现**（PC/SC 里没有读卡器）；后期即使读卡器出现，
  **证书与私钥也不显示**。
* 目标：让备份包在目标机上能完整重建卡片 —— 读卡器出现、卡片可识别、证书可读、私钥可用。

---

## 3. 卡片构成与关键机制（实测结论）

### 3.1 store 目录布局

```
Tpm\<store GUID>\
├── keymaps       DPAPI blob（PIN / 密钥映射；描述 "TPMVSC"）
├── pinmaps       DPAPI blob
├── pinpolicy     DPAPI blob
├── blobs\auth    DPAPI blob（认证相关）
├── blobs\key-80  DPAPI blob（卡上密钥材料，0x80 = PIN 引用）
└── fs\...        卡内文件系统，**明文**
```

DPAPI blob 头解析（实测）：`dwVersion=1`、`guidProvider={DF9D8CD0-1501-11D1-8C7A-00C04FC297EB}`、
`dwFlags=0`（用户作用域）、`dwDescription="TPMVSC"`；`guidMasterKey` 指向**源机**该账户的
DPAPI 主密钥 —— 也就是说，**没有源机那把主密钥，换机后这些数据解不开**。

### 3.2 「设备 ↔ store」的绑定

由 `tpmvsc.dll` 写入设备属性 `{2065F23D-D989-4F8F-B769-4A3D779FAF0B},2`（store 目录路径）。
该属性存在 `Enum\…\Properties` 子键里，**连管理员 `reg export` 都读不到**，必须走 PnP 属性接口
（`SetupDiGetDevicePropertyW` / `CM_Get_DevNode_PropertyW`）。

### 3.3 两组厂商设备属性

| 属性集 | PID | 含义 | 实测是否每卡不同 |
|---|---|---|---|
| `{2065F23D-…}`（`tpmvsc.dll`） | 2 | **store 目录路径** | **是** |
| | 3 | `tpmvsc.dll` 路径 | 否 |
| `{2BEED4A8-…}`（`smartcardsimulator.dll`） | 2 | 驱动 dll 路径 | 否 |
| | 3 | **卡片名** | **是** |
| | 4 | `0xFF` 标志位 | 否 |
| | 5 | GUID 常量 `{7c624d56-…}` | **否**（4 张卡实测同值） |

> 属性集 GUID 本身是**驱动常量**（编译进 dll 的命名空间），所有机器 / 所有卡都一样 —— 这是设计使然。
> 真正"跟着卡走"的是 store 路径与卡片名。早期曾误认为 `,5` 是卡片唯一 ID 并据此找 TPM 密钥，
> 已由 4 张卡的实测数据推翻（详见 devlog §13.11）。

### 3.4 驱动发布读卡器、以及证书出现的条件

* 读卡器是否被发布到 PC/SC → 取决于设备上**是否存在** `{2BEED4A8-…}` 这组属性（实测：补齐后
  设备接口与读卡器立刻出现）。
* 证书是否能列出 → 取决于驱动能否**建出卡的密钥容器**；而这又要求 ⑤ 的 DPAPI 数据在**本机**
  能解开（否则 `certutil -scinfo` 报 `找不到储存的密钥集`）。

---

## 4. 根因与修复（五个断点）

| # | 断点 | 现象 / 证据 | 根因 | 修复 |
|---|---|---|---|---|
| 1 | 设备节点从未被创建 | `reg import` 写回了 `Enum\…\0000`，但 `pnputil /enum-devices` 里没有该设备；`pnputil /scan-devices` 也建不出来 | `reg import` 只写磁盘，PnP 内存设备树里没有节点；重枚举不会为 ROOT 设备建节点 | 改用 `SetupDi` 注册设备（`SetupDiCreateDeviceInfo` + `DIF_REGISTERDEVICE` + `UpdateDriverForPlugAndPlayDevices(tpmvsc.inf)`），重建前先导出并删除孤儿 Enum 项 |
| 2 | TPM 密钥索引缺失 | 设备节点已启动、store 已绑定，但 `SCardListReaders` 仍返回 `SCARD_E_NO_READERS_AVAILABLE` | `*.PCPKEY` 在操作系统侧（3 个候选目录），**既不在 store 也不在注册表备份范围** | 备份新增 `pcp/<i>/…`，还原时写回（同名文件不覆盖，避免破坏本机其它 TPM 密钥） |
| 3 | 卡片身份属性缺失 | 与系统 `tpmvscmgr` 创建的健康对照卡逐项对比：唯一差异是 `{2BEED4A8-…}` 整组属性缺失 | 该属性在 ACL 保护的 `Properties` 子键里，注册表导出带不回来；缺了它驱动**不建设备接口、不发布读卡器** | 备份经 SetupAPI 读取全部设备属性，还原时写回（卡片身份**不一致则覆盖**，其余只补缺失；属性里的绝对路径按备份机器的 `%SystemRoot%` 改写） |
| 4 | 卡片数据是 DPAPI 保护的 | `keymaps` 等 5 个文件是 DPAPI blob；目标机没有对应主密钥 → 驱动建不出密钥容器 → 证书不显示 | 备份只收密文，跨机后解不开 | **备份时在源机解密成明文收进包**（`dpapi/…`）；**还原时用目标机 DPAPI 按备份记录的账户与作用域重新加密**写回 |
| 5 | 代码缺陷族（见 §4.1） | 备份/还原过程中陆续暴露：`OverflowError`、`NameError`、解密 `err=5`、假警告… | 见下 | 逐条修复并对账 |
| 6 | 还原后**读卡器不出现**（设备节点却已 `started`） | 设备节点 `started`、设备属性写回成功、`Calais\Readers` 有项、DPAPI 全部可解，但 PC/SC 列表里没有读卡器；**重启系统后立刻正常** | 卡片身份属性与 store 绑定都是**在设备启动之后**才写入的，而 `smartcardsimulator.dll` 只在**设备启动时**读一次这些属性并据此注册 PC/SC 接口；仅 `CM_Reenumerate_DevNode`（＝「扫描检测硬件改动」）**不会重启设备栈**，驱动仍停在"启动时没有身份属性"的状态 | 写完属性后调用 `restart_device()` 做**真正的设备重启**（SetupAPI `DIF_PROPERTYCHANGE` + `DICS_PROPCHANGE`，即 `devcon restart` 同款；失败退化为 `pnputil /restart-device`），然后刷新服务并重新判定读卡器 |

> 断点 6 的现场证据（真机）：`0001` 与 `0002` 用同一版本连续还原，`0001` 因中途**重启过系统**而可见，
> `0002`（重启之后才还原）不可见；对 `0002` 执行一次 `pnputil /restart-device` 后，
> `Control\DeviceClasses\{50dd5230-…}` 下的接口实例立刻出现，`Calais\Readers` 的
> `Microsoft Virtual Smart Card 2` 也带上了非空的 `Device`/`Groups`。

### 4.1 断点 5 明细（这类问题的共同形态：**把"失败"伪装成"没有/正常"**）

| 缺陷 | 表现 | 修复 |
|---|---|---|
| 64 位句柄被当 32 位 `int` 传 | `OverflowError: int too long to convert`，备份直接失败 | 句柄统一包 `c_void_p`，并给相关 Win32 函数声明 `argtypes` |
| 未定义常量 | `name 'SYSTEM_QUERY_LIMITED' is not defined` | 改为 `PROCESS_QUERY_LIMITED_INFORMATION` |
| 令牌借用扫错进程 | 备份时以 SYSTEM 身份解密报 `ACCESS_DENIED(5)`（只扫 pid 1..399，而可用的服务进程 pid 都 > 400） | 用 `K32EnumProcesses` 取真实 pid，优先借 `services.exe` / `winlogon.exe` / `lsass.exe` 等，借到后**做一次 DPAPI 往返探针**确认可用 |
| `fmtid` 比较失效 | 设备属性里的 `fmtid` 是 ctypes 数组，被当字符串 → 厂商属性**永远匹配不上** → 误报「厂商卡片身份 0 项」并给出假警告 | `_fmtid_text()` 显式支持 ctypes 数组 |
| 「枚举失败」当「没有属性」 | 设备属性读取失败时返回空表，与"设备确实没有属性"无法区分 | 硬失败返回 `None`，备份日志明确报「读取设备属性失败…」 |
| `os.walk` 静默跳过无权限子目录 | 备份可能少文件但无人知晓 | 卡片数据目录遇到遍历失败**直接报错**；辅助目录允许缺但日志写明「少收 N 处」 |
| 误导性文案 | 5 个文件全部解密失败时却打印「卡片数据里没有 DPAPI 保护的内容」；TPM 指纹读失败说成「旧版备份」 | 文案改为按实际状态区分 |

---

## 5. 实现清单

| 文件 | 变更 | 说明 |
|---|---|---|
| `Module/DPAPI.py` | **新增** | DPAPI blob 识别（`blob_info` / `blob_description`）；令牌借用（`impersonate` / `revert`，遍历进程 → 比对 TokenUser SID → `DuplicateTokenEx` → `SetThreadToken`，并做 DPAPI 往返探针）；加解密（`protect` / `unprotect`，`unprotect` 按「blob 记录的 flags → 用户作用域 → 机器作用域」× 多账户依次尝试，`protect` 自带回验）；主密钥归属查询（`master_key_owner`） |
| `Module/TPMBackup.py` | 修改 | 备份收集 ①②③④⑤；还原按序重建（设备注册表 → SetupDi 注册节点 → store 文件与 DPAPI 重新加密 → PCP 索引 → 设备属性 → 重枚举 → 服务刷新）；新增 `dpapi_state()` 还原后读回自检；诊断与结论按层输出 |
| `SmartCardAPP.py` | 修改 | 备份 / 还原结果弹窗展示「结论 + 逐条日志 + 现场诊断」与日志文件路径（原先失败在 GUI 下完全不可见） |
| `Config/locales/*.json` | 修改 | 备份完成提示文案更新（不再声称"只含卡片数据与设备注册表"）；zh-Hans / zh-Hant / en 已同步，其余语言待同步 |
| `docs/report-backup-restore.md` | **新增** | 本报告 |
| `docs/devlog-2026-10-14-backup-restore.md` | 修改 | 原始过程记录（含全部证据、逐条对账与自我更正） |

---

## 6. 备份包格式（`.tsb`）

`.tsb` 是 zip 包：

| 路径 | 内容 |
|---|---|
| `files/<store GUID>/…` | ① 卡片数据目录（含 DPAPI 密文原始文件） |
| `pcp/<i>/…` | ③ TPM 密钥索引（`*.PCPKEY`） |
| `registry/*.reg` | ② 设备类与设备节点注册表导出 |
| `tpmvsc-backup.json` | 清单：`files` / `pcp` / `registry` / `dpapi` / `device_properties` / `system_root` / TPM 指纹 / `notes` |
| `dpapi/<store GUID>/…` | ⑤ **卡片密钥与 PIN 映射的明文**（还原时用目标机 DPAPI 重新加密） |
| `store-index.txt` | 目录清单（诊断用） |

> ⚠️ **安全提示**：因为含 ⑤ 的明文，`.tsb` 等同于卡上密钥材料，必须与 PIN / 管理密码同级保管。
> 这一提示同时写入清单 `notes` 与界面文案。

---

## 7. 验证记录

### 7.1 备份侧（真机端到端验收，2026-10-16）

```
已备份设备属性: 60 项（其中厂商卡片身份 6 项）
DPAPI 已解密: …/keymaps（已借用 SYSTEM 令牌（来自 services.exe），用户作用域，2856 字节）… ×5
已解密 5 个 DPAPI 保护文件；…
清单: files=48   pcp=[16,7,4]   dpapi=5   props=60   vendor props=6
  2065f23d…,2 = …\Tpm\<store GUID>\            （store 绑定）
  2beed4a8…,3 = Personal TPM Virtual Smart Card（卡片名）
  2beed4a8…,5 = {7c624d56-…}
```

### 7.2 还原侧（真机手工端到端，早期已完成）

目标机上 `certutil -scinfo -silent`（交互会话）：

```
--- 状态: SCARD_STATE_PRESENT
================ 证书 0 ================
密钥容器 = Pikachu Common Code Sign SHA256 V-…
序列号: 573924575402574d26116a71
证书哈希(sha1): bc08045f11e2856fbad27b70bea6169b54712bf6
正在执行 AT_KEYEXCHANGE 公钥匹配测试…
公钥匹配测试成功
```

即：读卡器出现、卡片可识别、证书可读、**私钥真的完成了一次密码学运算**。

### 7.3 单元 / 冒烟验证

| 对象 | 结果 |
|---|---|
| `Module/DPAPI.py` | 识别 / 加密 / 解密 / 回验 / 非 blob 处理 / 不可解 blob 的报错文案，均通过 |
| `Module/TPMBackup.py` | `_fmtid_text()` 对 str / bytes / ctypes 数组归一化一致；`_restore_verdict` 在 DPAPI 失败时不再报成功；编译无新增告警 |
| 语言包 | 11 个 JSON 均可解析 |

---

## 8. 已知边界与风险

1. **目标机是不同的 TPM（非同一 vTPM 克隆）时，卡上私钥能否恢复 —— 未验证。**
   验证环境里两台机器的 TPM 指纹一致（同一 vTPM 克隆）。卡的私钥是 TPM 内的持久对象，
   换一颗 TPM 后可能无法恢复；此时卡片与证书仍可重建，但私钥需要重新签发证书。
2. **还原侧尚未用发布构建在真机复测一次**（卡片身份纠正、DPAPI 重新加密的日志形态）。
3. **"读不到 store 绑定 → 退化为整目录备份"**这条降级路径未实测（会记日志，但可能把同机
   其它 store 一并打包）。
4. **`.tsb` 含密钥材料明文**（见 §6）。若需要，可再加一层：用 PIN / 管理口令派生的密钥加密整包。
5. 还原需要**管理员权限**（借 SYSTEM 令牌做 DPAPI、注册设备节点、写 `ProgramData`）。
6. `tpmvscmgr create/destroy` 在非控制台会话（如 SSH）会被系统拒绝（`0x80070005`），
   属于系统限制，不是本工具问题。

---

## 9. 验收步骤（可复现）

在**源机（管理员）**：

1. 打开工具 → 选择卡片 → 备份；查看日志应出现：
   * `已备份设备属性: N 项（其中厂商卡片身份 6 项）`
   * `已备份 TPM 密钥索引: 共 M 个文件（各目录 …）`
   * `已解密 5 个 DPAPI 保护文件（SYSTEM，用户作用域）…`
   * `已导出注册表: 2 项`
2. 若出现 `DPAPI 解密失败` / `读取设备属性失败`，把该行与日志文件一并反馈。

在**目标机（管理员）**：

3. 用同一个包还原；日志应出现：
   * `已还原卡片数据文件: N 个`、`已还原 TPM 密钥索引文件: M 个`
   * `已用本机 DPAPI 重新加密 5 个卡片数据文件`
   * `已写回设备属性: N 项（其中卡片身份被纠正 M 项…）`
   * `卡片上的 5 个 DPAPI 保护文件在本机均可解开`
4. 在**交互会话**（不能是 SSH 会话）执行 `certutil -scinfo -silent`，确认：
   * `状态: SCARD_STATE_PRESENT`、`此卡可用`
   * 能列出证书、`AT_KEYEXCHANGE` 密钥可打开、**公钥匹配测试成功**
5. 用 PIN 做一次签名验证，确认私钥实际可用。

---

## 10. 附录

### 10.1 术语

| 术语 | 说明 |
|---|---|
| VSC / TPM 虚拟智能卡 | 用 TPM 代替物理卡片、由软件模拟的智能卡（`tpmvscmgr` 创建） |
| store | 卡片数据目录，路径见 §1 表 ② |
| PCPKEY | TPM 密钥索引文件（Platform Crypto Provider），见 §1 表 ③ |
| 卡片身份属性 | 设备属性里 `{2BEED4A8-…}` 一组，见 §3.3 |
| `.tsb` | 本工具的备份包（zip），见 §6 |

### 10.2 原始记录索引

> `docs/devlog-2026-10-14-backup-restore.md` 是**早期**过程记录，现含 §1–§11，止于 2026-10-15 的
> 实机定位。§12 之后的内容（卡片身份属性缺失、DPAPI 断点、代码缺陷族、端到端验收）在精简时被
> 移除，其要点**已完整并入本报告**（§3.3、§4、§4.1、§7），故以本报告为准。

| 本报告章节 | devlog 对应小节（仍存在） | 内容 |
|---|---|---|
| §3 卡片构成 | §2.1–§2.4 | store 目录语义、「设备实例 ↔ store 目录」绑定 |
| §4 断点 1 / 2 | §3、§10.2、§11.1–§11.3 | 设备节点重建、TPM 密钥索引、「还原成功需同时满足四件事」 |
| §4 断点 3 | §10.1、§11.4 | 设备属性与驱动发布读卡器的关系 |
| §4 断点 4、§4.1 | —（原 §12 / §13，已随精简移除） | 详见本报告 §4、§4.1、§7 |
| §7 验证记录 | §6、§7 | 早期可复现验证记录与判定命令 |
| §8 边界与风险 | §8、§9 | 未决事项与风险与限制 |

若需要恢复被移除的 §12 / §13（含当初的失败与更正过程），可另行补充为独立文档。
