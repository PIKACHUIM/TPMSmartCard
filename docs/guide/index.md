# 项目介绍

**TPM 虚拟智能卡管理器（TPM Virtual Smartcard Manager）** 是一款运行在 Windows 上的图形化工具，
用来**创建与管理 TPM 虚拟智能卡**（TPM Virtual Smart Card），并管理卡上的 X.509 证书与密钥。

它把"建卡 → 生成 / 导入证书 → 用卡（SSH 登录）→ 备份与还原"这条原本需要一堆命令行与文档的链路，
收敛到一个界面里；底层直接用 Windows 自带能力（`tpmvscmgr`、`certutil`、TPM 硬件）与随包分发的
[OpenSC](https://github.com/OpenSC/OpenSC) 工具，不引入额外的服务或驱动。

![主界面](/images/tpm-smartcard-manager.png)

::: tip 一句话理解它
TPM 虚拟智能卡 = **用主板上的 TPM 芯片冒充一张智能卡**。私钥在 TPM 内部生成与使用、
**始终不能以明文导出**，强度接近物理智能卡；而它不需要采购硬件、不占 USB 口、不用随身携带。
:::

## 它能做什么

### 卡片与凭据

* **虚拟智能卡**：创建、删除卡片，修改 PIN、重置 PIN（PUK）、设置管理密钥（Admin Key）
* **证书与密钥**：导入、删除、查看 X.509 证书与卡上密钥对象，查看证书链与密钥用途
* **生成与下发**：本地生成密钥 + CSR（`certreq`）后签发；或从云端安全下发私钥 / 证书
  （PBKDF2 派生 + AES-256-CBC，取件码带外传递）

### 备份与还原

* **整卡备份**：把一张卡的**五个组成部分**完整打包成 `.tsb`（卡片数据目录 + 设备注册表 +
  TPM 密钥索引 + 设备属性 + DPAPI 明文），详见 [备份与还原](/guide/backup)
* **同 TPM 还原**：重装系统后可在**同一颗 TPM** 上还原（换机器 / 换 TPM / 删除过卡片都不行）
* **还原诊断**：还原后自动判定「设备节点 / 读卡器 / DPAPI」三层状态，给出可执行的结论与日志

### 场景与工具

* **SSH2 登录**：配合随包分发的 WinCryptSSHAgent，用卡上私钥登录远程服务器
* **环境工具**：安装 / 启动 OpenSC 与 SSH 代理、检测 TPM 状态、导出证书
* **系统设置**：主题与界面语言、开机自启与托盘、OpenSC / WinSSH 代理管理、检查更新
* **多语言界面**：11 种语言（简体中文 / 繁體中文 / English / 日本語 / 한국어 / Deutsch /
  Français / Italiano / Português / Русский / Español）

## 和物理智能卡、普通软件证书比

| 维度 | 物理智能卡（YubiKey / ePass 等） | **本工具（TPM 虚拟智能卡）** | 普通软件证书（用户证书存储） |
|---|---|---|---|
| 私钥存放位置 | 卡内安全芯片 | 本机 TPM 内部持久对象 | 硬盘文件（可被复制） |
| 私钥能否导出 | 不能 | **不能** | 能 |
| 需要额外硬件 | 需要（采购+携带） | 不需要（用主板 TPM） | 不需要 |
| 占用 USB 口 / 需随身携带 | 是 | 否 | 否 |
| 换机器迁移 | 卡可带走 | **不可迁移**（与 TPM 绑定） | 文件可带走 |
| 防暴力破解 | PIN 重试计数 | PIN / PUK 重试策略（TPM 内） | 无 |
| 成本 | 采购费用 | Windows 自带，免费 | 免费 |

> 一句话取舍：**虚拟智能卡换来了"免硬件 + 私钥不可导出"，代价是"卡锁死在这台机器上"**。
> 如果你的场景要求"人走到哪卡跟到哪"，物理卡更合适；如果只是"本机需要一个不可导出的密钥容器"
> （代码签名、SSH 登录、内网双因素、TLS 客户端认证），虚拟智能卡更划算。

## 适用与不适用

| 场景 | 是否合适 | 说明 |
|---|---|---|
| 代码签名 / 文档签名 | ✅ | 私钥不可导出，比 PFX 文件安全得多 |
| SSH 登录远程服务器 | ✅ | 见 [SSH2 登录](/guide/ssh) |
| 客户端证书认证（VPN / 内网系统） | ✅ | 证书在用户存储中，系统会正常发起认证 |
| 双因素认证（智能卡登录域） | ⚠️ | 虚拟智能卡可以做，但需域侧策略配合（域控制器 / 证书模板），本工具只负责卡与证书本身 |
| 需要随身携带 / 跨机器使用 | ❌ | 虚拟智能卡与 TPM 绑定，不能迁移 |
| 在远程桌面里创建卡片 | ❌ | 系统禁止（`0x800704d3`），必须本机控制台 |
| 备份卡到另一台机器还原 | ❌ | 只支持同一颗 TPM，见 [备份与还原](/guide/backup) |

## 文档地图

| 章节 | 内容 |
|---|---|
| [工作原理](/guide/principles) | 虚拟智能卡由哪几部分组成、工具是怎么操作系统的、私钥为什么不可导出 |
| [硬件与软件要求](/guide/requirements) | 系统版本、TPM、权限、系统组件、网络与场景限制 |
| [安装方式](/guide/install) | 安装包 / 绿色版 / 源码运行 / 卸载 / 首次启动检查 |
| [智能卡管理](/guide/usage-cards) | 建卡、改 PIN、重置 PIN、删除卡、卡片详情 |
| [证书与密钥管理](/guide/usage-certs) | 导入 PFX / CER、生成 CSR、导出证书、删除密钥、云端下发 |
| [SSH2 登录](/guide/ssh) | 用卡上私钥登录远程服务器 |
| [备份与还原](/guide/backup) | `.tsb` 里有什么、还原前提、三层判定 |
| [常见问题](/guide/faq) | 集中回答使用者最常问的问题 |
| [开发方式](/guide/development) | 环境、运行、打包、CI、代码约定 |
| [文档站部署](/guide/deploy-docs) | 本站在 GitHub Pages 上的构建与自定义域名配置 |

工程侧的深入文档（架构、设计、安全模型、故障排查、技术报告）在
[工程文档索引](/README) 中统一列出。

## 许可与致谢

* 项目基于 **GPL-3.0** 开源，源码在 [PIKACHUIM/TPMSmartCard](https://github.com/PIKACHUIM/TPMSmartCard)，
  见 [LICENSE](https://github.com/PIKACHUIM/TPMSmartCard/blob/main/LICENSE)。
* 参考与依赖：[OpenSC/OpenSC](https://github.com/OpenSC/OpenSC)（开源智能卡中间件）、
  [Microsoft Docs: Virtual Smart Cards](https://github.com/MicrosoftDocs/windows-itpro-docs/tree/public/windows/security/identity-protection/virtual-smart-cards)、
  WinCryptSSHAgent（用智能卡私钥做 SSH 认证的代理）。
