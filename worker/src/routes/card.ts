import type { Context, Hono } from "hono";
import type { AppEnv } from "../env";
import { CARD_ROUTES, LEGACY_CARD_ALIASES } from "@tpmsc/protocol";
import { normalizeCode } from "../lib/card-code";
import { loadVault, vaultKeyV1, vaultKeyV2 } from "../lib/card-vault";
import {
  createDelivery,
  decodePfxBase64,
  DeliveryError,
  deliveryFingerprint,
  looksLikePkcs12,
} from "../lib/delivery";
import { hasPermission, resolveAuth } from "../lib/rbac";
import { auditFromContext } from "../lib/audit";
import { forbidden, serverError, unauthorized, collectParams } from "../lib/http";
import { consumeUse, getRecordByFingerprint } from "../lib/records";
import { settings, type Settings } from "../lib/settings";
import { renderUploadPage } from "../lib/page";

/**
 * 智能卡证书分发：与 PikaTestCert / SmartCardWEB.py 保持逐字段兼容。
 *
 * 兼容性红线：
 *   - 响应必须是 `{flag: true, data: ...}` / `{flag: false, data: null}`
 *   - 参数可放 query、urlencoded body、JSON body 或 GET 的请求体
 *   - v1 返回 {vaults, pubkey, pfxkey}，v2 返回 {vaults, salt, iterations, kdf}
 *   - 取回接口凭「传输公钥 / 取件码」授权，不要求登录
 */
export function mountCardRoutes(app: Hono<AppEnv>): void {
  app.get(CARD_ROUTES.getCert, handleGetCert);
  app.post(CARD_ROUTES.getCert, handleGetCert);
  app.get(CARD_ROUTES.getCode, handleGetCert);
  app.post(CARD_ROUTES.getCode, handleGetCert);
  app.post(CARD_ROUTES.putCert, handlePutCert);
  app.post(CARD_ROUTES.putCode, handlePutCert);
  app.get(CARD_ROUTES.status, handleStatus);
  app.post(CARD_ROUTES.status, handleStatus);
  app.get(CARD_ROUTES.codeStatus, handleStatus);
  app.post(CARD_ROUTES.codeStatus, handleStatus);
  app.get(CARD_ROUTES.webCert, handleUploadPage);

  app.get(LEGACY_CARD_ALIASES["/get/cert"], handleGetCert);
  app.post(LEGACY_CARD_ALIASES["/get/cert"], handleGetCert);
  app.post(LEGACY_CARD_ALIASES["/put/cert"], handlePutCert);
  app.get(LEGACY_CARD_ALIASES["/web/cert"], handleUploadPage);
}

type Ctx = Context<AppEnv>;

async function handleGetCert(c: Ctx) {
  const params = await collectParams(c);
  const pubkey = (params.get("pubkey") ?? c.req.header("x-pubkey") ?? "").trim();
  const rawCode = (params.get("code") ?? "").trim();
  const cfg = settings(c.env);

  if (!pubkey && !rawCode) return c.json({ flag: false, data: null });

  if (rawCode) {
    const normalized = normalizeCode(rawCode);
    const kvKey = await vaultKeyV2(normalized, cfg.codePepper);
    const fingerprint = await deliveryFingerprint("code", normalized, cfg.codePepper);
    const record = await getRecordByFingerprint(c.env, fingerprint);
    if (!record) return c.json({ flag: false, data: null });
    const vault = await loadVault(c.env, kvKey);
    if (!vault) return c.json({ flag: false, data: null });

    const consumed = await consumeUse(c.env, record);
    if (!consumed.ok) return c.json({ flag: false, data: null });

    await auditFromContext(c, {
      actor: "card-client",
      action: "card.get.code",
      target: fingerprint,
      result: "ok",
    });
    return c.json({
      flag: true,
      data: {
        vaults: vault.vaults,
        salt: vault.salt,
        iterations: vault.iterations,
        kdf: vault.kdf ?? "PBKDF2-SHA256",
        label: vault.label ?? record.label,
        contains: vault.contains ?? "pfx",
        remaining: consumed.remaining,
      },
    });
  }

  const kvKey = await vaultKeyV1(pubkey);
  const vault = await loadVault(c.env, kvKey);
  if (!vault) return c.json({ flag: false, data: null });

  const fingerprint = await deliveryFingerprint("key", pubkey, cfg.codePepper);
  const record = await getRecordByFingerprint(c.env, fingerprint);
  if (record) {
    const consumed = await consumeUse(c.env, record);
    if (!consumed.ok) return c.json({ flag: false, data: null });
  }

  await auditFromContext(c, {
    actor: "card-client",
    action: "card.get.key",
    target: fingerprint,
    result: "ok",
  });

  return c.json({
    flag: true,
    data: {
      vaults: vault.vaults,
      pubkey: vault.pubkey,
      pfxkey: vault.pfxkey ?? "",
      label: vault.label,
      contains: vault.contains ?? "pfx",
    },
  });
}

