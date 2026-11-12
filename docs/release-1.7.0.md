# v1.7.0 更新说明（Python 主线收官）

> **定位**：这是 **Python 主线（Tkinter + Flask）最后一个功能版本**，也是 Go 重构（v2）的基线。
> 标签 `v1.7.0` 指向重构前最后一个提交（`c7bf06a`），后续 `main` 分支进入 v2 架构。

## 一、这个版本包含什么

### 卡片与凭据

- 创建 / 删除 TPM 虚拟智能卡，修改与重置 PIN、PUK、管理密钥
- 导入 / 删除 / 查看 X.509 证书与卡上密钥对象，查看证书链与密钥用法
- 本地生成密钥 + CSR 后签发，或从云端安全下发（X25519 密钥协商 + AES-256 加密）
- 取件码模式：无需预先交换密钥，填写 16 位取件码即可取回证书

### 备份与还原

- 整卡打包为 `.tsb`（卡片数据 + 设备注册表 + TPM 密钥索引 + 设备属性 + DPAPI 明文）
- 还原前做设备节点 / 读卡器 / DPAPI 三层诊断，并给出可执行结论与日志
- **硬限制**：只能在同一颗 TPM 上还原；删除卡片后即使有备份也无法还原

### 场景与工具

- **内置 SSH 代理**：用卡上私钥登录远程服务器，公钥可一键登记到 `~/.ssh/authorized_keys`
- **FIDO2 / 通行密钥**：FIDO 服务随包分发，支持在浏览器中完成注册与登录
- 环境工具：安装 OpenSC、查看 TPM 状态、导出证书与公钥
- 11 种界面语言：简体中文 / 繁體中文 / English / 日本語 / 한국어 / Deutsch / Français / Italiano / Português / Русский / Español

## 二、自 v1.6 以来的主要变化

| 变更 | 说明 |
|---|---|
| 内置 SSH 代理 | 不再依赖外挂 `SSHCardAgent.exe`，支持多证书登记与 Git 场景 |
| 通行密钥详情 | 改为六行紧凑排布，补充 RP 名称与 UUID，加宽证书容器 ID 列 |
| 还原诊断 | 输出「结论 + 逐条日志 + 现场诊断」三段式结果并落盘 |
| 多语言 | 语言包键集与界面同步，修正部分翻译溢出 |

## 三、下载与安装

本 Release 附带的构建产物来自 `beta` 滚动预发布的最新一轮（Build #61），包含：

| 文件 | 适用系统 | 说明 |
|---|---|---|
| `TPMSmartCard-cxfree-beta-win10-x64-setup.exe` | Windows 10/11 x64 | 安装版 |
| `TPMSmartCard-cxfree-beta-win10-x64-green.zip` | Windows 10/11 x64 | 绿色版 |
| `TPMSmartCard-cxfree-beta-win11-a64-setup.exe` | Windows 11 arm64 | 安装版 |
| `TPMSmartCard-cxfree-beta-win11-a64-green.zip` | Windows 11 arm64 | 绿色版 |
| `TPMSmartCard-cxfree-beta-win78-x86-setup.exe` | Windows 8/8.1/10 x86 | 安装版 |
| `TPMSmartCard-cxfree-beta-win78-x86-green.zip` | Windows 8/8.1/10 x86 | 绿色版 |

安装与使用：

1. 下载对应架构的安装包，**以管理员身份运行**（注册卡片设备、读写系统目录需要权限）；
2. 在「卡片管理」中创建卡片 → 导入或生成证书；
3. 备份：选中卡片 → 备份，得到 `.tsb`；还原：选中 `.tsb` → 还原。

> **远程桌面限制**：创建 / 删除虚拟智能卡不能在 RDP 会话中进行，Windows 会返回 `0x800704d3`。
> 请在本机控制台操作，或使用 `mstsc /admin` 连接控制台会话。

## 四、升级注意事项

1. `.tsb` 备份**只在同一颗 TPM 上**可还原；升级前建议先做一次备份并验证。
2. 覆盖安装不会删除卡片；卸载程序时若勾选清理数据，会一并删除本机设置与日志。
3. 若证书链报 `CERT_E_CHAINING`，把签发该证书的中级 CA 导入「受信任的根/中间证书」即可。

## 五、关于 v2（Go 重构）

`main` 分支已开始 v2 重构，目标是：

- 后端迁移到 **Go**，支持 Windows / Linux / macOS；Linux 走 TPM2 + PKCS#11，macOS 走钥匙串 + Secure Enclave
- 前端重写为 **React 18**，桌面端（Wails v2）与管理台共用同一份构建产物
- 证书下发服务迁移到 **Hono + Cloudflare Workers**，带多用户 RBAC 与操作审计

v1.7.0 是 Python 线的稳定回退点；v2 达到功能对等前，本版本仍可继续使用。

---

**许可**：GPL-3.0 · **问题反馈**：请附上 `%APPDATA%\TPMSmartCard\logs\` 下的日志
