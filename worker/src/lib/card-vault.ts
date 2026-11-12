import type { Env } from "../env";
import { fromBase64, sha256Hex, toBase64, toHex, utf8 } from "./bytes";
import { deriveCodeKey, normalizeCode } from "./card-code";

/**
 * 证书密文存储层。
 *
 * 两种模式：
 *   v1 传输密钥：X25519(clientPub, serverPriv) → 共享密钥 → AES-256-CBC(零 IV)
 *   v2 取件码：  PBKDF2-SHA256(code, salt, iterations) → AES-256-CBC(零 IV)
 *
 * 两种模式的密文格式与 PikaTestCert / SmartCardWEB.py 完全一致：
 * AES-CBC + 16 字节零 IV + PKCS#7；WebCrypto 的 AES-CBC 本身就会做 PKCS#7 填充。
 */
const ZERO_IV = new Uint8Array(16);

/** Workers 的 X25519 WebCrypto 尚未进入标准 lib 类型，这里做一次窄化声明 */
interface X25519Subtle {
  generateKey(algorithm: { name: string }, extractable: boolean, usages: string[]): Promise<CryptoKeyPair>;
  importKey(
    format: string,
    keyData: BufferSource,
    algorithm: { name: string },
    extractable: boolean,
    usages: string[],
  ): Promise<CryptoKey>;
  deriveBits(algorithm: { name: string; public: CryptoKey }, key: CryptoKey, length: number): Promise<ArrayBuffer>;
  exportKey(format: string, key: CryptoKey): Promise<ArrayBuffer>;
}

function x25519(): X25519Subtle {
  return crypto.subtle as unknown as X25519Subtle;
}

async function aesCbcEncrypt(keyBytes: Uint8Array, plaintext: Uint8Array): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey("raw", keyBytes, { name: "AES-CBC" }, false, ["encrypt"]);
  const out = await crypto.subtle.encrypt({ name: "AES-CBC", iv: ZERO_IV }, key, plaintext);
  return new Uint8Array(out);
}

async function aesCbcDecrypt(keyBytes: Uint8Array, ciphertext: Uint8Array): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey("raw", keyBytes, { name: "AES-CBC" }, false, ["decrypt"]);
  const out = await crypto.subtle.decrypt({ name: "AES-CBC", iv: ZERO_IV }, key, ciphertext);
  return new Uint8Array(out);
}

export interface SealedV1 {
  vaults: string;
  pubkey: string;
}

/** v1：用客户端传输公钥加密，返回 Base64 密文与服务端临时公钥 */
export async function sealForPubkey(clientPubkeyBase64: string, plaintext: Uint8Array): Promise<SealedV1> {
  const clientRaw = fromBase64(clientPubkeyBase64);
  if (clientRaw.length !== 32) throw new Error("invalid x25519 public key length");
  const subtle = x25519();
  const pair = await subtle.generateKey({ name: "X25519" }, true, ["deriveBits"]);
  const clientKey = await subtle.importKey("raw", clientRaw, { name: "X25519" }, false, []);
  const shared = await subtle.deriveBits({ name: "X25519", public: clientKey }, pair.privateKey, 256);
  const serverPub = await subtle.exportKey("raw", pair.publicKey);
  const ciphertext = await aesCbcEncrypt(new Uint8Array(shared), plaintext);
  return { vaults: toBase64(ciphertext), pubkey: toBase64(new Uint8Array(serverPub)) };
}

/** v1 解密（仅测试与自检使用；生产不应把私钥交到服务端） */
export async function openWithPrivateKey(serverPubkeyBase64: string, clientPrivateKey: CryptoKey, vaultsBase64: string): Promise<Uint8Array> {
  const subtle = x25519();
  const serverKey = await subtle.importKey("raw", fromBase64(serverPubkeyBase64), { name: "X25519" }, false, []);
  const shared = await subtle.deriveBits({ name: "X25519", public: serverKey }, clientPrivateKey, 256);
  return aesCbcDecrypt(new Uint8Array(shared), fromBase64(vaultsBase64));
}

export interface SealedV2 {
  vaults: string;
  salt: string;
  iterations: number;
  kdf: "PBKDF2-SHA256";
}

/** v2：用取件码派生的密钥加密 */
export async function sealForCode(
  code: string,
  plaintext: Uint8Array,
  salt: Uint8Array,
  iterations: number,
): Promise<SealedV2> {
  const key = await deriveCodeKey(code, salt, iterations);
  const ciphertext = await aesCbcEncrypt(key, plaintext);
  return {
    vaults: toBase64(ciphertext),
    salt: toBase64(salt),
    iterations,
    kdf: "PBKDF2-SHA256",
  };
}

/** v2 解密（测试与排障用） */
export async function openWithCode(
  code: string,
  sealed: SealedV2,
): Promise<Uint8Array> {
  const key = await deriveCodeKey(code, fromBase64(sealed.salt), sealed.iterations);
  return aesCbcDecrypt(key, fromBase64(sealed.vaults));
}

/** v1 KV 键：SHA-256(传输公钥 Base64)，与旧实现一致，避免客户端需要知道新键 */
export async function vaultKeyV1(clientPubkeyBase64: string): Promise<string> {
  return `card:v1:${await sha256Hex(clientPubkeyBase64)}`;
}

/** v2 KV 键：SHA-256(pepper|规范化取件码)，没有 pepper 无法枚举 */
export async function vaultKeyV2(code: string, pepper: string): Promise<string> {
  return `card:v2:code:${await sha256Hex(`${pepper}|${normalizeCode(code)}`)}`;
}

export interface VaultRecord {
  v: 1 | 2;
  createdAt: string;
  label?: string;
  /** v1 字段 */
  vaults?: string;
  pubkey?: string;
  pfxkey?: string;
  /** v2 字段 */
  salt?: string;
  iterations?: number;
  kdf?: string;
  /** 记录归属（D1 deliveries.id） */
  id?: string;
  /** 明文载荷是 PFX 还是 PEM 组合（deliveredCert） */
  contains?: "pfx" | "pem";
}

function kvOptions(ttlSeconds: number): KVNamespacePutOptions | undefined {
  if (ttlSeconds <= 0) return undefined;
  // KV 要求 expirationTtl >= 60
  return { expirationTtl: Math.max(60, Math.floor(ttlSeconds)) };
}

export async function putVault(
  env: Env,
  key: string,
  record: VaultRecord,
  ttlSeconds: number,
): Promise<void> {
  await env.CARD_KV.put(key, JSON.stringify(record), kvOptions(ttlSeconds));
}

export async function loadVault(env: Env, key: string): Promise<VaultRecord | null> {
  const raw = await env.CARD_KV.get(key, "text");
  if (!raw) return null;
  try {
    return JSON.parse(raw) as VaultRecord;
  } catch {
    return null;
  }
}

export async function deleteVault(env: Env, key: string): Promise<void> {
  await env.CARD_KV.delete(key);
}

/** 存储层指纹展示（不泄露公钥/取件码原文） */
export async function shortFingerprint(input: string): Promise<string> {
  return (await sha256Hex(input)).slice(0, 16);
}
