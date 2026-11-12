import type { Env } from "../env";
import type { Context } from "hono";
import type { AppEnv } from "../env";
import { clientIp, userAgent } from "./http";
import { nowIso } from "./time";

/**
 * 审计日志。
 *
 * 两条硬规则：
 *   1. 只记录「谁在什么时候对什么做了什么、结果如何」，**绝不**记录密钥、口令、取件码；
 *   2. 审计写入失败不能影响主流程（例如用户已经改成密码了，不能因为日志写失败而回滚），
 *      但必须打进 console 便于 Worker 日志排查。
 */
export interface AuditEntry {
  actor: string;
  action: string;
  target?: string | null;
  result?: "ok" | "deny" | "error";
  detail?: string | null;
  ip?: string | null;
  userAgent?: string | null;
}

export async function writeAudit(env: Env, entry: AuditEntry): Promise<void> {
  const values = [
    entry.actor || "anonymous",
    entry.action,
    entry.target ?? null,
    entry.result ?? "ok",
    entry.ip ?? null,
    entry.userAgent ?? null,
    redact(entry.detail),
  ];
  try {
    await env.DB.prepare(
      `INSERT INTO audit_logs (actor, action, target, result, ip, user_agent, detail, created_at)
       VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)`,
    )
      .bind(...values.slice(0, 7), nowIso())
      .run();
  } catch (err) {
    console.error("audit write failed", err);
  }
}

/** 从请求上下文写一条审计（自动带上 IP 与 UA） */
export async function auditFromContext(
  c: Context<AppEnv>,
  entry: Omit<AuditEntry, "ip" | "userAgent">,
): Promise<void> {
  await writeAudit(c.env, {
    ...entry,
    ip: clientIp(c),
    userAgent: userAgent(c),
  });
}

/** 兜底脱敏：即使调用方不小心把凭证拼进 detail，也不会原样落库 */
function redact(detail: string | null | undefined): string | null {
  if (!detail) return detail ?? null;
  return detail
    .replace(/[A-Za-z0-9+/]{32,}={0,2}/g, "***")
    .replace(/\b\d{4}-\d{4}-\d{4}-\d{4}\b/g, "****-****-****-****")
    .replace(/(password|pfxkey|token|secret)=([^&\s]+)/gi, "$1=***");
}
