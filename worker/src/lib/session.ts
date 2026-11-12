import { fromBase64Url, timingSafeEqual, toBase64Url, utf8 } from "./bytes";

/**
 * 无状态会话令牌：`tpmsc.v1.<base64url(payload)>.<base64url(HMAC)>`
 *
 * 同时兼容 PikaTestCert 的 `cardadm.v1` 前缀（只校验签名与结构，便于老管理脚本继续使用）。
 * 签名密钥来自 SESSION_SECRET（未配置时回退 CARD_ADMIN_PASSWORD），
 * 因此改口令会让所有旧会话立即失效。
 */
const PREFIXES = ["tpmsc.v1", "cardadm.v1"] as const;

export interface SessionPayload {
  /** 用户 ID（bootstrap 用户为 `bootstrap`） */
  sub: string;
  /** 会话 ID，对应 D1 sessions.id，可单点吊销 */
  sid: string;
  /** 签发时间（秒） */
  iat: number;
  /** 过期时间（秒） */
  exp: number;
}

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", utf8(secret), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
    "verify",
  ]);
}

async function sign(secret: string, data: string): Promise<Uint8Array> {
  const key = await hmacKey(secret);
  const mac = await crypto.subtle.sign("HMAC", key, utf8(data));
  return new Uint8Array(mac);
}

function encodePayload(payload: SessionPayload): string {
  return toBase64Url(utf8(JSON.stringify(payload)));
}

export async function createSessionToken(
  secret: string,
  payload: SessionPayload,
): Promise<string> {
  const body = encodePayload(payload);
  const signature = await sign(secret, body);
  return `${PREFIXES[0]}.${body}.${toBase64Url(signature)}`;
}

export interface VerifiedSession extends SessionPayload {
  prefix: string;
}

export async function verifySessionToken(
  secret: string,
  token: string,
): Promise<VerifiedSession | null> {
  // 前缀本身含点（tpmsc.v1），因此从右往左取签名与载荷，剩下的整体才是前缀
  const parts = token.split(".");
  if (parts.length < 4) return null;
  const signature = parts[parts.length - 1];
  const body = parts[parts.length - 2];
  const prefix = parts.slice(0, -2).join(".");
  if (!PREFIXES.includes(prefix as (typeof PREFIXES)[number])) return null;
  const expected = await sign(secret, body);
  const actual = fromBase64Url(signature);
  if (!timingSafeEqual(actual, expected)) return null;
  let payload: SessionPayload;
  try {
    payload = JSON.parse(new TextDecoder().decode(fromBase64Url(body))) as SessionPayload;
  } catch {
    return null;
  }
  if (!payload?.sub || !payload?.sid || !Number.isFinite(payload.exp)) return null;
  if (payload.exp * 1000 <= Date.now()) return null;
  return { ...payload, prefix };
}

/** 剩余秒数，用于前端展示「会话即将过期」 */
export function sessionSecondsLeft(payload: SessionPayload): number {
  return Math.max(0, payload.exp - Math.floor(Date.now() / 1000));
}
