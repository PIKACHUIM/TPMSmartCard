/** 认证上下文：会话、静态令牌、引导口令三种来源统一成一种形状 */
export interface AuthUser {
  id: string;
  username: string;
  displayName: string | null;
  roles: string[];
  permissions: string[];
  mustChangePassword: boolean;
}

export interface AuthContext {
  authenticated: boolean;
  via?: "session" | "token" | "bootstrap";
  user?: AuthUser;
  expiresAt?: string;
}

export const ANONYMOUS: AuthContext = { authenticated: false };

/** 一条下发记录（D1 deliveries 行） */
export interface DeliveryRow {
  id: string;
  mode: "key" | "code";
  fingerprint: string;
  kv_key: string;
  label: string | null;
  common_name: string | null;
  serial_number: string | null;
  algorithm: string | null;
  source: "inline" | "openrepo" | "manual";
  used: number;
  max_uses: number;
  ttl_seconds: number;
  created_at: string;
  expires_at: string | null;
  revoked: number;
  created_by: string | null;
  idempotency_key: string | null;
}
