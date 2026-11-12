# 证书下发协议（v1 传输密钥 / v2 取件码）

> 定位：定义桌面端、Worker 与 OpenCertRepo 之间的**唯一契约**。
> 任何一侧改动都必须同时更新本文件与两侧的单测向量。
> 参考实现：`worker/src/lib/card-*.ts`（TypeScript）、`core/internal/crypto`（Go）、
> `Module/Cryptography.py`（v1 Python）。

## 1. 密码学原语

| 用途 | 参数 | 说明 |
|---|---|---|
| 取件码规范化 | 去非 `[0-9A-Z]`；`O→0`、`I→1`、`L→1`（顺序固定） | `"i-l-o"` → `"110"` |
| 取件码密钥 | `PBKDF2-HMAC-SHA256(code, salt, iterations, 32)` | 盐 16 字节；迭代次数随响应回传 |
| 对称加密 | `AES-256-CBC`，**16 字节零 IV**，PKCS#7 | 与 Python `Crypto.aes_encrypt` 逐字节一致 |
| 传输密钥 | X25519，原始 32 字节公钥（Base64） | 共享密钥直接作为 AES-256 密钥 |
| 会话令牌 | `HMAC-SHA256`，`tpmsc.v1.<b64url(payload)>.<b64url(mac)>` | 兼容 `cardadm.v1` 前缀 |
| 服务投递签名 | `HMAC-SHA256(secret, clientId|timestamp|nonce|sha256hex(body))` | 见 §5 |

### 1.1 金标向量

```
PBKDF2-HMAC-SHA256("password", "salt", 1, 32)
= 120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b

normalize_code("abcd-efgh jkmn/pqrs") = "ABCDEFGHJKMNPQRS"
normalize_code("OIL") = "011"
normalize_code("i-l-o") = "110"
```

Go 与 TypeScript 两侧都有对应单测；任何一侧失败即视为协议被破坏。

## 2. 取下证书

### 2.1 v1 传输密钥（兼容旧客户端）

```
客户端                                    Worker
  │ 生成临时 X25519 密钥对                    │
  │ POST /card/get/cert                      │
  │ body: pubkey=<Base64 公钥>               │
  │ ───────────────────────────────────────► │ 生成服务端临时密钥对
  │                                          │ shared = X25519(serverPriv, clientPub)
  │                                          │ vaults = AES-256-CBC(shared, PFX)
  │ ◄─────────────────────────────────────── │ {flag:true,data:{vaults,pubkey,pfxkey}}
  │ shared = X25519(clientPriv, serverPub)   │
  │ 解密 → 导入卡片                           │
```

- 参数可放在 query、urlencoded body、JSON body 或 **GET 的请求体**（旧客户端 `requests.get(url, data=...)`）。
- 未命中/过期/用尽：`{"flag": false, "data": null}`，HTTP 200。
- `pubkey` 必须是 32 字节；长度不符返回 `400` 与可读错误。

### 2.2 v2 取件码（自协商）

```
POST /card/get/code    code=XXXX-XXXX-XXXX-XXXX
→ {"flag":true,"data":{"vaults":"…","salt":"…","iterations":100000,"kdf":"PBKDF2-SHA256",
                       "label":"…","contains":"pfx","remaining":0}}
```

客户端本地派生：

```
key = PBKDF2-SHA256(normalize_code(code), salt, iterations, 32)
plaintext = AES-256-CBC-Decrypt(key, vaults)
```

明文有两种形态（`contains` 字段指示）：

```json
{ "v": 1, "pfx": "<base64 PKCS#12>", "pfxkey": "<PFX 口令>", "label": "…" }
{ "v": 2, "cert_pem": "…", "key_pem": "…", "chain_pem": "…", "label": "…" }
```

> 旧 Python 客户端只识别 `v:1`；`v:2` 是 OpenCertRepo 投递时的形态，由 Go 客户端处理。

### 2.3 上传

| 路径 | 形式 | 必填 |
|---|---|---|
| `POST /card/put/cert` | `multipart/form-data` | `pubkey` 或 `mode=code`、`vaults`、`pfxkey` |
| `POST /card/put/code` | 同上，等价 `mode=code` | `vaults`，`code` 可留空由平台生成 |
| 脚本调用 | `vaults_b64`（Base64 文本） | 与上同 |

响应：

```json
{"flag":true,"data":{"id":"dlv_…","mode":"code","code":"ABCD-EFGH-JKMN-PQRS",
                     "expires_at":"2026-11-13T02:14:00Z","max_uses":1}}
```

`code` **只在由平台生成且首次返回时出现**，之后无法再取回。

### 2.4 状态查询

`GET/POST /card/code/status?code=…` 返回 `used` / `max_uses` / `remaining` / `expires_at`，**不核销**。

## 3. 管理台 API

统一包络：

```json
{ "done": true,  "data": { } }
{ "done": false, "error": "可读中文", "code": "forbidden", "detail": "…" }
```

