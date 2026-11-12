import { CODE_ALPHABET, fromBase64, randomAscii, randomBytes, sha256Hex, toBase64, utf8 } from "./bytes";

/**
 * 取件码（自协商）模式的规范化与派生。
 *
 * 必须与 Python `Module/Cryptography.py` 的 `normalize_code` / `code_key`
 * 逐字节一致，否则旧客户端解不开新服务端加密的载荷：
 *   1. 去掉一切非 [0-9A-Z] 字符（大小写、分隔符都不敏感）
 *   2. O → 0、I → 1、L → 1
 *   3. PBKDF2-SHA256(规范化后的码, salt, iterations) → 32 字节
 */
export function normalizeCode(input: string | null | undefined): string {
  const upper = String(input ?? "").toUpperCase();
  return upper
    .replace(/[^0-9A-Z]/g, "")
    .replace(/O/g, "0")
    .replace(/I/g, "1")
    .replace(/L/g, "1");
}

/** 展示形式：每 4 位一组 */
export function formatCode(code: string): string {
  const normalized = normalizeCode(code);
  return normalized.match(/.{1,4}/g)?.join("-") ?? normalized;
}

/** 随机取件码：16 位，字母表已剔除 I/L/O，约 80.7 bit 熵 */
export function generateCode(): string {
  return formatCode(randomAscii(16));
}

/**
 * 自定义取件码强度校验。
 *
 * 取件码是唯一保护 PFX 的密钥，全同字符或 ABAB 循环等价于没有保护，
 * 因此要求至少 8 个不同字符（与 PikaTestCert 的 CODE_MIN_DISTINCT 对齐）。
 */
export const CODE_MIN_DISTINCT = 8;

export function validateCustomCode(code: string): { ok: true } | { ok: false; reason: string } {
  const normalized = normalizeCode(code);
  if (normalized.length < 8) return { ok: false, reason: "取件码至少 8 位" };
  if (normalized.length > 32) return { ok: false, reason: "取件码最多 32 位" };
  const distinct = new Set(normalized.split("")).size;
  if (distinct < CODE_MIN_DISTINCT) {
    return { ok: false, reason: `取件码强度不足：至少需要 ${CODE_MIN_DISTINCT} 个不同字符` };
  }
  return { ok: true };
}

/** 取件码指纹：服务端只保存它，不保存明文码 */
export async function codeFingerprint(code: string, pepper: string): Promise<string> {
  return sha256Hex(`${pepper}|${normalizeCode(code)}`);
}

/**
 * PBKDF2-HMAC-SHA256 派生 32 字节。
 * 与 `hashlib.pbkdf2_hmac("sha256", ...)` 完全一致（RFC 7914 §11 向量见单测）。
 */
export async function pbkdf2Sha256(
  secret: Uint8Array,
  salt: Uint8Array,
  iterations: number,
): Promise<Uint8Array> {
  const baseKey = await crypto.subtle.importKey("raw", secret, "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    baseKey,
    256,
  );
  return new Uint8Array(bits);
}

/** 取件码 → AES-256 密钥 */
export async function deriveCodeKey(
  code: string,
  salt: Uint8Array,
  iterations: number,
): Promise<Uint8Array> {
  return pbkdf2Sha256(utf8(normalizeCode(code)), salt, iterations);
}

/** 生成 PBKDF2 盐（16 字节）并返回 Base64，便于放进响应给客户端 */
export function newSalt(): { bytes: Uint8Array; base64: string } {
  const bytes = randomBytes(16);
  return { bytes, base64: toBase64(bytes) };
}

export function saltFromBase64(base64: string): Uint8Array {
  return fromBase64(base64);
}

export { CODE_ALPHABET };
