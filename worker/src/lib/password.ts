import { fromBase64, randomBytes, timingSafeEqual, toBase64, utf8 } from "./bytes";

/**
 * 口令哈希。
 *
 * Workers 的 WebCrypto 只有 PBKDF2（没有 Argon2id / scrypt），因此采用
 * PBKDF2-SHA256 + 16 字节随机盐，参数随行存储（`algo` / `iterations`），
 * 后续可平滑升级到 WASM 版 Argon2id 而不影响老用户登录。
 *
 * 注意 CPU 预算：100k 次迭代在免费套餐（10ms CPU）上可能超时，
 * 生产建议 Workers Paid，或把 PBKDF2_ITERATIONS 调到 50000。
 */
export interface PasswordRecord {
  hash: string;
  salt: string;
  algo: string;
  iterations: number;
}

export const DEFAULT_ALGO = "pbkdf2-sha256";

async function derive(password: string, salt: Uint8Array, iterations: number): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey("raw", utf8(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    key,
    256,
  );
  return new Uint8Array(bits);
}

export async function hashPassword(password: string, iterations: number): Promise<PasswordRecord> {
  const salt = randomBytes(16);
  const hash = await derive(password, salt, iterations);
  return {
    hash: toBase64(hash),
    salt: toBase64(salt),
    algo: DEFAULT_ALGO,
    iterations,
  };
}

export async function verifyPassword(password: string, record: PasswordRecord): Promise<boolean> {
  if (record.algo !== DEFAULT_ALGO) return false;
  const expected = fromBase64(record.hash);
  const actual = await derive(password, fromBase64(record.salt), record.iterations);
  return timingSafeEqual(actual, expected);
}

/** 口令强度：至少 10 位，且不能是纯数字（引导管理员口令也要过这一关） */
export function checkPasswordStrength(password: string): { ok: true } | { ok: false; reason: string } {
  if (password.length < 10) return { ok: false, reason: "口令至少 10 位" };
  if (password.length > 256) return { ok: false, reason: "口令过长" };
  if (/^\d+$/.test(password)) return { ok: false, reason: "口令不能是纯数字" };
  return { ok: true };
}
