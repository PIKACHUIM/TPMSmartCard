# v1 → v2 迁移与功能对等清单

> v1 = Python 3.13 + Tkinter + Flask（Windows 专属）
> v2 = Go + Wails v2 + React 18 + Hono/Cloudflare Workers
>
> 状态图例：✅ 已完成并通过测试 ｜ 🟡 可用但需真机验证 ｜ ⏳ 未完成（P1/P2）

## 1. 阶段划分

| 阶段 | 范围 | 验收 |
|---|---|---|
| **P0** | Worker + 管理台 + 协议兼容 + 设计系统 | `/card/*` 金标向量、RBAC/审计、OpenCertRepo 投递幂等 |
| **P1** | Go 核心库、CLI、平台卡槽、备份格式 | `go test ./...`、`tpmsc doctor`、`.tsb` v1→v2、云端取回 |
| **P2** | Wails 桌面壳、完整 UI、三平台安装包 | 三平台构建、11 语言、签名/公证、文档站更新 |

## 2. 模块对等表

| v1 模块 | v2 对应 | 状态 | 说明 |
|---|---|---|---|
| `Module/Cryptography.py` | `core/internal/crypto` | ✅ | RFC 7914 向量 + 两种模式往返测试 |
| `SmartCardWEB.py` `/get/cert` `/put/cert` | `worker/src/routes/card.ts` | ✅ | 响应 `{flag,data}` 逐字段兼容；支持 GET body |
| `SmartCardWEB.py` `/web/cert` | `worker/src/lib/page.ts` | ✅ | 服务端渲染，零外部依赖 |
| `templates/` 上传页 | 同上 + `web` 管理台 | ✅ | 取件码模式新增表单校验 |
| `Module/TPMSmartCard.py` | `platform/win32` | 🟡 | 建卡/删卡/改 PIN + PnP 枚举；证书走 OpenSC |
| `Module/SmartCardAPI.py` | `platform/p11` | ✅ | `pkcs15-tool` 读取、`pkcs15-init` 导入 |
| `Module/CertutilDeal.py` | 待补 | ⏳ | v1 的 certutil 回退后端未迁移 |
| `Module/OpenSCDealer.py` | `platform/p11` | 🟡 | 证书读取已迁移；解析覆盖常见格式 |
| `Module/Certificates.py` | `platform.Certificate` | ✅ | X.509 视图字段对齐前端 |
| `Module/TPMBackup.py` | `internal/backup` | 🟡 | v2 包格式与校验完成；DPAPI 采集未接 |
| `Module/DPAPI.py` | 待补 | ⏳ | 需借用 SYSTEM 令牌，P1 关键项 |
| `Module/SSHAgent.py` | `internal/sshagent` | 🟡 | 协议帧/身份/签名分发 + 测试完成；卡上签名适配待 `Slot.Sign` |
| `Module/Fido*` + `Fido/src/fido-go` | `Fido/src/fido-go` | 🟡 | 本身已是 Go 模块（含 vendored virtual-fido），待并入统一构建与发布 |
| `Module/I18n.py` + `Config/locales/*.json` | `web/src/locales/*.json` | 🟡 | 11 语言骨架；键集需补全到 v1 规模 |
| `Module/Theme.py` + `Config/themes.json` | `web` 设计令牌 | ✅ | 石墨 + 紫铜，双主题 |
| `Module/TrayIcon.py` | Wails 外壳 | 🟡 | Windows 托盘菜单（显示/浏览器/重启/退出）；macOS/Linux 待 P2 |
| `Module/AutoStart.py` | `internal/autostart` | ✅ | Windows Run 项 / macOS LaunchAgent / Linux XDG，设置页可切换 |
| `Module/Paths.py` / `Version.py` | `core/internal/api` + ldflags | ✅ | 数据目录与版本注入 |
| `Module/WinPlatform.py` | `platform/win32` | 🟡 | 提权/远程会话判定已迁移 |
| `SubApp/CertImport.py` | 本地 API + UI 导入 | 🟡 | 后端导入接口就绪，UI 走证书页 |
| `SubApp/SystemSettings.py` | `web` 设置页 | 🟡 | 外观/语言/平台能力；自启与 SSH 待接后端 |
| `SubApp/MoreConfig.py` | 设置页 | ⏳ | OpenSC 安装器分发未迁移 |
| `BuildPackage.py` / `install.iss` | `scripts/package-*.{sh,ps1}` | 🟡 | Windows zip 与 Linux tar.gz / macOS .app 脚本就绪；msi/dmg 未做 |
| `Builds/Sign-Windows.ps1` | CI + 打包脚本 | 🟡 | 签名钩子（`TPMSC_SIGN_TOOL` / `MACOS_SIGN_IDENTITY`）已留位，未接 Secrets |

## 3. P0 验收结果（已执行）

| 项目 | 结果 |
|---|---|
| `worker` 单元测试 | ✅ 3 文件 / 23 用例通过 |
| `worker` 类型检查 | ✅ `tsc --noEmit` 无错误 |
| 前端构建 | ✅ `tsc -b && vite build` 通过 |
| Go 单元测试 | ✅ crypto / cloud / backup 全部通过 |
| 跨平台编译 | ✅ `GOOS=linux`、`GOOS=darwin` 均通过 |
| Wails 桌面端 | ✅ `go build -tags desktop` 通过（含 Windows 托盘） |
| 本地 API 契约 | ✅ 4 用例（CSRF 401 / 建卡 / 证书 / 统计） |
| SSH agent 协议 | ✅ 3 用例（身份列表 / 签名验签 / 超长帧拒绝） |
| Windows 打包脚本 | ✅ 产出 `dist/TPMSmartCard-2.0.0-windows-amd64.zip` |
| 开机自启 | ⏳ 未执行真机写入（会改用户注册表 / LaunchAgent，需手动确认） |
| 部署 | ⏳ 需配置 D1/KV 与 Secrets 后执行 |

## 4. 已知风险与对策

| 风险 | 现状 | 对策 |
|---|---|---|
| macOS Secure Enclave | 未接 cgo，能力上报为不支持 | 用 Developer ID 签名构建 `darwin && cgo` 实现 `SecKeyCreateRandomKey` + `SecKeyCreateSignature` |
| DPAPI 备份 | 未迁移 | 借 SYSTEM 令牌做一次往返探针后再采集 `keymaps` / `pinmaps` |
| Linux TPM2 真机差异 | 仅静态实现 | `tpmsc doctor` 探针 + 错误码映射；CI 只做编译检查 |
| 取件码并发超发 | KV 最终一致 | 默认 `max_uses=1`，文档标注；需要严格一次性时改用 D1 条件更新（已实现 `consumeUse`） |
| Worker CPU 预算 | PBKDF2 100k | 免费套餐下调 `PBKDF2_ITERATIONS`，生产建议 Paid |
| 11 语言覆盖 | 键集小于 v1 | 以 `Config/locales/*.json` 为源生成差异清单后补全 |

## 5. 回退与并行

- Python 版本保持可运行（`legacy/README.md` 记录了归档计划与命令前缀）。
- 新旧两条流水线并行：`build-client-*.yml`（v1）与 `build-desktop-v2.yml`（v2）。
- `.tsb v2` 读取器识别 v1 包并明确拒绝跨机还原；**不提供**v2 → v1 的降级写入。
