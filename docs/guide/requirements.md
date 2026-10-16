# 硬件与软件要求

## 1. 一览表

| 项 | 要求 | 说明 |
|---|---|---|
| 操作系统 | **Windows 8 x86 / x64 或更高**；安装包要求 **Windows 8.1（6.3）及以上** | 安装器声明了 `MinVersion=6.3`，更早的系统请用绿色版 |
| 架构 | x86（32 位） / x64 / arm64 | 三个架构各自有安装包，见 [安装方式](/guide/install) |
| 硬件 | **TPM 1.2 / 2.0 或更高** | 需在 BIOS / UEFI 中启用；与 BitLocker 共用同一颗 TPM 不冲突 |
| 权限 | **管理员**（UAC 提权） | 注册设备节点、读写系统目录、借 SYSTEM 令牌做 DPAPI 都需要 |
| 会话类型 | **本地控制台（交互会话）** | 建卡 / 删卡 / 枚举读卡器在远程会话里会被系统拒绝 |
| 系统组件 | `tpmvscmgr.exe`、`certutil.exe`、`certreq.exe`、PowerShell | 系统自带（`tpmvscmgr` 只存在于真正的 `System32`，见下方提示） |
| 随包组件 | OpenSC 工具、WinCryptSSHAgent、`Import\TPMImport.exe`（.NET 证书导入工具） | 随安装包分发，无需另行安装 |
| 磁盘 | 安装包解压后约 **数百 MB** | 含 OpenSC 全套工具、SSH 代理与 VC++ 运行库 |
| 网络 | **除"云端下发证书"外全部离线可用** | 不需要账号，不需要联网激活 |
| 显示器 / 语言 | 图形界面（Tkinter） | 11 种界面语言可选 |

::: warning tpmvscmgr 必须在真正的 System32 里
`tpmvscmgr.exe` 在 `SysWOW64` 下不存在。32 位程序访问 `System32` 会被重定向到 `SysWOW64`，
本工具用 `Sysnative` 别名兜住（`Module/WinPlatform.py`）；如果你写脚本调用它，
同样需要注意 WOW64 文件系统重定向问题。
:::

## 2. 不支持 / 需要绕开的环境

| 环境 | 结论 |
|---|---|
| **远程桌面（普通 RDP 会话）** | 创建 / 删除卡片会被系统拒绝，报 `0x800704d3`；请到本机控制台，或用 `mstsc /admin` 连到控制台会话 |
| SSH / 服务 / 计划任务（非交互会话） | 枚举读卡器返回 `ERROR_ACCESS_DENIED`，建卡同样被拒；脚本化请用「只在用户登录时运行」的计划任务落到交互会话 |
| 未提权运行 | 建卡、写系统目录、DPAPI 令牌借用都会失败；程序清单已声明 `requireAdministrator` |
| Windows Server Core / 无桌面环境 | 没有图形界面，本工具无法运行 |
| 没有 TPM 的机器或 BIOS 中关闭了 TPM | 无法创建虚拟智能卡（这是硬件前提，不是软件配置问题） |

## 3. 环境自查（可直接复制执行）

在**管理员**的 PowerShell（本地控制台）里依次运行：

```powershell
# ① TPM 是否存在、是否就绪
Get-Tpm | Select-Object TpmPresent, TpmReady, TpmEnabled, TpmVersion, ManufacturerIdTxt

# ② 建卡所需工具是否就位
Test-Path "$env:SystemRoot\System32\tpmvscmgr.exe"
Test-Path "$env:SystemRoot\System32\certutil.exe"

# ③ 当前会话是不是远程会话（返回 RDP-* 说明是远程桌面会话，不能建卡）
$env:SESSIONNAME

# ④ 当前进程是否已提权（Enabled 那行含 S-1-16-12288 表示已是高完整性/管理员）
whoami /groups | Select-String "S-1-16-12288"
```

| 自查结果 | 结论 |
|---|---|
| `TpmPresent=False` | 机器没有 TPM 或 BIOS 里被禁用 → 去 BIOS / UEFI 打开 TPM（Intel PTT / AMD fTPM / 独立 TPM 模块） |
| `TpmReady=False` / `TpmEnabled=False` | TPM 未初始化或已关闭 → 用 `tpm.msc` 或「设置 → 安全和更新」初始化 |
| `TpmVersion` 为 `1.2` / `2.0` | 都受支持；TPM 2.0 更常见，功能更完整 |
| ② 任一为 `False` | 系统组件缺失（极少见），本工具无法替代，需要修复系统 |
| ③ 为 `RDP-*` | **不要**在此时创建 / 删除卡片，改用 `mstsc /admin` 或到本机操作 |

## 4. 与其它软件的关系

| 软件 | 关系 |
|---|---|
| OpenSC | **随程序分发**（程序目录 `OpenSC\`），读卡默认走它；安装包里的"系统级 OpenSC 组件"是**可选项**，只有其它软件（PKCS#11 客户端、物理卡 minidriver）需要时才装 |
| WinCryptSSHAgent | 随程序分发（`SSHCardAgent.exe`），只在 SSH 登录场景需要；也可用安装包组件或 `choco install wincrypt-sshagent` |
| BitLocker / Windows Hello / 其它 TPM 应用 | 可共存；虚拟智能卡只占用 TPM 的一部分能力 |
| 杀毒 / EDR | 程序会调用 `certutil`、`certreq`、`tpmvscmgr`、注册表与 PnP 接口，个别产品会拦截；如有拦截请加信任 |

下一步：[安装方式](/guide/install)。
