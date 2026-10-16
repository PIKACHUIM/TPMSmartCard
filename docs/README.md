# 文档索引

本目录存放工程的**长期文档**（架构、设计、安全、排查、开发指南）与技术报告。
代码目录里不放文档；所有文档统一放在 `docs/`，文件名用小写英文 + 连字符。

## 文档地图

| 文档 | 内容 | 主要读者 |
|---|---|---|
| [`architecture.md`](architecture.md) | 项目定位、进程与入口、模块分层职责、界面与配置驱动、多语言机制、运行时路径、卡片数据模型、版本与发布 | 新加入的开发者、评审 |
| [`design-backup-restore.md`](design-backup-restore.md) | 备份 / 还原的**方案与设计**：不变量、数据模型、备份与还原流程、状态判定、错误处理与降级、兼容性策略、设计决策记录 | 开发者、评审 |
| [`report-backup-restore.md`](report-backup-restore.md) | 备份 / 还原的**技术报告**：问题背景、五个断点的根因与修复、实现清单、真机验证证据、已知边界、可复现验收步骤 | 评审、验收方 |
| [`security.md`](security.md) | 安全模型：资产与信任边界、权限要求、DPAPI 与令牌借用、备份包明文风险与缓解、凭据与日志卫生 | 开发者、安全评审 |
| [`troubleshooting.md`](troubleshooting.md) | 故障排查手册：症状 → 判定命令 → 结论与处理 | 使用者、支持人员 |
| [`dev-guide.md`](dev-guide.md) | 开发与调试：环境、运行方式、自检 CLI、打包（cx_Freeze / Nuitka / Inno Setup）、签名、CI、代码约定、真机验证方法 | 开发者 |
| [`devlog-2026-10-14-backup-restore.md`](devlog-2026-10-14-backup-restore.md) | **早期过程记录**（现含 §1–§11，止于 2026-10-15）：逆向与实机定位的命令行证据。仅作证据来源，不作为结论；其后进展见技术报告 | 需要追溯细节的人 |

根目录的
[`README.md`](https://github.com/PIKACHUIM/TPMSmartCard/blob/main/README.md)
是**面向使用者**的产品说明（介绍、功能、系统要求）。

## 在线文档站

本目录同时是 **VitePress 文档站**的源码目录，由 CI 构建后发布到 GitHub Pages，
面向使用者的内容在 [`guide/`](https://github.com/PIKACHUIM/TPMSmartCard/tree/main/docs/guide) 下：

| 章节 | 内容 |
|---|---|
| [`guide/index.md`](guide/index.md) | 项目介绍、能力矩阵、适用与不适用场景 |
| [`guide/principles.md`](guide/principles.md) | 工作原理：五部分构成、工具与系统命令的对应关系、私钥不可导出的原因 |
| [`guide/requirements.md`](guide/requirements.md) | 硬件与软件要求、环境自查命令、不支持的环境 |
| [`guide/install.md`](guide/install.md) | 安装包 / 绿色版 / 源码运行、卸载、安装排错 |
| [`guide/usage-cards.md`](guide/usage-cards.md) | 智能卡管理：建卡、改 / 重置 PIN、删卡、详情 |
| [`guide/usage-certs.md`](guide/usage-certs.md) | 证书与密钥管理：导入 PFX / CER、生成 CSR、导出、云端下发 |
| [`guide/ssh.md`](guide/ssh.md) | 用卡上私钥做 SSH2 登录 |
| [`guide/backup.md`](guide/backup.md) | 备份与还原：包内容、还原前提、三层判定 |
| [`guide/faq.md`](guide/faq.md) | 常见问题 |
| [`guide/development.md`](guide/development.md) | 开发方式：环境、运行、打包、CI、代码约定 |
| [`guide/deploy-docs.md`](guide/deploy-docs.md) | 本文档站的构建与 GitHub Pages / 自定义域名配置 |

本地预览：`cd docs && npm install && npm run docs:dev`。

## 建议的阅读路径

| 场景 | 顺序 |
|---|---|
| 第一次接触本工程 | `architecture.md` → `design-backup-restore.md` |
| 验收「备份 / 还原」能力 | `report-backup-restore.md` →（按其中的验收步骤实操） |
| 排查现场问题 | `troubleshooting.md` → 必要时查 `devlog` 对应章节 |
| 安全评审 | `security.md` → `design-backup-restore.md` §DPAPI 设计 |
| 改代码 / 出包 | `dev-guide.md` → `architecture.md` |

## 文档维护约定

1. **结论与过程分离**：结论、方案、设计进本目录的正式文档；逐日过程、失败与纠错进 `devlog-*`。
2. **证据可追溯**：正式文档里给出的判定与数字，尽量附「命令 / 日志摘录 / 文件路径」，便于复核。
   原始证据指向 `devlog` 对应小节。
3. **未验证的东西必须标注**：写「已实测」或「未验证」，不写模棱两可的话。
4. **文档与代码同批提交**：行为变化时同步更新对应文档，避免文档过期误导排查。

## 待补文档（尚未编写）

| 文档 | 内容 |
|---|---|
| 用户手册 | 逐界面操作步骤、常见任务（建卡、导入证书、SSH 登录、备份还原） |
| 发布流程 | 版本号规则、两条构建线（cx_Freeze / Nuitka）的选择、签名与 CI 触发条件、回滚方式 |
| 云端下发协议 | `Cryptography.py` 的取件码 + PBKDF2 + AES-256-CBC 流程与接口约定 |
| Web 端说明 | `SmartCardWEB.py` 的部署、端口、语言协商、证书缓存位置 |
