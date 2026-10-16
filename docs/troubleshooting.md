# 故障排查手册

> 按「症状 → 怎么判定 → 结论与处理」组织。判定命令都可直接复制。
> 原理与依赖关系见 [`design-backup-restore.md`](design-backup-restore.md) 与
> [`architecture.md`](architecture.md) §8。

## 0. 开始之前（三条通用前提）

1. **先拿日志**：`%APPDATA%\TPMSmartCard\logs\`，文件名 `backup-*.log` / `restore-*.log`。
   结论、逐条日志、现场诊断都在里面。
2. **确认是管理员**：注册设备节点、写 `ProgramData`、借 SYSTEM 令牌做 DPAPI 都要求管理员；
   工具清单已声明 `requireAdministrator`，若被降权运行会明确报错。
3. **读卡器 / 建卡 / 删卡相关的操作必须在交互会话（本地控制台）**：
   SSH、服务会话、RDP 会话里做这些事会被系统拒绝
   （`SCardListReaders` 返回 `ERROR_ACCESS_DENIED`，`tpmvscmgr` 返回 `0x800704d3` / `0x80070005`）。
   RDP 请用 `mstsc /admin` 或到本机控制台。

## 1. 症状速查

| 症状 | 最可能原因 | 处理 |
|---|---|---|
| 备份报 `OverflowError: int too long to convert` | 旧构建的 64 位句柄缺陷 | 升级到新版本 |
| 备份报 `name 'SYSTEM_QUERY_LIMITED' is not defined` | 旧构建的常量缺陷 | 升级 |
| 备份日志出现「已备份设备属性: N 项（其中厂商卡片身份 **0** 项）」+「警告: 没读到厂商卡片身份属性」 | 旧构建的 `fmtid` 比较缺陷（**假警告**，属性其实读到了） | 升级；新版本会显示真实项数（正常卡为 6 项） |
| 备份日志「DPAPI 解密失败 … err=-2146893813 / err=5」 | 令牌借用失败（旧构建只扫 pid 1..399） | 升级；仍失败请把该行连同日志发回 |
| 备份日志「警告: 读取设备属性失败」 | 设备属性读取异常（非"没有属性"） | 先确认卡片设备在设备管理器里正常，再把日志发回 |
| 换过机器 / 清除或更换过 TPM / 删除过卡片之后想还原 | **还原前提不满足**：备份只支持**同一颗 TPM**，且**卡片未被删除** | **无法还原**卡上私钥：`tpmvscmgr destroy` 会清除该卡在 TPM 内的持久密钥，换 TPM 后父密钥也不同。卡片与证书可以重建，但需要**重新建卡并重新签发证书**；TPM 指纹不一致时工具会弹框询问是否继续 |
| **还原后卡片没出现**（读卡器列表里没有这张卡） | 设备属性是"设备启动之后"才写入的，驱动需要重启才会发布读卡器 | **先重启设备（驱动）或重启系统**再看；仍不出现则按下一行的三层判定处理 |
| **还原后读卡器不出现**（`SCardListReaders` = `SCARD_E_NO_READERS_AVAILABLE`） | 设备节点没建 / 卡片身份属性缺失 / TPM 密钥索引缺失 | 见 §2 |
| **读卡器出现但卡片没加载**（无卡或卡不可用） | 设备→store 绑定没生效；或卡片数据与 TPM 密钥不匹配 | 见 §3 |
| **卡片在、证书不显示** | 卡上密钥/PIN 数据在本机解不开（DPAPI 层） | 见 §4 |
| 卡片名 / 卡片信息与另一张卡一模一样 | 本机残留了旧卡片身份，且用的是旧构建 | 升级后用新构建**再还原一次**（不一致会被覆盖） |
| 还原日志提示 TPM 指纹不一致 | 备份来自另一颗 TPM | **卡上私钥无法恢复**（父密钥在源机 TPM 内）：卡片与证书可以重建，但需要**重新签发证书** |
| 创建/删除卡片失败 `0x800704d3` / `0x80070005` | 在远程会话或非提权会话里执行 | 到本机控制台，或用 `mstsc /admin` |
| SSH 连接时提示 `post-quantum key exchange algorithm` 警告 | 该提示与卡片功能无关 | 可忽略；当前 Windows OpenSSH 9.5 不含后量子 KEX 算法，需换客户端/服务端版本才有 |

## 2. 「还原后读卡器不出现」怎么判

在**交互会话**（管理员 PowerShell）里依次执行：

```powershell
# ① 设备节点到底建出来没有
pnputil /enum-devices /class SmartCardReader
# 期望：能看到 "Microsoft Virtual Smart Card 0" 之类的条目
# 若为空 → 设备节点没被创建（只 reg import 是不够的，需要工具用 SetupDi 注册）

