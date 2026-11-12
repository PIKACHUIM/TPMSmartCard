import type { Context, Hono } from "hono";
import type { AppEnv } from "../env";
import { API_PREFIX, type DeliveryRequest } from "@tpmsc/protocol";
import { fromBase64Url, fromHex, sha256Hex, timingSafeEqual, toHex, toBase64, utf8 } from "../lib/bytes";
import { createDelivery, DeliveryError, decodePfxBase64 } from "../lib/delivery";
import { settings } from "../lib/settings";
import { auditFromContext } from "../lib/audit";
import { badRequest, fail, ok, serverError, unauthorized } from "../lib/http";
import { getRecord } from "../lib/records";
import { toRecordRow } from "../lib/records";

/**
 * 外部 CA 平台（OpenCertRepo server-card）→ Worker 的证书投递。
 *
 * 鉴权不走用户会话，而是服务间 HMAC：
 *   X-Client-Id / X-Timestamp / X-Nonce / X-Signature
 *   签名内容 = `clientId|timestamp|nonce|sha256hex(body)`
 * 时间戳窗口 ±300s，nonce 落 D1 去重，Idempotency-Key 保证重复推送不产生重复记录。
 */
const TIMESTAMP_WINDOW_SECONDS = 300;

export function mountDeliveryRoutes(app: Hono<AppEnv>): void {
  app.post(`${API_PREFIX}/deliveries`, handleCreateDelivery);
  app.get(`${API_PREFIX}/deliveries/:id`, handleGetDelivery);
}

async function handleCreateDelivery(c: Context<AppEnv>) {
  const secret = (c.env.DELIVERY_CLIENT_SECRET ?? "").trim();
  if (!secret) {
    return fail(c, 503, "unsupported", "投递接口未启用：请先配置 DELIVERY_CLIENT_SECRET");
  }

  const bodyText = await c.req.text();
  const verified = await verifySignature(c, secret, bodyText);
  if (!verified.ok) {
    await auditFromContext(c, {
      actor: c.req.header("x-client-id") ?? "unknown",
      action: "delivery.auth",
      result: "deny",
      detail: verified.reason,
    });
    return unauthorized(c, verified.reason);
  }

  let payload: DeliveryRequest;
  try {
    payload = JSON.parse(bodyText) as DeliveryRequest;
  } catch {
    return badRequest(c, "请求体不是合法 JSON");
  }
  if (!payload?.mode || !payload?.target || !payload?.payload) {
    return badRequest(c, "缺少 mode / target / payload");
  }
  if (payload.mode === "key" && !payload.target.pubkey) return badRequest(c, "mode=key 时缺少 target.pubkey");
  if (payload.mode === "code" && payload.target.pubkey) return badRequest(c, "mode=code 时不应传 target.pubkey");

  // 幂等：同一个 Idempotency-Key 直接返回已有记录（不再返回取件码）
  const idempotencyKey = (c.req.header("idempotency-key") ?? "").trim();
  if (idempotencyKey) {
    const existing = await c.env.DB.prepare(
      "SELECT id FROM deliveries WHERE idempotency_key = ?1",
    )
      .bind(idempotencyKey)
      .first<{ id: string }>();
    if (existing) {
      const row = await getRecord(c.env, existing.id);
      if (row) {
        return ok(
          c,
          {
            id: row.id,
            mode: row.mode,
            expires_at: row.expires_at,
            max_uses: row.max_uses,
            idempotent: true,
          },
          200,
        );
      }
    }
  }

  const cfg = settings(c.env);
  const pfx = decodePfxBase64(payload.payload.pfx_base64) ?? undefined;
  const pem =
    payload.payload.cert_pem
      ? {
          certPem: payload.payload.cert_pem,
          keyPem: payload.payload.key_pem,
          chainPem: payload.payload.chain_pem,
        }
      : undefined;

  try {
    const created = await createDelivery(c.env, cfg, {
      mode: payload.mode,
      pubkey: payload.mode === "key" ? payload.target.pubkey : undefined,
      code: payload.mode === "code" ? payload.target.code : undefined,
      pfx,
      pem,
      pfxKey: undefined,
      label: payload.label,
      commonName: payload.payload.common_name,
      serialNumber: payload.payload.serial_number,
      algorithm: payload.payload.algorithm,
      ttlSeconds: payload.ttl,
      maxUses: payload.max_uses,
      source: "openrepo",
      createdBy: `service:${verified.clientId}`,
      idempotencyKey: idempotencyKey || null,
    });

    await auditFromContext(c, {
      actor: `service:${verified.clientId}`,
      action: `delivery.${payload.mode}`,
      target: created.row.id,
      result: "ok",
      detail: `cn=${payload.payload.common_name ?? "-"}`,
    });

    return ok(
      c,
      {
        id: created.row.id,
        mode: payload.mode,
        code: created.code,
        expires_at: created.row.expires_at,
        max_uses: created.row.max_uses,
      },
      201,
    );
  } catch (err) {
    if (err instanceof DeliveryError) {
      return badRequest(c, err.message);
    }
    console.error("delivery failed", err);
    return serverError(c, "投递处理失败");
  }
}

