import type { Env } from "../env";

/**
 * 运行时配置的统一解析入口。
 *
 * 所有数值都钳制在安全区间内：配置写错不应该让服务变成「永不过期」或
 * 「无限次下发」这种危险状态，因此越界一律回落到默认值而不是原样放大。
 */
export interface Settings {
  allowAnonymous: boolean;
  ttlSeconds: number;
  codeTtlSeconds: number;
  codeUses: number;
  codeIterations: number;
  maxBytes: number;
  sessionSeconds: number;
  loginMaxFailures: number;
  passwordIterations: number;
  codePepper: string;
  sessionSecret: string;
  deliveryClientId: string;
}

const DAY = 24 * 60 * 60;

function int(value: string | undefined, fallback: number, min: number, max: number): number {
  const n = Number.parseInt((value ?? "").trim(), 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(Math.max(n, min), max);
}

function flag(value: string | undefined, fallback: boolean): boolean {
  const v = (value ?? "").trim().toLowerCase();
  if (!v) return fallback;
  return !(v === "0" || v === "false" || v === "no" || v === "off");
}

export function settings(env: Env): Settings {
  const sessionSecret =
    (env.SESSION_SECRET ?? "").trim() ||
    (env.CARD_ADMIN_PASSWORD ?? "").trim() ||
    "tpmsc-dev-session-secret-please-change";
  return {
    allowAnonymous: flag(env.CARD_ALLOW_ANONYMOUS, false),
    // 0 表示永不过期，用 0 作为下界
    ttlSeconds: int(env.CARD_TTL_SECONDS, 7 * DAY, 0, 90 * DAY),
    codeTtlSeconds: int(env.CARD_CODE_TTL_SECONDS, DAY, 0, 90 * DAY),
    codeUses: int(env.CARD_CODE_USES, 1, 1, 100),
    codeIterations: int(env.CARD_CODE_ITERATIONS, 100_000, 10_000, 1_000_000),
    maxBytes: int(env.CARD_MAX_BYTES, 8 * 1024 * 1024, 1024, 32 * 1024 * 1024),
    sessionSeconds: int(env.CARD_ADMIN_SESSION_SECONDS, 12 * 60 * 60, 300, 7 * DAY),
    loginMaxFailures: int(env.CARD_LOGIN_MAX_FAILURES, 5, 1, 100),
    passwordIterations: int(env.PBKDF2_ITERATIONS, 100_000, 10_000, 1_000_000),
    codePepper:
      (env.CARD_CODE_PEPPER ?? "").trim() ||
      (env.CARD_MASTER_KEY ?? "").trim() ||
      "tpmsc-default-code-pepper",
    sessionSecret,
    deliveryClientId: (env.DELIVERY_CLIENT_ID ?? "").trim() || "opencert",
  };
}

/** 引导管理员（未建任何用户时可用 CARD_ADMIN_PASSWORD 登录） */
export function bootstrapPassword(env: Env): string {
  return (env.CARD_ADMIN_PASSWORD ?? "").trim();
}

/** 旧版静态令牌 */
export function legacyAdminToken(env: Env): string {
  return (env.CARD_ADMIN_TOKEN ?? "").trim();
}
