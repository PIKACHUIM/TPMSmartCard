<div align="center">
# TPM Virtual Smartcard Manager

_一款在 Windows 上创建与管理 TPM 虚拟智能卡的图形化工具_

<img src="Images/QQ20261016-184916.png" width="760" alt="TPM 虚拟智能卡管理器">



基于 TPM 的虚拟智能卡提供接近物理智能卡的强度，私钥由 TPM 保护、始终不以明文导出

支持本地生成密钥与 CSR 和云端安全下发证书，替代 YubiKey、ePass 等物理卡的PIV需求


[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![Build](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml/badge.svg)](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml)
[![Release](https://img.shields.io/github/v/release/PIKACHUIM/TPMSmartCard?include_prereleases&label=release)](https://github.com/PIKACHUIM/TPMSmartCard/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%208%2B-0078D6.svg)](#-系统要求)

📘 [文档索引](docs/README.md) · 🧭 [架构说明](docs/architecture.md) · 💾 [备份还原设计](docs/design-backup-restore.md) · 🛠️ [故障排查](docs/troubleshooting.md) · 🔐 [安全模型](docs/security.md)

[English](readmes/README_en.md) | 简体中文 | [繁體中文](readmes/README_zh-Hant.md) | [日本語](readmes/README_ja.md) | [한국어](readmes/README_ko.md)<br>[Deutsch](readmes/README_de.md) | [Français](readmes/README_fr.md) | [Italiano](readmes/README_it.md) | [Português](readmes/README_pt.md) | [Русский](readmes/README_ru.md) | [Español](readmes/README_es.md)
</div>
---

## ✨ 功能

### 卡片与凭据

* **虚拟智能卡**：创建、删除卡片，修改 / 重置 PIN、PUK 与管理密钥
* **证书与密钥**：导入、删除、查看 X.509 证书与卡上密钥对象，查看证书链与密钥用法
* **生成与下发**：本地生成密钥 + CSR 后签发；或从云端安全下发（X25519 密钥协商 + AES 加密，取件码带外传递）

### 备份与还原

* **整卡备份**：把一张卡完整打包成 `.tsb`（卡片数据 + 设备注册表 + TPM 密钥索引 + 设备属性 + DPAPI 明文）
* **同 TPM 还原**：只能在同一颗 TPM 上还原（在本机重装系统后可以；**换机器 / 换 TPM 不行**，**删除卡片后也无法还原**）；DPAPI 数据在备份时解开、还原时用本机主密钥重新加密（详见 [备份还原设计](docs/design-backup-restore.md)）
* **还原诊断**：还原后自动判定设备节点 / 读卡器 / DPAPI 三层状态，并给出可执行的结论与日志

### 场景与工具

* **SSH2 登录**：配合 WinCryptSSHAgent 用卡上私钥登录远程服务器
* **环境工具**：安装 / 启动 OpenSC 与 SSH 代理、查看 TPM 状态、导出证书与公钥
* **多语言界面**：11 种语言（简体中文 / 繁體中文 / English / 日本語 / 한국어 / Deutsch / Français / Italiano / Português / Русский / Español）

---

## 🚀 快速开始

1. 到 [Releases](https://github.com/PIKACHUIM/TPMSmartCard/releases) 下载 `TPMSmartCard-*-setup.exe`（或绿色版 zip）并安装；
2. **以管理员身份运行**（注册卡片设备、读写系统目录都需要管理员权限）；
3. 在「卡片管理」里创建卡片 → 导入或生成证书 →（可选）在「系统设置」里安装并启动 SSH 代理；
4. 备份：选中卡片 → 备份，得到 `.tsb`；还原：选中 `.tsb` → 还原。

> [!IMPORTANT]
> **创建 / 删除虚拟智能卡不能在远程桌面（终端服务）会话中进行**，Windows 会拒绝并返回 `0x800704d3`。
> 请到本机控制台操作，或用 `mstsc /admin` 连接到控制台会话。

> [!TIP]
> 读卡所需的 [OpenSC](https://github.com/OpenSC/OpenSC/releases) 工具**已随程序分发**（程序目录的 `OpenSC` 文件夹），
> 无需另外安装；安装包里的系统级 OpenSC 组件是可选项，仅供其它软件使用（PKCS#11 客户端、物理卡 minidriver 等）。

---

## 🧩 系统要求

| 项 | 要求 |
|---|---|
| 系统 | Windows 8 x86 / x64 或更高（**需要管理员权限**） |
| 硬件 | TPM 1.2 / 2.0 或更高 |
| 系统组件 | `tpmvscmgr`、`certutil`（系统自带） |
| 随包组件 | OpenSC 工具、WinCryptSSHAgent、`Import`（.NET 证书导入工具） |

---

## 🏗️ 技术架构

| 维度 | 取值 |
|---|---|
| 语言 / 运行时 | Python **3.11** |
| 界面 | Tkinter + ttkbootstrap（纯代码构建界面，布局由 `Config/*.json` 驱动） |
| 卡片操作 | `tpmvscmgr`（建卡 / 删卡 / 改 PIN）+ OpenSC（读卡与证书）+ 自研 PnP / SetupAPI 层（设备节点与属性） |
| 备份还原 | 自研 `.tsb`（zip）打包；`Module/DPAPI.py` 负责 DPAPI 加解密与令牌借用 |
| 打包 | 两条流水线：**cx_Freeze**（正式包，Inno Setup 出安装器）与 **Nuitka**（standalone 目录） |
| 多语言 | `Config/locales/*.json`，11 种语言 |

---

## 🛠️ 开发构建

```bash
# 1. 准备 Python 3.11 环境（推荐用仓库自带脚本重建 venv）
powershell -File Builds\NewVenv-PY311.ps1

# 2. 安装依赖
pip install -r requirements.txt

# 3. 直接从源码运行（需要管理员权限）
python SmartCardAPP.py

# 4. 打包
python BuildPackage.py build      # cx_Freeze：三个 exe + 随包资源
python BuildNuitka.py             # Nuitka：build/nuitka/TPMSmartCard/
```

* 依赖自查：`python Builds/check_imports.py`
* 完整开发说明（运行方式、打包、签名、CI、真机调试方法）：[开发与调试指南](docs/dev-guide.md)
* 代码结构与模块职责：[架构说明](docs/architecture.md)

---

## 💾 备份还原

一张可用的 TPM 虚拟智能卡由**五个部分**共同构成，`.tsb` 会把这五部分全部收进包里：

| 组成 | 内容 | 缺失后果 |
|---|---|---|
| 卡片数据目录 | `Tpm\<store GUID>\`（卡内文件系统与密钥 / PIN 映射） | 卡片没有内容 |
| 设备注册表 | `ROOT\SMARTCARDREADER\<实例>` 等 | 设备节点建不出来 |
| TPM 密钥索引 | `*.PCPKEY`（3 个候选目录） | 驱动找不到卡上密钥 |
| 设备属性 | 卡片名、卡片 GUID、store 绑定（ACL 保护，注册表导出拿不到） | 读卡器不会发布到 PC/SC |
| DPAPI 明文 | `keymaps` / `pinmaps` / `pinpolicy` / `blobs\*` 的明文（还原时用目标机重新加密） | 证书与私钥不显示 |

> [!WARNING]
> 因为包含上表最后一项，**`.tsb` 等同于卡片密钥材料**：请离线妥善保管，不要放进版本库、云盘或聊天工具。
> 还原时工具会用目标机的 DPAPI 重新加密后写回；建议同时保管好卡片名称、PIN、PUK 与管理密钥。

其它说明：

* **还原前提**：必须**同一颗 TPM**（在本机重装系统后可以还原；换机器、换 TPM 都不行），且**卡片没有被删除**
  —— 删除卡片会清除它在 TPM 内的持久密钥，删除之后即使有备份也无法还原；
* 还原后**可能需要重启设备（驱动）或重启系统**，卡片才会出现在读卡器列表中；
* 旧版本工具做的 `.tsb` 不含「设备属性」与「DPAPI 明文」，用它还原会缺卡片身份、读卡器不会出现，请用新版本重新备份。

---

## ❓ 常见问题

**Q：为什么在远程桌面里创建卡片失败，报 `0x800704d3`？**
A：Windows 禁止在终端服务会话中创建 / 删除虚拟智能卡。请在本机控制台操作，或用 `mstsc /admin` 连接控制台会话。

**Q：备份能在别的机器上还原吗？**
A：**不能**。备份只适用于**同一颗 TPM**：在本机重装系统后可以还原，换机器或换 TPM 都不行；而且**卡片被删除后**
**也无法还原**（删除卡片会清除它在 TPM 内的持久密钥）。还原后若卡片没出现，先重启设备或重启系统再试。

**Q：还原后读卡器没出现 / 证书不显示怎么办？**
A：先看还原日志的三层判定（设备节点 / 读卡器 / DPAPI）。常见原因是「用旧版本备份的包」或缺卡片身份属性；
对照 [故障排查手册](docs/troubleshooting.md) 逐步判定，或把日志发到 Issues。

**Q：需要联网吗？**
A：除「云端下发证书」外全部离线可用。

**Q：证书链报 `CERT_E_CHAINING`？**
A：签发该证书的中级 CA 没装在当前机器上，把它导入「受信任的根/中间证书」即可。

---

## 🤝 帮助支持

* 🐛 **Bug 或功能请求**：请到 [Issues](https://github.com/PIKACHUIM/TPMSmartCard/issues) 提交（附上 `%APPDATA%\TPMSmartCard\logs\` 下的日志）
* 💬 **使用问题**：也欢迎在 Issues 中讨论

---

## 📄 开源许可

本项目基于 **GPL-3.0** 许可证开源，详见 [LICENSE](LICENSE)。

## 🙏 参考

1. [OpenSC/OpenSC](https://github.com/OpenSC/OpenSC) —— 开源智能卡工具与中间件
2. [Microsoft Docs: Virtual Smart Cards](https://github.com/MicrosoftDocs/windows-itpro-docs/tree/public/windows/security/identity-protection/virtual-smart-cards)
3. WinCryptSSHAgent —— 用智能卡私钥做 SSH 认证的代理程序