async function handleGetDelivery(c: Context<AppEnv>) {
  const auth = c.get("auth");
  if (!auth?.authenticated || !auth.user?.permissions.includes("record:read")) {
    return unauthorized(c, "需要管理员权限");
  }
  const row = await getRecord(c.env, c.req.param("id") ?? "");
  if (!row) return badRequest(c, "记录不存在");
  return ok(c, toRecordRow(row));
}

interface VerifyResult {
  ok: boolean;
  reason: string;
  clientId: string;
}

async function verifySignature(
  c: Context<AppEnv>,
  secret: string,
  bodyText: string,
): Promise<VerifyResult> {
  const cfg = settings(c.env);
  const clientId = (c.req.header("x-client-id") ?? "").trim();
  const timestamp = (c.req.header("x-timestamp") ?? "").trim();
  const nonce = (c.req.header("x-nonce") ?? "").trim();
  const signature = (c.req.header("x-signature") ?? "").trim();

  if (!clientId || !timestamp || !nonce || !signature) {
    return { ok: false, reason: "缺少签名头", clientId };
  }
  if (clientId !== cfg.deliveryClientId) {
    return { ok: false, reason: "未知的投递客户端", clientId };
  }
  const ts = Number.parseInt(timestamp, 10);
  if (!Number.isFinite(ts) || Math.abs(Date.now() / 1000 - ts) > TIMESTAMP_WINDOW_SECONDS) {
    return { ok: false, reason: "时间戳超出允许窗口", clientId };
  }

  const bodyHash = await sha256Hex(bodyText);
  const message = `${clientId}|${timestamp}|${nonce}|${bodyHash}`;
  const expected = toHex(await hmacSha256(secret, message));
  const providedHex = /^[0-9a-fA-F]{64}$/.test(signature) ? signature.toLowerCase() : "";
  const provided = providedHex ? fromHex(providedHex) : fromBase64Url(signature);
  if (!timingSafeEqual(provided, fromHex(expected))) {
    return { ok: false, reason: "签名校验失败", clientId };
  }

  // nonce 去重（D1 主键冲突即重放）
  try {
    await c.env.DB.prepare("INSERT INTO nonces (nonce, expires_at) VALUES (?1, ?2)")
      .bind(nonce, Math.floor(Date.now() / 1000) + TIMESTAMP_WINDOW_SECONDS * 2)
      .run();
  } catch {
    return { ok: false, reason: "请求已被使用（nonce 重放）", clientId };
  }

  return { ok: true, reason: "", clientId };
}

async function hmacSha256(secret: string, message: string): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey("raw", utf8(secret), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
  ]);
  const mac = await crypto.subtle.sign("HMAC", key, utf8(message));
  return new Uint8Array(mac);
}

void toBase64;
