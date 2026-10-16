# 工作原理

这一页说明三件事：**Windows 的虚拟智能卡是怎么构成的**、**本工具做了哪些动作**、
以及**为什么卡上私钥无法被复制**。理解这些之后，[备份与还原](/guide/backup) 里那些
"看起来成功但卡片不出现"的现象就有了解释。

## 1. 虚拟智能卡是 Windows 自带的能力

Windows 8 起自带 TPM 虚拟智能卡（TPM Virtual Smart Card），它的实现链条是：

```
       应用（浏览器 / SSH / 签名工具）
                │  标准 Crypto API / CNG / PKCS#11
                ▼
   ┌──────────────────────────────────────────┐
   │ tpmvsc.dll（智能卡 minidriver）           │   ← 把"卡"翻译成 CSP/CryptoAPI 调用
   └──────────────────┬───────────────────────┘
                      │  PC/SC（WinSCard）
                      ▼
   ┌──────────────────────────────────────────┐
   │ 虚拟读卡器 + 模拟器驱动                   │   ← 枚举成 "Microsoft Virtual Smart Card 0"
   └──────────────────┬───────────────────────┘
                      │  卡片文件系统 / 密钥与 PIN 映射（DPAPI 保护）
                      ▼
   ┌──────────────────────────────────────────┐
   │ TPM（1.2 / 2.0）                          │   ← 私钥在这里生成、在这里签名
   └──────────────────────────────────────────┘
```

* 卡片由系统命令 **`tpmvscmgr.exe create`** 创建，创建后系统里会出现一个 **PC/SC 读卡器**，
  名字形如 `Microsoft Virtual Smart Card 0`；
* 卡内文件系统、密钥映射（`keymaps`）、PIN 映射（`pinmaps`）、PIN 策略（`pinpolicy`）以文件形式
  落在系统目录里，并由 **DPAPI** 加密（见 §3）；
* 卡上私钥是 **TPM 内部的持久对象**，只暴露"用某把密钥签名 / 解密"的能力，不提供导出接口。

## 2. 一张可用的卡由**五个部分**共同构成

这是本项目最核心的一条认识 —— 缺任何一项，表现都是"卡在、但系统不认"或"证书不显示"：

```
       ┌─────────────────────────────┐
       │ ① PnP 设备节点               │  Enum\ROOT\SMARTCARDREADER\<实例>
       │   （tpmvsc.dll + 模拟器驱动）│
       └──────────────┬──────────────┘
                      │ ④ 设备属性（ACL 保护）
                      │    {2065F23D-…},2 = store 路径
                      │    {2BEED4A8-…}   = 卡片名 / 驱动信息 ← 决定读卡器是否发布
                      ▼
       ┌─────────────────────────────┐        ┌──────────────────────────┐
       │ ② 卡片数据目录 store         │◀──────▶│ ③ TPM 密钥索引 *.PCPKEY   │
       │   keymaps / pinmaps /        │        │   「KSP 密钥名 → TPM 对象」│
       │   pinpolicy / blobs / fs     │        │   在 3 个候选目录下        │
       └──────────────┬──────────────┘        └──────────────────────────┘
                      │ ⑤ keymaps 等 5 个文件 = DPAPI blob（用户作用域，"TPMVSC"）
                      ▼
       ┌─────────────────────────────┐
       │ 源机 DPAPI 主密钥             │  ← 换机后不存在，必须"解密→重新加密"
       └─────────────────────────────┘
```