async function handlePutCert(c: Ctx) {
  const cfg = settings(c.env);
  const auth = await resolveAuth(c);
  if (!cfg.allowAnonymous && !hasPermission(auth, "cert:deliver")) {
    return auth.authenticated ? forbidden(c) : unauthorized(c, "站点已关闭匿名下发，请先登录");
  }

  const parsed = await readPutInput(c, cfg);
  if ("error" in parsed) {
    const status = parsed.status;
    return c.json({ flag: false, data: { error: parsed.error } }, status);
  }

  try {
    const created = await createDelivery(c.env, cfg, {
      mode: parsed.mode,
      pubkey: parsed.pubkey,
      code: parsed.code,
      pfx: parsed.pfx,
      pfxKey: parsed.pfxKey,
      label: parsed.label,
      ttlSeconds: parsed.ttl,
      maxUses: parsed.maxUses,
      source: "inline",
      createdBy: auth.user?.username ?? null,
    });
    await auditFromContext(c, {
      actor: auth.user?.username ?? "anonymous",
      action: `card.put.${parsed.mode}`,
      target: created.row.id,
      result: "ok",
      detail: `label=${parsed.label ?? "-"}`,
    });
    return c.json({
      flag: true,
      data: {
        id: created.row.id,
        mode: parsed.mode,
        code: created.code,
        expires_at: created.row.expires_at,
        max_uses: created.row.max_uses,
      },
    });
  } catch (err) {
    if (err instanceof DeliveryError) {
      return c.json({ flag: false, data: { error: err.message } }, 400);
    }
    console.error("put cert failed", err);
    return serverError(c, "证书写入失败");
  }
}

async function handleStatus(c: Ctx) {
  const params = await collectParams(c);
  const pubkey = (params.get("pubkey") ?? "").trim();
  const rawCode = (params.get("code") ?? "").trim();
  const cfg = settings(c.env);
  if (!pubkey && !rawCode) return c.json({ flag: false, data: null });

  const fingerprint = rawCode
    ? await deliveryFingerprint("code", rawCode, cfg.codePepper)
    : await deliveryFingerprint("key", pubkey, cfg.codePepper);
  const record = await getRecordByFingerprint(c.env, fingerprint);
  if (!record) return c.json({ flag: false, data: null });
  return c.json({
    flag: true,
    data: {
      label: record.label,
      mode: record.mode,
      used: record.used,
      max_uses: record.max_uses,
      remaining: Math.max(0, record.max_uses - record.used),
      expires_at: record.expires_at,
      created_at: record.created_at,
    },
  });
}

function handleUploadPage(c: Ctx) {
  return c.html(renderUploadPage(new URL(c.req.url).origin));
}

interface PutParsed {
  mode: "key" | "code";
  pubkey?: string;
  code?: string;
  pfx: Uint8Array;
  pfxKey: string;
  label?: string;
  ttl?: number;
  maxUses?: number;
}

interface PutError {
  error: string;
  status: 400 | 413;
}

async function readPutInput(c: Ctx, cfg: Settings): Promise<PutParsed | PutError> {
  const contentType = (c.req.header("content-type") ?? "").toLowerCase();
  let pubkey: string | undefined;
  let code: string | undefined;
  let modeField: string | undefined;
  let pfxKey = "";
  let label: string | undefined;
  let ttl: number | undefined;
  let maxUses: number | undefined;
  let pfx: Uint8Array | undefined;

  if (contentType.includes("multipart/form-data")) {
    const form = await c.req.formData();
    pubkey = text(form.get("pubkey"));
    code = text(form.get("code"));
    modeField = text(form.get("mode"));
    pfxKey = text(form.get("pfxkey")) ?? "";
    label = text(form.get("label"));
    ttl = number(form.get("ttl"));
    maxUses = number(form.get("max_uses"));

    // Workers 的 FormData 类型在 TS 里可能被窄化成 string，这里显式放宽
    const file = form.get("vaults") as unknown as
      | { arrayBuffer(): Promise<ArrayBuffer> }
      | string
      | null;
    if (file && typeof file !== "string") {
      const bytes = new Uint8Array(await file.arrayBuffer());
      if (bytes.length > cfg.maxBytes) return { error: "PFX 超过大小上限", status: 413 };
      pfx = bytes;
    } else {
      pfx = decodePfxBase64(text(form.get("vaults_b64")) ?? undefined) ?? undefined;
    }
  } else {
    const params = await collectParams(c);
    pubkey = params.get("pubkey") ?? undefined;
    code = params.get("code") ?? undefined;
    modeField = params.get("mode") ?? undefined;
    pfxKey = params.get("pfxkey") ?? "";
    label = params.get("label") ?? undefined;
    ttl = number(params.get("ttl"));
    maxUses = number(params.get("max_uses"));
    pfx = decodePfxBase64(params.get("vaults_b64") ?? undefined) ?? undefined;
  }

  if (!pfx) return { error: "缺少证书文件 vaults（.pfx/.p12）", status: 400 };
  if (pfx.length > cfg.maxBytes) return { error: "PFX 超过大小上限", status: 413 };
  if (!looksLikePkcs12(pfx)) return { error: "文件不是 PKCS#12（请上传 .pfx/.p12）", status: 400 };

  const wantsCode = modeField === "code" || Boolean(code) || !pubkey;
  if (wantsCode) {
    return { mode: "code", code, pfx, pfxKey, label, ttl, maxUses };
  }
  return { mode: "key", pubkey, pfx, pfxKey, label, ttl, maxUses };
}

function text(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

function number(value: unknown): number | undefined {
  const raw = typeof value === "string" ? value : null;
  if (!raw) return undefined;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}
