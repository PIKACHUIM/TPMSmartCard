# 安装方式

三种安装方式按需选择：**安装包**（大多数人的选择）、**绿色版 zip**（不想安装 / 便携）、
**源码运行**（开发与调试）。

## 方式一：安装包（推荐）

1. 打开 [Releases](https://github.com/PIKACHUIM/TPMSmartCard/releases)，按架构下载对应的安装包：
   `TPMSmartCard-win64-setup.exe`（x64）、x86 或 arm64 版本（文件名里带架构标识；正式版与
   滚动 beta 预发布都在同一页面）；
2. 双击运行 —— 安装器**需要管理员权限**（写入 `Program Files`、注册 `.tsb` 文件关联）；
   进程版本信息与产品名见下表；
3. 在向导里选择**安装位置、开始菜单组、附加任务**：

   | 项 | 默认 | 说明 |
   |---|---|---|
   | 安装目录 | `C:\Program Files\TPM Virtual Smart Card Manager` | 显示名为「TPM VSC管理」 |
   | 桌面快捷方式 | 勾选 | |
   | 开始菜单 | 始终创建（含卸载入口） | |
   | 组件：`OpenSC 智能卡中间件（推荐）` | **勾选** | 装系统级 OpenSC（`OpenSC-0.25.1_win64-Light.msi`），供其它软件使用 |
   | 组件：`SSH 密钥代理（WinCryptSSHAgent）` | 不勾选 | 只有 SSH 登录场景需要；勾选后可额外创建代理快捷方式 |
   | `Config\tsb.reg`（.tsb 文件关联） | 自动 | 双击备份包即可用本工具打开 |
   | Visual C++ 运行库 | 按需 | 缺失时安装器会自动静默安装 |

4. 安装完成后可勾选「运行 TPM VSC管理」；
5. 后续启动：**从开始菜单启动时选择"以管理员身份运行"**，或尽量保持程序清单的提权行为
   （程序自身已声明 `requireAdministrator`，正常双击即会弹 UAC）。

> 静默安装（批量部署）：Inno Setup 标准参数可用，例如
> `TPMSmartCard-win64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="D:\Tools\TPMSmartCard" /LOG="%TEMP%\tpmvsc-install.log"`。
> 组件选择请以 Inno Setup 官方参数（`/COMPONENTS`）与实际安装包为准。

### 安装器细节（便于排查）

* 压缩使用 `lzma2/max` + solid 压缩，安装时解压较慢属正常现象；
* 三个架构各自出包（`x86compatible` / `x64compatible` / `arm64`），arm64 会安装到 64 位模式；
* 卸载时会删除自启计划任务（`TPMSmartCard`、`WinCryptSSHAgent`）并结束相关进程，
  不会动你的 `.tsb` 备份与 `%APPDATA%\TPMSmartCard` 下的设置和日志。

## 方式二：绿色版 zip

CI 同时产出绿色版 zip（`TPMSmartCard-*-win64.zip` 之类），适合不想安装的场景：

1. 解压到一个**你有写权限**的目录（不要放在受保护目录，否则日志与缓存写不进去）；
2. **以管理员身份运行** `SmartCardAPP.exe`；
3. 与安装版相比缺少：**系统级 OpenSC**（读卡仍可用，程序自带的 `OpenSC\` 目录够用）、
   **`.tsb` 文件关联**（双击 `.tsb` 不会打开本工具，但可以在界面里手动选文件）、
   开始菜单与卸载入口。

## 方式三：源码运行

适合开发与调试，详见 [开发方式](/guide/development)：

```powershell
# 1. 重建 Python 3.13 虚拟环境（x86 / 低版本系统线用 -PythonVersion 3.10）
powershell -File Builds\NewVenv-PY313.ps1

# 2. 安装依赖
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. 运行（需要管理员权限）
.\.venv\Scripts\python.exe SmartCardAPP.py
```

## 安装后的第一次启动

1. **以管理员身份运行**，接受 UAC；
2. 首次启动会创建工作目录并写入设置：`%APPDATA%\TPMSmartCard\settings.json`；
3. 主界面「全局相关」里点 **🔎 检测 TPM**，确认 TPM 存在且就绪（未就绪先按
   [硬件与软件要求](/guide/requirements) 自查）；
4. 确认卡片列表为空、读卡器正常后，进入 [智能卡管理](/guide/usage-cards) 创建第一张卡；
5. 需要改语言 / 主题 / 开机自启 / OpenSC / SSH 代理时，点 **⚙️ 系统设置**。

::: tip 想少踩坑，先做三件事
1. **确认自己在本地控制台**，不是远程桌面会话；
2. **准备好要保存的凭据**：卡片 PIN、PUK、管理密钥（Admin Key）—— 建卡后工具会把它们
   复制到剪贴板，请立刻存进密码管理器；
3. **先做一次备份**：卡一旦创建就尽早备份，删卡之后备份也救不回卡上私钥（见
   [备份与还原](/guide/backup)）。
:::

## 卸载

* 从「设置 → 应用」或开始菜单的卸载入口卸载；
* 卸载不会删除：`%APPDATA%\TPMSmartCard`（设置、日志）、你的 `.tsb` 备份、已经创建并存在于
  系统中的虚拟智能卡。**如果卡还要用，请勿卸载后直接删卡**；
* 卸载后卡片仍会留在读卡器列表里，需要清理时用 `tpmvscmgr destroy` 或先重新安装工具再删除卡片。

## 安装阶段常见问题

| 现象 | 原因与处理 |
|---|---|
| SmartScreen「Windows 已保护你的电脑」 | 未签名或签名不受信任；点「更多信息 → 仍要运行」。企业环境请让管理员核验哈希 |
| OpenSC MSI 安装失败，报 `1625` / `0x80070659` | MSI 安装策略被限制；仓库自带排障脚本 `Fix-MsiPolicy.ps1` / `Fix-MsiPolicy.bat`，或安装时不勾选 OpenSC 组件 |
| 提示需要管理员权限 | 安装器与主程序都要求管理员；请用管理员账户或右键「以管理员身份运行」 |
| 装完打不开 / 闪退 | 先看 `%APPDATA%\TPMSmartCard\logs\`；也可从命令行运行 `SmartCardAPP.exe` 观察输出 |
| 双击 `.tsb` 没反应 | 绿色版没有注册文件关联，在界面里手动选择备份文件即可 |

下一步：[智能卡管理](/guide/usage-cards)。
