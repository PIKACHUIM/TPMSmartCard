import type { Env } from "../env";
import type { DeliveryRow } from "../types";
import type { Settings } from "./settings";
import { fromBase64, sha256Hex, toBase64, utf8 } from "./bytes";
import {
  codeFingerprint,
  formatCode,
  generateCode,
  newSalt,
  normalizeCode,
  validateCustomCode,
} from "./card-code";
import { putVault, sealForCode, sealForPubkey, vaultKeyV1, vaultKeyV2 } from "./card-vault";
import { newId } from "./db";
import { isoFromSeconds, nowIso } from "./time";

/**
 * 下发记录创建：把「接收到的证书材料」变成一条 KV 密文 + 一条 D1 记录。
 *
 * 两种模式共用同一个入口，区别只在加密方式与明文内容：
 *   key  → 明文是 PFX 字节；pfxkey 单独存 KV（兼容旧客户端的响应结构）
 *   code → 明文是 JSON（含 pfx 与 pfxkey，或 PEM 组合）；服务端不保留明文口令
 */
export interface CreateDeliveryInput {
  mode: "key" | "code";
  pubkey?: string;
  code?: string;
  /** PKCS#12 原始字节（优先使用） */
  pfx?: Uint8Array;
  /** 没有 PFX 时的 PEM 组合（来自 OpenCertRepo deliveredCert） */
  pem?: { certPem: string; keyPem?: string; chainPem?: string };
  pfxKey?: string;
  label?: string;
  commonName?: string;
  serialNumber?: string;
  algorithm?: string;
  ttlSeconds?: number;
  maxUses?: number;
  source: "inline" | "openrepo" | "manual";
  createdBy?: string | null;
  idempotencyKey?: string | null;
}

export interface CreatedDelivery {
  row: DeliveryRow;
  /** 仅 code 模式且由服务端生成时返回（只返回一次） */
  code?: string;
  sealed: Record<string, unknown>;
}

export async function createDelivery(
  env: Env,
  cfg: Settings,
  input: CreateDeliveryInput,
): Promise<CreatedDelivery> {
  const ttl = clamp(input.ttlSeconds ?? (input.mode === "code" ? cfg.codeTtlSeconds : cfg.ttlSeconds), 0, 90 * 24 * 3600);
  const maxUses = clamp(input.maxUses ?? (input.mode === "code" ? cfg.codeUses : 1000), 1, 1000);
  const id = newId("dlv");
  const createdAt = nowIso();
  const expiresAt = ttl > 0 ? isoFromSeconds(ttl) : null;

  if (input.mode === "key") {
    const pubkey = (input.pubkey ?? "").trim();
    if (!pubkey) throw new DeliveryError("bad_request", "缺少传输公钥 pubkey");
    if (input.pfx) {
      const sealed = await sealForPubkey(pubkey, input.pfx);
      const kvKey = await vaultKeyV1(pubkey);
      await putVault(
        env,
        kvKey,
        {
          v: 1,
          createdAt,
          vaults: sealed.vaults,
          pubkey: sealed.pubkey,
          pfxkey: input.pfxKey ?? "",
          label: input.label,
          id,
          contains: "pfx",
        },
        ttl,
      );
      const row = await insertRow(env, {
        id,
        mode: "key",
        fingerprint: (await sha256Hex(pubkey)).slice(0, 16),
        kvKey,
        label: input.label ?? null,
        commonName: input.commonName ?? null,
        serialNumber: input.serialNumber ?? null,
        algorithm: input.algorithm ?? null,
        source: input.source,
        maxUses,
        ttl,
        createdAt,
        expiresAt,
        createdBy: input.createdBy ?? null,
        idempotencyKey: input.idempotencyKey ?? null,
      });
      return { row, sealed: sealed as unknown as Record<string, unknown> };
    }
    if (input.pem) {
      // 没有 PFX 时，把 PEM 组合直接作为密文载荷；新客户端可解，旧客户端会拿到明确错误
      const plaintext = utf8(
        JSON.stringify({
          v: 2,
          cert_pem: input.pem.certPem,
          key_pem: input.pem.keyPem ?? "",
          chain_pem: input.pem.chainPem ?? "",
          label: input.label ?? "",
        }),
      );
      const sealed = await sealForPubkey(pubkey, plaintext);
      const kvKey = await vaultKeyV1(pubkey);
      await putVault(
        env,
        kvKey,
        {
          v: 1,
          createdAt,
          vaults: sealed.vaults,
          pubkey: sealed.pubkey,
          pfxkey: "",
          label: input.label,
          id,
          contains: "pem",
        },
        ttl,
      );
      const row = await insertRow(env, {
        id,
        mode: "key",
        fingerprint: (await sha256Hex(pubkey)).slice(0, 16),
        kvKey,
        label: input.label ?? null,
        commonName: input.commonName ?? null,
        serialNumber: input.serialNumber ?? null,
        algorithm: input.algorithm ?? null,
        source: input.source,
        maxUses,
        ttl,
        createdAt,
        expiresAt,
        createdBy: input.createdBy ?? null,
        idempotencyKey: input.idempotencyKey ?? null,
      });
      return { row, sealed: sealed as unknown as Record<string, unknown> };
    }
    throw new DeliveryError("bad_request", "缺少 PFX 或证书材料");
  }

  // ---- 取件码模式 ----
  let code = (input.code ?? "").trim();
  let generated = false;
  if (!code) {
    code = generateCode();
    generated = true;
  } else {
    const check = validateCustomCode(code);
    if (!check.ok) throw new DeliveryError("bad_request", check.reason);
  }
  const normalized = normalizeCode(code);
  const salt = newSalt();
  const iterations = cfg.codeIterations;

  let plaintext: Uint8Array;
  if (input.pfx) {
    plaintext = utf8(
      JSON.stringify({
        v: 1,
        pfx: toBase64(input.pfx),
        pfxkey: input.pfxKey ?? "",
        label: input.label ?? "",
      }),
    );
  } else if (input.pem) {
    plaintext = utf8(
      JSON.stringify({
        v: 2,
        cert_pem: input.pem.certPem,
        key_pem: input.pem.keyPem ?? "",
        chain_pem: input.pem.chainPem ?? "",
        label: input.label ?? "",
      }),
    );
  } else {
    throw new DeliveryError("bad_request", "缺少 PFX 或证书材料");
  }

  const sealed = await sealForCode(normalized, plaintext, salt.bytes, iterations);
  const kvKey = await vaultKeyV2(normalized, cfg.codePepper);
  await putVault(
    env,
    kvKey,
    {
      v: 2,
      createdAt,
      vaults: sealed.vaults,
      salt: sealed.salt,
      iterations: sealed.iterations,
      kdf: sealed.kdf,
      label: input.label,
      id,
      contains: input.pfx ? "pfx" : "pem",
    },
    ttl,
  );

  const row = await insertRow(env, {
    id,
    mode: "code",
    fingerprint: (await codeFingerprint(normalized, cfg.codePepper)).slice(0, 16),
    kvKey,
    label: input.label ?? null,
    commonName: input.commonName ?? null,
    serialNumber: input.serialNumber ?? null,
    algorithm: input.algorithm ?? null,
    source: input.source,
    maxUses,
    ttl,
    createdAt,
    expiresAt,
    createdBy: input.createdBy ?? null,
    idempotencyKey: input.idempotencyKey ?? null,
  });

  return {
    row,
    code: generated ? formatCode(code) : undefined,
    sealed: sealed as unknown as Record<string, unknown>,
  };
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(Math.max(Math.floor(value), min), max);
}