| 方法 | 路径 | 权限 |
|---|---|---|
| POST | `/api/v1/auth/login` | —（首次部署用 `CARD_ADMIN_PASSWORD` 引导） |
| POST | `/api/v1/auth/logout` | 登录 |
| GET | `/api/v1/auth/me` | 登录 |
| POST | `/api/v1/auth/password` | 登录 |
| GET | `/api/v1/users` | `user:read` |
| POST | `/api/v1/users` | `user:write` |
| PATCH | `/api/v1/users/:id` | `user:write` |
| POST | `/api/v1/users/:id/password` | `user:write` |
| GET | `/api/v1/roles` | `user:read` |
| POST | `/api/v1/roles` | `role:write` |
| GET | `/api/v1/records` | `record:read` |
| DELETE | `/api/v1/records/:id` | `record:delete` |
| GET | `/api/v1/audit` | `audit:read` |
| POST | `/api/v1/deliveries` | 服务间 HMAC |
| GET | `/api/health` | — |

会话令牌可放 `Authorization: Bearer`、`x-admin-token`、`?token=` 或 HttpOnly Cookie `tpmsc_session`。

## 4. 角色与权限

| 角色 | 权限 |
|---|---|
| `super_admin` | 全部 |
| `admin` | 记录读写删、下发、用户读写、审计、投递客户端 |
| `operator` | 记录读写、下发 |
| `auditor` | 记录读、审计读 |
| `user` | 记录读 |
| `readonly` | 记录读 |

权限码：`record:read/write/delete`、`cert:deliver`、`user:read/write`、`role:write`、`audit:read`、`policy:write`、`apiclient:write`。

## 5. OpenCertRepo 投递契约

`POST /api/v1/deliveries`

请求头：

```
X-Client-Id:  opencert
X-Timestamp:  1770000000            # 秒；±300s 窗口
X-Nonce:      <一次性随机串>
X-Signature:  <hex 或 base64url>    # HMAC-SHA256(secret, "clientId|timestamp|nonce|sha256hex(body)")
Idempotency-Key: <可选，重复推送返回同一条记录>
```

请求体（字段与 OpenCertRepo `deliveredCert` 对齐）：

```jsonc
{
  "mode": "code",
  "target": { "code": "ABCD-EFGH-JKMN-PQRS" },   // 留空则由平台生成
  "payload": {
    "cert_pem": "-----BEGIN CERTIFICATE-----…",
    "key_pem": "…",
    "chain_pem": "…",
    "pfx_base64": "…",
    "algorithm": "ECDSA-P256",
    "serial_number": "1a2b",
    "common_name": "CN=Demo",
    "not_before": "2026-01-01T00:00:00Z",
    "not_after": "2027-01-01T00:00:00Z",
    "revoked": false,
    "sans": ["demo.local"]
  },
  "ttl": 86400,
  "max_uses": 1,
  "label": "张三-笔记本"
}
```

`pfx_base64` 优先：有 PFX 时按 `v:1` 加密；只有 PEM 时按 `v:2` 加密。

响应：`201`，`data.code` 仅在首次生成时返回；重复 `Idempotency-Key` 返回 `200` 且不再返回取件码。

## 6. 本地 API（桌面端）

| 路径 | 说明 |
|---|---|
| `GET /api/health` | 平台、TPM/SE、读卡器、能力矩阵 |
| `GET /api/v1/desktop/cards` | 卡片列表（含 warnings） |
| `POST /api/v1/desktop/cards` | 建卡 `{name,pin,puk}` |
| `DELETE /api/v1/desktop/cards/{id}` | 删卡 |
| `POST /api/v1/desktop/cards/{id}/pin` | 改 PIN `{old_pin,new_pin}` |
| `GET /api/v1/desktop/certificates?card_id=` | 证书列表 |
| `GET /api/v1/desktop/backups` | 备份包列表（读取 manifest） |
| `POST /api/v1/desktop/backups` | 生成备份 `{card_id}` |
| `GET /api/v1/events` | SSE 长任务进度 |

写操作必须带 `X-Requested-With: tpmsc`（跨站页面无法在不触发预检的情况下伪造）。
可选 `TPMSC_LOCAL_TOKEN`，脚本用 `Authorization: Bearer` 或 `?token=`。

## 7. 兼容性检查清单

发布前逐项确认：

- [ ] `worker` 的 `card-code.test.ts` / `card-vault.test.ts` 全绿
- [ ] `core/internal/crypto` 的 RFC 7914 向量通过
- [ ] 用 v1 Python 客户端向新 Worker 上传 + 取回一次（不改代码）
- [ ] 用 Go 客户端以取件码取回一次，`pfxkey` 正确
- [ ] **GET 带请求体**的旧写法仍可用
- [ ] 旧路径 `/get/cert`、`/put/cert`、`/web/cert` 仍可用
