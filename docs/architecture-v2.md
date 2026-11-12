# 架构说明（v2：Go + Wails + Hono Worker）

> v1（Python / Tkinter / Flask）的结构见 [architecture.md](architecture.md)。
> 本文描述 P0–P2 的目标架构，并标注每个模块的落地状态。

## 1. 分层

```
┌─────────────────────────────────────────────────────────────┐
│ web/  React 18 + Tailwind（桌面端与管理台共用一份产物）        │
└───────────────┬──────────────────────────────┬──────────────┘
                │ 同源 REST / SSE              │ 同源 REST
┌───────────────▼──────────────┐   ┌───────────▼──────────────┐
│ desktop/wails（Wails v2）      │   │ worker/（Hono + Workers） │
│  · 反向代理到内嵌 API          │   │  · /card/* 证书下发       │
│  · 单实例 / 原生打开           │   │  · RBAC + 审计（D1）      │
└───────────────┬──────────────┘   │  · KV 存密文              │
                │ 进程内            └───────────┬──────────────┘
┌───────────────▼──────────────────────────────┐│
│ core/（Go：CLI + 库 + 本地 API + SSE）         ││ 服务间 HMAC
│  platform.Slot：windows_vsc / tpm2 / keychain ││
│  crypto · cloud · backup · api · protocol     ││
└───────┬──────────────┬──────────────┬─────────┘│
        │              │              │          │
   tpmvscmgr       tpm2-pkcs11     Security     OpenCertRepo
   SetupAPI        pkcs11-tool    Keychain      server-card
   DPAPI           OpenSC          OpenSC
```

## 2. 目录与职责

| 目录 | 职责 | 状态 |
|---|---|---|
| `core/internal/crypto` | 与 v1 逐字节互通的协议实现 | ✅ 完成（含金标测试） |
| `core/internal/cloud` | v1/v2 取回客户端 | ✅ 完成（含 httptest） |
| `core/internal/platform` | `Slot` / `Capability` 抽象 | ✅ 完成 |
| `core/internal/platform/win32` | `tpmvscmgr` 建卡/删卡/改 PIN、PnP 枚举 | ✅ 基础可用（证书读写依赖 OpenSC） |
| `core/internal/platform/tpm2` | `tpm2_ptool` token 管理 | ✅ 基础可用（需真机验证） |
| `core/internal/platform/darwin` | 钥匙串证书读写 | ⚠️ Secure Enclave 待 cgo 接入 |
| `core/internal/platform/p11` | OpenSC CLI 只读后端 | ✅ 证书读取与导入 |
| `core/internal/backup` | `.tsb` v2 清单 / 校验 / 解包 | ✅ 完成（含 v1 识别） |
| `core/internal/api` | 本地 REST + SSE + CSRF 防线 | ✅ 完成 |
| `core/internal/autostart` | Windows Run / macOS LaunchAgent / Linux XDG | ✅ 完成（UI 已接） |
| `core/internal/sshagent` | SSH agent 协议帧、身份与签名分发 | ✅ 协议 + 测试（卡上签名适配待 `Slot.Sign`） |
| `core/cmd/tpmsc` | CLI（doctor/card/cert/backup/cloud/serve） | ✅ 完成 |
| `desktop/wails` | Wails v2 外壳、反代、单实例、托盘 | 🟡 Windows 托盘可用；macOS/Linux 托盘待 P2 |
| `web` | 设计系统 + 9 个页面 + 11 语言骨架 | ✅ 可构建 |
| `worker` | `/card/*`、RBAC、审计、投递 | ✅ 单测通过，待真机部署 |
| `Fido/src/fido-go` | FIDO2 服务（已是 Go 独立模块） | 🟡 已纳入 CI 构建；尚未与桌面端生命周期联动 |

## 3. 平台能力矩阵

| 能力 | Windows | Linux | macOS |
|---|---|---|---|
| 建卡 / 删卡 | `tpmvscmgr` | `tpm2_ptool addtoken/rmtoken` | 不支持（云端/钥匙串条目） |
| PIN / PUK | `tpmvscmgr changePin` | `pkcs11-tool --change-pin` | 无 PIN 语义 |
| 证书读取 | OpenSC `pkcs15-tool` | 同左 | `security` + OpenSC |
| 密钥生成 / CSR | ⏳ PKCS#11 引擎 | ⏳ `tpm2tss-genkey` | ⏳ Secure Enclave cgo |
| 备份还原 | ⏳ DPAPI 层 | ⏳ TPM2 seal | 仅证书/链/元数据 |
| SSH Agent | 🟡 协议就绪，签名待接 | 🟡 同左（Unix socket 可用） | 🟡 同左 |
| FIDO2 | ⏳ 独立模块待并入 | ⏳ | ⏳ |
| 开机自启 | ✅ Run 项 | ✅ XDG autostart | ✅ LaunchAgent |
| 系统托盘 | ✅（Windows） | ⏳ | ⏳ |

> 「不支持」必须由 `Capability` 上报并由 UI 置灰说明，不允许静默失败。

## 4. 关键设计决策

1. **CLI 优先而非 cgo**：卡片读写走 `opensc-tool` / `pkcs15-tool` / `tpm2_ptool`，
   保住 `CGO_ENABLED=0` 的 Windows 交叉编译；只有 Wails 与 macOS SE 需要 cgo。
2. **Wails v2 而非 Tauri**：后端已经是 Go，同进程内嵌省掉 sidecar 与 IPC；
   Wails v3 仍处预发布，暂不迁移。
3. **前端只有一份**：Wails 反代到内嵌 API，Worker 用 Static Assets 托管，
   同一个 `web/dist` 服务两端，避免「管理台和桌面端长得不一样」。
4. **本地 API 的 CSRF 防线**：写操作要求 `X-Requested-With: tpmsc`；
   跨站请求无法在不触发 CORS 预检的情况下携带自定义头。
5. **备份格式显式化**：`.tsb v2` 带 manifest、逐部件 SHA-256 与 `key_exportable`，
   把「私钥不可导出」变成数据而不是口头约定。

## 5. 构建与部署

```bash
# 依赖
npm ci
npm run build -w @tpmsc/web
node scripts/prepare-ui.mjs          # web/dist → core/ui/dist（go:embed）

# 核心库与 CLI
cd core && go test ./... && go build ./cmd/tpmsc

# 桌面端（Windows 可 CGO_ENABLED=0）
cd desktop/wails && go build -tags desktop -o ../dist/TPMSmartCard .

# Worker
npm run test -w @tpmsc/worker
cd worker && npx wrangler d1 migrations apply tpmsc --remote && npx wrangler deploy
```

CI：`.github/workflows/build-desktop-v2.yml`（五条平台线）、`.github/workflows/deploy-worker.yml`。
旧的 Python 流水线保留到 P2 验收。

## 6. 扩展新平台

1. 新建 `platform/<os>` 包，实现 `platform.Slot`；
2. 在 `platform/factory/factory_<os>.go` 里注册；
3. 在 `Capability` 里如实上报支持项；
4. 补 `go build -tags desktop` 的交叉编译检查。

前端零改动：页面只读 `/api/desktop/*` 与 `Capability`。