interface InsertRowInput {
  id: string;
  mode: "key" | "code";
  fingerprint: string;
  kvKey: string;
  label: string | null;
  commonName: string | null;
  serialNumber: string | null;
  algorithm: string | null;
  source: "inline" | "openrepo" | "manual";
  maxUses: number;
  ttl: number;
  createdAt: string;
  expiresAt: string | null;
  createdBy: string | null;
  idempotencyKey: string | null;
}

async function insertRow(env: Env, input: InsertRowInput): Promise<DeliveryRow> {
  await env.DB.prepare(
    `INSERT INTO deliveries (id, mode, fingerprint, kv_key, label, common_name, serial_number,
      algorithm, source, used, max_uses, ttl_seconds, created_at, expires_at, revoked,
      created_by, idempotency_key)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, 0, ?10, ?11, ?12, ?13, 0, ?14, ?15)`,
  )
    .bind(
      input.id,
      input.mode,
      input.fingerprint,
      input.kvKey,
      input.label,
      input.commonName,
      input.serialNumber,
      input.algorithm,
      input.source,
      input.maxUses,
      input.ttl,
      input.createdAt,
      input.expiresAt,
      input.createdBy,
      input.idempotencyKey,
    )
    .run();

  const row = await env.DB.prepare("SELECT * FROM deliveries WHERE id = ?1").bind(input.id).first<DeliveryRow>();
  if (!row) throw new DeliveryError("internal_error", "记录写入失败");
  return row;
}

/** 业务错误：路由层统一映射成 4xx，避免把内部异常暴露给客户端 */
export class DeliveryError extends Error {
  readonly code: "bad_request" | "internal_error" | "conflict" | "not_found";
  constructor(code: "bad_request" | "internal_error" | "conflict" | "not_found", message: string) {
    super(message);
    this.code = code;
  }
}

/**
 * 记录指纹：v1 用传输公钥，v2 用 (pepper|取件码) 的哈希。
 * 生成与查询必须走同一个函数，否则会出现「上传成功但查询不到记录」。
 */
export async function deliveryFingerprint(
  mode: "key" | "code",
  value: string,
  pepper: string,
): Promise<string> {
  const hex =
    mode === "code"
      ? await codeFingerprint(normalizeCode(value), pepper)
      : await sha256Hex(value);
  return hex.slice(0, 16);
}

/** 校验 PFX 结构（DER 首字节 0x30）；误传 .crt/.pem 时给出可读错误 */
export function looksLikePkcs12(bytes: Uint8Array): boolean {
  return bytes.length > 4 && bytes[0] === 0x30;
}

export function decodePfxBase64(text: string | undefined): Uint8Array | null {
  if (!text) return null;
  try {
    const bytes = fromBase64(text);
    return bytes.length > 0 ? bytes : null;
  } catch {
    return null;
  }
}