| # | 部分 | 位置 | 缺失后果 |
|---|---|---|---|
| ① | PnP 设备节点 | `HKLM\SYSTEM\CurrentControlSet\Enum\ROOT\SMARTCARDREADER\<实例>` | 设备节点建不出来，读卡器不出现 |
| ② | 卡片数据目录（store） | `%SystemRoot%\ServiceProfiles\LocalService\AppData\Local\Microsoft\Windows\SmartCard\Tpm\<store GUID>\` | 卡片没有内容 |
| ③ | TPM 密钥索引 | `…\Microsoft\Crypto\PCPKSP\` 下的 `*.PCPKEY`（3 个候选目录） | 驱动找不到卡上密钥 |
| ④ | 设备属性 | `Enum\…\<实例>\Properties`（**ACL 保护**，注册表导出拿不到） | 读卡器不会发布到 PC/SC |
| ⑤ | DPAPI 主密钥 | 源机 `…\Microsoft\Protect\<SID>[\User]\` | 证书与私钥不显示 |

依赖顺序决定了还原顺序：**④ 决定读卡器是否发布 → ② 提供卡内数据 → ③ 让驱动找到卡上密钥 →
⑤ 决定密钥容器能否建起来（证书才会出现）**。

## 3. 为什么换机器就解不开

`keymaps` / `pinmaps` / `pinpolicy` / `blobs\auth` / `blobs\key-80` 这几份数据是**用户作用域的
DPAPI blob**，其主密钥保存在**源机**该账户的 DPAPI 存储里，由 TPM 保护。把文件原样拷到另一台机器后：

* 驱动解不开这些数据 → 建不出密钥容器 → `certutil -scinfo` 报「找不到储存的密钥集」→ **证书不显示**；
* 私钥本身仍留在源机 TPM 里，**从来没有离开过那台机器的 TPM**。

所以本工具的备份策略是「**备份时在源机解密成明文 → 还原时在目标机重新加密**」，而不是搬运主密钥：
搬主密钥会连带解密同账户的其它受保护数据，暴露面不可接受（设计依据见
[备份还原设计](/design-backup-restore) 的 ADR-1）。

## 4. 工具到底做了哪些动作

界面上的每个按钮，最终都落到一条有据可查的系统命令：

| 界面动作 | 实际执行 | 说明 |
|---|---|---|
| 创建智能卡 | `tpmvscmgr create /name <标签> /AdminKey PROMPT\|RANDOM [/PUK PROMPT] /PIN PROMPT /generate` | 需要管理员；**不能在远程会话执行** |
| 删除智能卡 | `tpmvscmgr destroy` | 会一并清除该卡在 TPM 内的持久密钥 |
| 修改 PIN | `OpenSC\pkcs15-tool.exe --reader <卡序号> --change-pin --pin <旧> --new-pin <新>` | 通过 OpenSC 走 PC/SC |
| 重置 PIN（忘记 PIN） | `OpenSC\pkcs15-tool.exe --reader <卡序号> --unblock-pin --puk <PUK> --new-pin <新>` | 需要 PUK |
| 读卡 / 读证书 | 默认 OpenSC（`opensc-tool` / `pkcs15-tool`），可回退 `certutil` | 必须在**交互会话**执行 |
| 导入 PFX（含私钥） | `certutil -csp "<CSP>" -p <密码> -importpfx <文件>` | 私钥交给卡上密钥容器，写证书到用户存储 |
| 导入 CER / P7B | `Import\TPMImport.exe -user -b <文件> <密码>`（.NET 工具） | 只导入证书；要求卡上已有对应密钥 |
| 生成 CSR | `certreq -new -f <inf> <csr>` | 先由界面生成 `.inf`（含算法、密钥用途等） |
| 导入 CA 签发的证书 | `certreq -accept -machine <文件>` | 把签发结果与卡上密钥配对 |
| 删除密钥 | `certutil -delkey -csp "Microsoft Base Smart Card Crypto Provider" "<密钥名>"` | 删除卡上密钥对象 |
| 检测 TPM 状态 | `powershell Get-TPM` | 展示制造商、版本、就绪状态等 |
| 备份 / 还原 | 自研 `Module/TPMBackup.py`：注册表导出 + `SetupDi` 注册设备节点 + PnP 属性读写 + DPAPI | 见 [备份与还原](/guide/backup) |

> 顺带解释两个"怪现象"：
> 1. **建卡要几分钟**：`tpmvscmgr` 在 TPM 内创建密钥并生成卡片文件系统，本身较慢，
>    工具会等最多 300 秒。
> 2. **证书导入后不立刻出现**：证书要经 `CertReq -Accept` / 证书传播写进用户证书存储，
>    个别场景需要注销或重启才会刷新（详见 [常见问题](/guide/faq)）。

## 5. 私钥为什么不能导出

* 密钥对由 TPM 生成，**私钥是 TPM 的持久对象**；CSP/CNG 只能请求"用它签名或解密"，
  没有导出接口（这也正是"导出证书"只能拿到公钥数据的原因）；
* PIN / PUK / 管理密钥的校验发生在卡（TPM）内部，重试次数上限也由 TPM 计数，无法通过重装软件绕过；
* 因此**卡上私钥不可备份、不可迁移**：删除卡片（`tpmvscmgr destroy`）会清除 TPM 内的持久密钥，
  之后连本机也无法再用同一份备份恢复 —— 这是使用中必须知道的硬约束。

## 6. 技术架构一览

| 维度 | 取值 |
|---|---|
| 语言 / 运行时 | Python **3.13**（x64 与 arm64 线）、**3.10**（x86 / 低版本系统线）、**3.14**（Nuitka 线） |
| 界面 | Tkinter + ttkbootstrap，界面**纯代码构建**，布局与文案由 `Config/*.json` 驱动 |
| 卡片操作 | `tpmvscmgr`（建卡 / 删卡 / 改 PIN）+ OpenSC（读卡与证书）+ 自研 PnP / SetupAPI 层 |
| 备份还原 | 自研 `.tsb`（zip）打包；`Module/DPAPI.py` 负责 DPAPI 加解密与令牌借用 |
| 云端下发接收端 | `SmartCardWEB.py`（Flask，默认 `0.0.0.0:1080`） |
| 打包 | 两条流水线：**cx_Freeze**（正式包，Inno Setup 出安装器）与 **Nuitka**（standalone 目录） |
| 多语言 | `Config/locales/*.json`，11 种语言 |

核心库在 `Module/` 中，界面与子程序都复用它：

| 分层 | 模块 | 职责 |
|---|---|---|
| 基础设施 | `Paths.py`、`Version.py`、`I18n.py`、`AppConfigure.py`、`Theme.py`、`TrayIcon.py` | 路径解析、版本单一来源、多语言、配置驱动布局、主题与托盘 |
| 智能卡与 TPM | `TPMSmartCard.py`、`SmartCardAPI.py`、`OpenSCDealer.py`、`CertutilDeal.py`、`Certificates.py`、`SmartCardObj.py` | `tpmvscmgr` 封装、读卡与证书读取门面、X.509 数据对象 |
| 备份与还原 | `TPMBackup.py`、`DPAPI.py` | `.tsb` 打包 / 还原、设备节点重建、DPAPI 加解密与令牌借用 |
| 云端下发 | `Cryptography.py` | 取件码规范化 + PBKDF2-SHA256 + AES-256-CBC |
| 系统集成 | `AutoStart.py` | 开机自启（登录触发计划任务 + 注册表兜底） |

## 7. 数据落在哪里

| 用途 | 路径 |
|---|---|
| 程序根目录 | 含 `Config` 子目录的那个目录（可用 `TPMSMART_HOME` 覆盖） |
| 用户设置 | `%APPDATA%\TPMSmartCard\settings.json` |
| 备份 / 还原日志 | `%APPDATA%\TPMSmartCard\logs\<backup\|restore>-<时间戳>.log` |
| `.tsb` 备份包 | 用户自选（默认名 `<卡片名>-<实例编号>.tsb`） |
| Web 端证书缓存 | `<程序根>\Caches\PullCerts.pkl` |
| 卡片数据（系统侧） | `%SystemRoot%\ServiceProfiles\LocalService\AppData\Local\Microsoft\Windows\SmartCard\Tpm\<store GUID>\` |

## 8. 工程上守住的两条纪律

1. **失败不得伪装成"没有"**：读不到数据必须报错或明确告警，不允许静默返回空值后当作正常继续
   （历史上因此出过"厂商卡片身份 0 项"的假警告、遍历时静默丢文件的问题）。
2. **诊断要能落地**：备份 / 还原必须同时给出「结论 + 逐条日志 + 现场诊断」并落盘，
   保证在 GUI 下也能看清失败在哪一步。

完整的分层、路径、版本与发布约定见 [架构说明](/architecture)。
