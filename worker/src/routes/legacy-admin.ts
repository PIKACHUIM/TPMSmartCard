import type { Context, Hono } from "hono";
import type { AppEnv } from "../env";
import { CARD_ROUTES } from "@tpmsc/protocol";
import { hasPermission, resolveAuth } from "../lib/rbac";
import { auditFromContext } from "../lib/audit";
import { collectParams, forbidden, notFound, ok, unauthorized } from "../lib/http";
import { getRecord, listRecords, revokeRecord } from "../lib/records";
import { findLegacyRecord } from "./admin";

/**
 * PikaTestCert 时代的 `/card/admin/*` 缓存管理接口。
 *
 * 语义与新版一致（会话令牌或静态令牌 + 权限码），只是响应包络沿用
 * `{done:true,data}`，方便旧脚本与旧管理页继续工作。
 */
export function mountLegacyAdminRoutes(app: Hono<AppEnv>): void {
  app.get(CARD_ROUTES.adminList, handleList);
  app.post(CARD_ROUTES.adminList, handleList);
  app.post(CARD_ROUTES.adminDelete, handleDelete);
}

async function handleList(c: Context<AppEnv>) {
  const auth = await resolveAuth(c);
  if (!auth.authenticated) return unauthorized(c);
  if (!hasPermission(auth, "record:read")) return forbidden(c, "缺少权限：record:read");

  const result = await listRecords(c.env, { limit: 100 });
  return ok(c, { records: result.rows, total: result.total });
}

async function handleDelete(c: Context<AppEnv>) {
  const auth = await resolveAuth(c);
  if (!auth.authenticated) return unauthorized(c);
  if (!hasPermission(auth, "record:delete")) return forbidden(c, "缺少权限：record:delete");

  const params = await collectParams(c);
  const found = await findLegacyRecord(c, params);
  if (!found) return notFound(c, "记录不存在或已删除");
  const row = await getRecord(c.env, found.id);
  if (!row) return notFound(c, "记录不存在");

  await revokeRecord(c.env, row);
  await auditFromContext(c, {
    actor: auth.user?.username ?? "unknown",
    action: "record.delete.legacy",
    target: row.id,
    result: "ok",
  });
  return ok(c, { done: true, id: row.id });
}
