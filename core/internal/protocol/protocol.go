// Package protocol 定义与 Worker / 前端共享的常量。
//
// 与 packages/protocol/src/index.ts 一一对应；改动任何一边都必须同步另一边，
// 并在 docs/protocol.md 记录原因。
package protocol

// Version 是核心库与本地 API 的版本（与 Module/Version.py 的语义一致）。
const Version = "2.0.0"

// API 前缀
const (
	APIPrefix = "/api/v1"
	Desktop   = APIPrefix + "/desktop"
)

// 云端证书分发路径（与 PikaTestCert / SmartCardWEB.py 兼容）
const (
	PathGetCertByKey  = "/card/get/cert"
	PathGetCertByCode = "/card/get/code"
	PathPutCert       = "/card/put/cert"
	PathCodeStatus    = "/card/code/status"
	PathWebCert       = "/card/web/cert"
)

// 旧部署的路径别名
const (
	LegacyGetCert = "/get/cert"
	LegacyPutCert = "/put/cert"
)

// 权限码（与 Worker D1 中的 permission_code 一致）
const (
	PermRecordRead   = "record:read"
	PermRecordWrite  = "record:write"
	PermRecordDelete = "record:delete"
	PermCertDeliver  = "cert:deliver"
	PermUserRead     = "user:read"
	PermUserWrite    = "user:write"
	PermRoleWrite    = "role:write"
	PermAuditRead    = "audit:read"
	PermPolicyWrite  = "policy:write"
	PermAPIClient    = "apiclient:write"
)

// 错误码
const (
	ErrBadRequest = "bad_request"
	ErrUnauth     = "unauthorized"
	ErrForbidden  = "forbidden"
	ErrNotFound   = "not_found"
	ErrConflict   = "conflict"
	ErrRateLimit  = "rate_limited"
	ErrTooLarge   = "payload_too_large"
	ErrInternal   = "internal_error"
)
