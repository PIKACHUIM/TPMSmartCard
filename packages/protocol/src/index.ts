/**
 * @tpmsc/protocol —— 桌面端、管理台与 Worker 共用的协议常量与类型。
 *
 * 这里只放「跨端必须一致」的东西：路径、权限码、角色、错误码、投递契约。
 * 密码学实现不在此处（Worker 用 WebCrypto，Go 用 crypto/*），但两边的
 * 规范化规则与派生参数必须与 `docs/protocol.md` 描述一致。
 */

/** 云端 API 主版本前缀 */
export const API_PREFIX = '/api/v1' as const;

/** 智能卡证书分发路由（与 PikaTestCert / SmartCardWEB.py 逐字兼容） */
export const CARD_ROUTES = {
  getCert: '/card/get/cert',
  putCert: '/card/put/cert',
  getCode: '/card/get/code',
  putCode: '/card/put/code',
  codeStatus: '/card/code/status',
  status: '/card/status',
  webCert: '/card/web/cert',
  adminLogin: '/card/admin/login',
  adminSession: '/card/admin/session',
  adminList: '/card/admin/list',
  adminDelete: '/card/admin/delete',
} as const;

/** 旧 Flask 部署的路径别名，反向代理改写后可继续使用 */
export const LEGACY_CARD_ALIASES = {
  '/get/cert': CARD_ROUTES.getCert,
  '/put/cert': CARD_ROUTES.putCert,
  '/web/cert': CARD_ROUTES.webCert,
} as const;

/** 细粒度权限码；新增权限时必须同步 migrations 与 web 端菜单门控 */
export const PERMISSIONS = [
  'record:read',
  'record:write',
  'record:delete',
  'cert:deliver',
  'user:read',
  'user:write',
  'role:write',
  'audit:read',
  'policy:write',
  'apiclient:write',
] as const;

export type Permission = (typeof PERMISSIONS)[number];

/** 内置角色。自定义角色在 D1 中维护，命名与 OpenCertRepo 对齐 */
export const ROLE_PERMISSIONS: Record<string, Permission[]> = {
  super_admin: [...PERMISSIONS],
  admin: [
    'record:read',
    'record:write',
    'record:delete',
    'cert:deliver',
    'user:read',
    'user:write',
    'audit:read',
    'apiclient:write',
  ],
  operator: ['record:read', 'record:write', 'cert:deliver'],
  auditor: ['record:read', 'audit:read'],
  user: ['record:read'],
  readonly: ['record:read'],
};

export type RoleName = keyof typeof ROLE_PERMISSIONS;

/** 统一错误码；前端据此做文案映射，避免依赖后端中文提示 */
export const ERROR_CODES = {
  badRequest: 'bad_request',
  unauthorized: 'unauthorized',
  forbidden: 'forbidden',
  notFound: 'not_found',
  conflict: 'conflict',
  rateLimited: 'rate_limited',
  payloadTooLarge: 'payload_too_large',
  unsupported: 'unsupported',
  internal: 'internal_error',
} as const;

export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

/** 统一成功 / 失败包络（管理台 API） */
export interface ApiOk<T> {
  done: true;
  data: T;
}

export interface ApiErr {
  done: false;
  error: string;
  code: ErrorCode;
  detail?: string;
}

export type ApiResult<T> = ApiOk<T> | ApiErr;

/** 证书交付模式：传输密钥（v1）与取件码（v2） */
export type DeliveryMode = 'key' | 'code';

/**
 * 外部 CA 平台（OpenCertRepo server-card）推送的载荷。
 * 字段名与 `servers/internal/api/handler_delivery.go` 的 deliveredCert 保持一致，
 * 便于对方直接序列化后 POST 过来，不需要额外适配层。
 */
export interface DeliveredCertPayload {
  cert_pem: string;
  key_pem?: string;
  chain_pem?: string;
  pfx_base64?: string;
  algorithm?: string;
  serial_number?: string;
  common_name?: string;
  not_before?: string;
  not_after?: string;
  revoked?: boolean;
  sans?: string[];
}

export interface DeliveryRequest {
  mode: DeliveryMode;
  target: {
    /** mode=key 时必填：客户端 Base64(32 字节 X25519 公钥) */
    pubkey?: string;
    /** mode=code 时必填：平台生成或自定义取件码 */
    code?: string;
  };
  payload: DeliveredCertPayload;
  /** 有效期（秒），0 表示永久；上限 90 天 */
  ttl?: number;
  /** 允许取回次数，1~100 */
  max_uses?: number;
  label?: string;
}

export interface DeliveryResponse {
  id: string;
  mode: DeliveryMode;
  /** 仅 mode=code 且由平台生成时返回一次，后续不可再取 */
  code?: string;
  expires_at: string | null;
  max_uses: number;
}

/** 管理台记录列表的行结构 */
export interface RecordRow {
  id: string;
  mode: DeliveryMode;
  label: string | null;
  fingerprint: string;
  common_name: string | null;
  serial_number: string | null;
  source: 'inline' | 'openrepo' | 'manual';
  used: number;
  max_uses: number;
  created_at: string;
  expires_at: string | null;
  state: 'active' | 'exhausted' | 'expired' | 'revoked';
}

/** 审计日志行 */
export interface AuditRow {
  id: number;
  actor: string;
  action: string;
  target: string | null;
  result: 'ok' | 'deny' | 'error';
  ip: string | null;
  user_agent: string | null;
  detail: string | null;
  created_at: string;
}