# ② 设备节点在 PnP 里的状态
reg query "HKLM\SYSTEM\CurrentControlSet\Enum\ROOT\SMARTCARDREADER"
# 列出 0000/0001…；再看子键里的 FriendlyName / Service

# ③ 读卡器有没有被发布到 PC/SC
sc query SCardSvr          # 智能卡服务是否在跑
reg query "HKLM\SOFTWARE\Microsoft\Cryptography\Calais\Readers"
# 若这里出现条目但 Device/Groups 为空，说明是派生状态、被系统清空过
```

| 判定结果 | 结论 | 处理 |
|---|---|---|
| ① 无设备节点 | 设备节点没建出来 | 用工具的还原功能重跑（会用 `SetupDi` 注册）；确认备份包里有 `registry/*.reg` |
| ① 有、③ 无读卡器 | 卡片身份属性缺失 | 确认备份包清单里 `device_properties` 含 `{2BEED4A8-…}` 组（新版本备份正常为 6 项）；用新版本重新备份 + 还原 |
| ①③ 都正常但仍无卡 | TPM 密钥索引缺失 | 确认清单里有 `pcp[]`；目录 `…\Crypto\PCPKSP\` 下是否有 `*.PCPKEY` |

> 设备属性存在 `Enum\…\Properties` 子键里，**ACL 保护，`reg export` 读不到**，
> 只能通过 PnP 属性接口读；因此"注册表导出"从来不带这些属性。

## 3. 「读卡器出现但卡片没加载」怎么判

```powershell
# 设备绑定的 store 目录是不是备份里的那一个
reg query "HKLM\SYSTEM\CurrentControlSet\Enum\ROOT\SMARTCARDREADER\0000\Device Parameters" /s
# 另外：store 目录下应有 keymaps/pinmaps/pinpolicy/blobs/fs
dir "$env:SystemRoot\ServiceProfiles\LocalService\AppData\Local\Microsoft\Windows\SmartCard\Tpm"
```

* 绑定还不生效 → **重启系统后再执行一次还原**（工具也会重试枚举与刷新服务）。
* 绑定正确但仍无卡 → 卡片数据与 TPM 密钥不匹配（备份来自别的卡/别的 TPM）。

## 4. 「卡片在、证书不显示」怎么判（最常见）

```powershell
# 必须在交互会话执行
certutil -scinfo -silent
```

| certutil 输出 | 含义 | 处理 |
|---|---|---|
| `找不到储存的密钥集` / `无法打开读卡器的 AT_KEYEXCHANGE 密钥` | 驱动建不出密钥容器：卡上密钥/PIN 数据（DPAPI 保护）在本机解不开 | 用**新版本**在**源机**重新备份（备份时会解密）、再到目标机还原（还原时会用本机 DPAPI 重新加密） |
| 能打开密钥、但没有证书 | 卡上确实没有证书 | 用证书导入功能导入 |
| 证书列出但链不完整（`CERT_E_CHAINING`） | 签发它的中级 CA 没装在目标机 | 导入对应 CA 证书 |

还原日志里对应的判定字段：

* `卡片上的 5 个 DPAPI 保护文件在本机均可解开` → 正常
* `卡片上有 N 个 DPAPI 保护的文件，其中 M 个在本机解不开` → 见上表；旧版工具做的备份一定会这样
* 结论里出现「卡上的密钥 / PIN 数据在本机解不开…请用新版工具在源系统重新备份」→ 同上

## 5. 需要把问题发给支持时，请附上

1. 日志文件全文：`%APPDATA%\TPMSmartCard\logs\backup-*.log` / `restore-*.log`；
2. 现场诊断（工具界面上的「诊断」区块，或日志尾部）；
3. `certutil -scinfo -silent` 的完整输出（**在交互会话里跑**）；
4. `pnputil /enum-devices /class SmartCardReader` 的输出；
5. 备份包清单里的 `computer` / `tool_version` / `tpm` / `dpapi` 项数与 `device_properties` 项数
   （可用压缩工具打开 `.tsb` 看 `tpmvsc-backup.json`，**注意包里含密钥材料明文，勿外传**）。

> ⚠️ 发送日志前请自行确认里面没有敏感信息；`.tsb` 等同于密钥材料，**不要**发给无关人员。
