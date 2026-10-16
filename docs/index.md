---
layout: home

hero:
  name: TPM 虚拟智能卡管理器
  text: 用 TPM 打造一张私钥永不导出的智能卡
  tagline: Windows 桌面工具 · 建卡 / 证书 / 密钥 / 备份还原全流程图形化，替代 YubiKey、ePass 等物理卡的 PIV 需求
  image:
    src: /images/tpm-smartcard-manager.png
    alt: TPM 虚拟智能卡管理器主界面
  actions:
    - theme: brand
      text: 安装与快速上手
      link: /guide/install
    - theme: alt
      text: 项目介绍
      link: /guide/
    - theme: alt
      text: 工作原理
      link: /guide/principles

features:
  - icon: 🔐
    title: 私钥由 TPM 保护
    details: 卡上私钥在 TPM 内部生成与使用，始终不以明文导出；签名与解密在硬件内完成，强度接近物理智能卡。
  - icon: 🧩
    title: 一条龙管理
    details: 创建 / 删除卡片、修改与重置 PIN、导入导出证书、本地生成密钥与 CSR，全部在同一个界面完成。
  - icon: 💾
    title: 整卡备份与还原
    details: 把五部分卡片数据打包成 .tsb，重装系统后在同一颗 TPM 上还原，并给出设备 / 读卡器 / DPAPI 三层判定结论。
  - icon: 🔑
    title: SSH2 登录
    details: 配合随包分发的 WinCryptSSHAgent，用卡上私钥登录远程服务器，代替磁盘上的私钥文件。
  - icon: 🌐
    title: 11 种界面语言
    details: 简体中文 / 繁體中文 / English / 日本語 / 한국어 / Deutsch / Français / Italiano / Português / Русский / Español。
  - icon: 📴
    title: 默认完全离线
    details: 除「云端下发证书」外全部功能离线可用；不需要订阅，不需要联网激活。
---

## 从这里开始

| 我是…… | 建议阅读顺序 |
|---|---|
| 第一次听说这个工具 | [项目介绍](/guide/) → [工作原理](/guide/principles) → [硬件与软件要求](/guide/requirements) |
| 想马上装起来用 | [安装方式](/guide/install) → [智能卡管理](/guide/usage-cards) → [证书与密钥管理](/guide/usage-certs) |
| 关心数据安全 / 备份 | [备份与还原](/guide/backup) → [安全模型](/security) |
| 要改代码或出安装包 | [开发方式](/guide/development) → [架构说明](/architecture) → [开发与调试指南](/dev-guide) |
| 现场遇到问题 | [常见问题](/guide/faq) → [故障排查手册](/troubleshooting) |
| 要部署这个文档站 | [文档站部署](/guide/deploy-docs) |

::: warning 先记住两条硬限制
1. **创建 / 删除虚拟智能卡必须在本地控制台会话执行**，远程桌面（含普通 RDP）会被系统拒绝并返回
   `0x800704d3`；RDP 请用 `mstsc /admin` 连到控制台会话。
2. **备份 `.tsb` 只能在同一颗 TPM 上还原**（本机重装系统后可以），换机器 / 换 TPM / 删除过卡片都不行。
:::
