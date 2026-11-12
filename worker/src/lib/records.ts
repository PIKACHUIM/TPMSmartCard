import type { Env } from "../env";
import type { DeliveryRow } from "../types";
import type { RecordRow } from "@tpmsc/protocol";
import { deleteVault } from "./card-vault";
import { isExpired } from "./time";

/** 下发记录的读取 / 状态推导 / 核销 / 删除 */

export type RecordState = RecordRow["state"];

export function recordState(row: DeliveryRow): RecordState {
  if (row.revoked) return "revoked";
  if (row.expires_at && isExpired(row.expires_at)) return "expired";
  if (row.used >= row.max_uses) return "exhausted";
  return "active";
}

export function toRecordRow(row: DeliveryRow): RecordRow {
  return {
    id: row.id,
    mode: row.mode,
    label: row.label,
    fingerprint: row.fingerprint,
    common_name: row.common_name,
    serial_number: row.serial_number,
    source: row.source,
    used: row.used,
    max_uses: row.max_uses,
    created_at: row.created_at,
    expires_at: row.expires_at,
    state: recordState(row),
  };
}

export interface ListOptions {
  query?: string;
  mode?: "key" | "code";
  state?: RecordState;
  limit?: number;
  offset?: number;
}

export async function listRecords(
  env: Env,
  options: ListOptions = {},
): Promise<{ rows: RecordRow[]; total: number }> {
  const limit = Math.min(Math.max(options.limit ?? 50, 1), 200);
  const offset = Math.max(options.offset ?? 0, 0);
  const clauses: string[] = [];
  const binds: unknown[] = [];

  if (options.query) {
    clauses.push("(label LIKE ? OR common_name LIKE ? OR serial_number LIKE ? OR fingerprint LIKE ?)");
    const like = `%${options.query}%`;
    binds.push(like, like, like, like);
  }
  if (options.mode) {
    clauses.push("mode = ?");
    binds.push(options.mode);
  }
  if (options.state === "revoked") clauses.push("revoked = 1");
  if (options.state === "expired") {
    clauses.push("revoked = 0 AND expires_at IS NOT NULL AND expires_at <= ?");
    binds.push(new Date().toISOString());
  }
  if (options.state === "exhausted") clauses.push("revoked = 0 AND used >= max_uses");
  if (options.state === "active") {
    clauses.push("revoked = 0 AND used < max_uses AND (expires_at IS NULL OR expires_at > ?)");
    binds.push(new Date().toISOString());
  }

  const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
  const totalRow = await env.DB.prepare(`SELECT COUNT(*) AS n FROM deliveries ${where}`)
    .bind(...binds)
    .first<{ n: number }>();

  const rows = await env.DB.prepare(
    `SELECT * FROM deliveries ${where} ORDER BY created_at DESC LIMIT ? OFFSET ?`,
  )
    .bind(...binds, limit, offset)
    .all<DeliveryRow>();

  return {
    rows: (rows.results ?? []).map(toRecordRow),
    total: Number(totalRow?.n ?? 0),
  };
}

export async function getRecord(env: Env, id: string): Promise<DeliveryRow | null> {
  return await env.DB.prepare("SELECT * FROM deliveries WHERE id = ?1").bind(id).first<DeliveryRow>();
}

export async function getRecordByFingerprint(
  env: Env,
  fingerprint: string,
): Promise<DeliveryRow | null> {
  return await env.DB.prepare(
    "SELECT * FROM deliveries WHERE fingerprint = ?1 AND revoked = 0 ORDER BY created_at DESC LIMIT 1",
  )
    .bind(fingerprint)
    .first<DeliveryRow>();
}

/** 删除记录：先清 KV 再标记 revoked，KV 失败不回滚（宁可留密文也不能留可下发状态） */
export async function revokeRecord(env: Env, row: DeliveryRow): Promise<void> {
  try {
    await deleteVault(env, row.kv_key);
  } catch (err) {
    console.error("kv delete failed", err);
  }
  await env.DB.prepare("UPDATE deliveries SET revoked = 1 WHERE id = ?1").bind(row.id).run();
}

/**
 * 核销一次取回。
 *
 * 并发安全依赖 D1 的单条 UPDATE：`used < max_uses` 作为条件，
 * 返回 changes=0 说明已用尽。KV 最终一致性导致的并发超发仍可能发生，
 * 因此默认 max_uses=1，且文档里明确这一限制。
 */
export async function consumeUse(
  env: Env,
  row: DeliveryRow,
): Promise<{ ok: boolean; used: number; remaining: number }> {
  const result = await env.DB.prepare(
    "UPDATE deliveries SET used = used + 1 WHERE id = ?1 AND used < max_uses AND revoked = 0",
  )
    .bind(row.id)
    .run();
  const changed = Number(result.meta?.changes ?? 0);
  if (changed === 0) {
    return { ok: false, used: row.used, remaining: 0 };
  }
  const used = row.used + 1;
  const remaining = Math.max(0, row.max_uses - used);
  if (remaining === 0) await deleteVault(env, row.kv_key).catch((err) => console.error(err));
  return { ok: true, used, remaining };
}
