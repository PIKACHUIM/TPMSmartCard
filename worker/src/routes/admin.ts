import type { Context, Hono } from "hono";
import type { AppEnv } from "../env";
import { API_PREFIX, PERMISSIONS, ROLE_PERMISSIONS } from "@tpmsc/protocol";
import { hashPassword, checkPasswordStrength } from "../lib/password";
import { newId, revokeUserSessions, getUserById } from "../lib/db";
import { listRecords, getRecord, revokeRecord } from "../lib/records";
import { getRecordByFingerprint } from "../lib/records";
import { deliveryFingerprint } from "../lib/delivery";
import { requirePermission } from "../lib/rbac";
import { auditFromContext } from "../lib/audit";
import { badRequest, collectParams, notFound, ok } from "../lib/http";
import { settings } from "../lib/settings";
import { nowIso } from "../lib/time";

/**
 * 管理台 API：用户 / 角色 / 下发记录 / 审计 / 策略。
 * 所有写操作都走 requirePermission，且必须落审计。
 */
export function mountAdminRoutes(app: Hono<AppEnv>): void {
  app.get(`${API_PREFIX}/permissions`, requirePermission("user:read"), handlePermissions);

  app.get(`${API_PREFIX}/users`, requirePermission("user:read"), handleListUsers);
  app.post(`${API_PREFIX}/users`, requirePermission("user:write"), handleCreateUser);
  app.patch(`${API_PREFIX}/users/:id`, requirePermission("user:write"), handleUpdateUser);
  app.post(`${API_PREFIX}/users/:id/password`, requirePermission("user:write"), handleResetPassword);

  app.get(`${API_PREFIX}/roles`, requirePermission("user:read"), handleListRoles);
  app.post(`${API_PREFIX}/roles`, requirePermission("role:write"), handleCreateRole);

  app.get(`${API_PREFIX}/records`, requirePermission("record:read"), handleListRecords);
  app.delete(`${API_PREFIX}/records/:id`, requirePermission("record:delete"), handleDeleteRecord);

  app.get(`${API_PREFIX}/audit`, requirePermission("audit:read"), handleListAudit);
}

function handlePermissions(c: Context<AppEnv>) {
  return ok(c, {
    permissions: PERMISSIONS,
    builtin_roles: ROLE_PERMISSIONS,
  });
}

async function handleListUsers(c: Context<AppEnv>) {
  const rows = await c.env.DB.prepare(
    `SELECT u.id, u.username, u.display_name, u.email, u.status, u.must_change_password,
            u.created_at, u.last_login_at,
            COALESCE(GROUP_CONCAT(r.name, ','), '') AS roles
       FROM users u
       LEFT JOIN user_roles ur ON ur.user_id = u.id
       LEFT JOIN roles r ON r.id = ur.role_id
      GROUP BY u.id ORDER BY u.created_at ASC`,
  ).all<Record<string, unknown>>();
  return ok(c, {
    users: (rows.results ?? []).map((row) => ({
      ...row,
      roles: String(row.roles ?? "").split(",").filter(Boolean),
    })),
  });
}

async function handleCreateUser(c: Context<AppEnv>) {
  const params = await readPayload(c);
  const username = String(params.username ?? "").trim();
  const password = String(params.password ?? "");
  const roles = Array.isArray(params.roles) ? params.roles.map(String) : ["user"];
  if (!/^[a-zA-Z0-9._-]{3,32}$/.test(username)) return badRequest(c, "用户名需为 3~32 位字母、数字或 ._-");
  const strength = checkPasswordStrength(password);
  if (!strength.ok) return badRequest(c, strength.reason);

  const exists = await c.env.DB.prepare("SELECT id FROM users WHERE username = ?1 COLLATE NOCASE")
    .bind(username)
    .first<{ id: string }>();
  if (exists) return badRequest(c, "用户名已存在");

  const cfg = settings(c.env);
  const record = await hashPassword(password, cfg.passwordIterations);
  const id = newId("usr");
  const timestamp = nowIso();
  const statements = [
    c.env.DB.prepare(
      `INSERT INTO users (id, username, display_name, email, password_hash, password_salt,
        password_algo, password_iterations, status, must_change_password, created_at, updated_at)
       VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, 'active', 1, ?9, ?9)`,
    ).bind(
      id,
      username,
      String(params.display_name ?? username),
      params.email ? String(params.email) : null,
      record.hash,
      record.salt,
      record.algo,
      record.iterations,
      timestamp,
    ),
    ...roles.map((role) =>
      c.env.DB.prepare("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?1, ?2)").bind(
        id,
        role,
      ),
    ),
  ];
  await c.env.DB.batch(statements);
  await auditFromContext(c, {
    actor: c.get("auth").user?.username ?? "unknown",
    action: "user.create",
    target: id,
    result: "ok",
    detail: `roles=${roles.join(",")}`,
  });
  return ok(c, { id, username, roles }, 201);
}

async function handleUpdateUser(c: Context<AppEnv>) {
  const id = c.req.param("id") ?? "";
  const user = await getUserById(c.env, id);
  if (!user) return notFound(c, "用户不存在");
  const payload = await readPayload(c);

  const updates: string[] = [];
  const binds: unknown[] = [];
  if (typeof payload.display_name === "string") {
    updates.push(`display_name = ?${binds.length + 1}`);
    binds.push(payload.display_name);
  }
  if (typeof payload.status === "string" && ["active", "disabled"].includes(payload.status)) {
    updates.push(`status = ?${binds.length + 1}`);
    binds.push(payload.status);
  }
  if (updates.length > 0) {
    updates.push(`updated_at = ?${binds.length + 1}`);
    binds.push(nowIso());
    binds.push(id);
    await c.env.DB.prepare(`UPDATE users SET ${updates.join(", ")} WHERE id = ?${binds.length}`)
      .bind(...binds)
      .run();
  }

  if (Array.isArray(payload.roles)) {
    const roles = payload.roles.map(String);
    await c.env.DB.prepare("DELETE FROM user_roles WHERE user_id = ?1").bind(id).run();
    for (const role of roles) {
      await c.env.DB.prepare("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?1, ?2)")
        .bind(id, role)
        .run();
    }
    await revokeUserSessions(c.env, id);
  }

  await auditFromContext(c, {
    actor: c.get("auth").user?.username ?? "unknown",
    action: "user.update",
    target: id,
    result: "ok",
  });
  return ok(c, { done: true });
}

async function handleResetPassword(c: Context<AppEnv>) {
  const id = c.req.param("id") ?? "";
  const user = await getUserById(c.env, id);
  if (!user) return notFound(c, "用户不存在");
  const payload = await readPayload(c);
  const password = String(payload.password ?? "");
  const strength = checkPasswordStrength(password);
  if (!strength.ok) return badRequest(c, strength.reason);

  const cfg = settings(c.env);
  const record = await hashPassword(password, cfg.passwordIterations);
  await c.env.DB.prepare(
    `UPDATE users SET password_hash = ?1, password_salt = ?2, password_algo = ?3,
       password_iterations = ?4, must_change_password = 1, updated_at = ?5 WHERE id = ?6`,
  )
    .bind(record.hash, record.salt, record.algo, record.iterations, nowIso(), id)
    .run();
  await revokeUserSessions(c.env, id);
  await auditFromContext(c, {
    actor: c.get("auth").user?.username ?? "unknown",
    action: "user.password.reset",
    target: id,
    result: "ok",
  });
  return ok(c, { done: true });
}

async function handleListRoles(c: Context<AppEnv>) {
  const rows = await c.env.DB.prepare(
    `SELECT r.id, r.name, r.description, r.builtin,
            COALESCE(GROUP_CONCAT(rp.permission_code, ','), '') AS permissions
       FROM roles r LEFT JOIN role_permissions rp ON rp.role_id = r.id
      GROUP BY r.id ORDER BY r.builtin DESC, r.name ASC`,
  ).all<Record<string, unknown>>();
  return ok(c, {
    roles: (rows.results ?? []).map((row) => ({
      ...row,
      permissions: String(row.permissions ?? "").split(",").filter(Boolean),
    })),
  });
}

async function handleCreateRole(c: Context<AppEnv>) {
  const payload = await readPayload(c);
  const name = String(payload.name ?? "").trim();
  if (!/^[a-z][a-z0-9_]{2,31}$/.test(name)) return badRequest(c, "角色名需为小写字母开头，3~32 位");
  const permissions = Array.isArray(payload.permissions)
    ? payload.permissions.map(String).filter((p) => (PERMISSIONS as readonly string[]).includes(p))
    : [];
  const id = newId("rol");
  await c.env.DB.batch([
    c.env.DB.prepare("INSERT INTO roles (id, name, description, builtin, created_at) VALUES (?1, ?2, ?3, 0, ?4)")
      .bind(id, name, String(payload.description ?? ""), nowIso()),
    ...permissions.map((permission) =>
      c.env.DB.prepare("INSERT OR IGNORE INTO role_permissions (role_id, permission_code) VALUES (?1, ?2)")
        .bind(id, permission),
    ),
  ]);
  await auditFromContext(c, {
    actor: c.get("auth").user?.username ?? "unknown",
    action: "role.create",
    target: id,
    result: "ok",
    detail: `permissions=${permissions.join(",")}`,
  });
  return ok(c, { id, name, permissions }, 201);
}

async function handleListRecords(c: Context<AppEnv>) {
  const url = new URL(c.req.url);
  const result = await listRecords(c.env, {
    query: url.searchParams.get("q") ?? undefined,
    mode: (url.searchParams.get("mode") as "key" | "code" | null) ?? undefined,
    state: (url.searchParams.get("state") as never) ?? undefined,
    limit: Number.parseInt(url.searchParams.get("limit") ?? "50", 10),
    offset: Number.parseInt(url.searchParams.get("offset") ?? "0", 10),
  });
  return ok(c, result);
}

async function handleDeleteRecord(c: Context<AppEnv>) {
  const id = c.req.param("id") ?? "";
  const row = await getRecord(c.env, id);
  if (!row) return notFound(c, "记录不存在");
  await revokeRecord(c.env, row);
  await auditFromContext(c, {
    actor: c.get("auth").user?.username ?? "unknown",
    action: "record.delete",
    target: id,
    result: "ok",
  });
  return ok(c, { done: true });
}

async function handleListAudit(c: Context<AppEnv>) {
  const url = new URL(c.req.url);
  const limit = Math.min(Math.max(Number.parseInt(url.searchParams.get("limit") ?? "50", 10), 1), 200);
  const offset = Math.max(Number.parseInt(url.searchParams.get("offset") ?? "0", 10), 0);
  const actor = url.searchParams.get("actor");
  const action = url.searchParams.get("action");

  const clauses: string[] = [];
  const binds: unknown[] = [];
  if (actor) {
    clauses.push("actor = ?");
    binds.push(actor);
  }
  if (action) {
    clauses.push("action LIKE ?");
    binds.push(`%${action}%`);
  }
  const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
  const total = await c.env.DB.prepare(`SELECT COUNT(*) AS n FROM audit_logs ${where}`)
    .bind(...binds)
    .first<{ n: number }>();
  const rows = await c.env.DB.prepare(
    `SELECT * FROM audit_logs ${where} ORDER BY id DESC LIMIT ? OFFSET ?`,
  )
    .bind(...binds, limit, offset)
    .all();

  return ok(c, { rows: rows.results ?? [], total: Number(total?.n ?? 0) });
}

/** 兼容 JSON / urlencoded 两种提交 */
async function readPayload(c: Context<AppEnv>): Promise<Record<string, unknown>> {
  const contentType = (c.req.header("content-type") ?? "").toLowerCase();
  if (contentType.includes("application/json")) {
    return (await c.req.json().catch(() => ({}))) as Record<string, unknown>;
  }
  const params = await collectParams(c);
  const out: Record<string, unknown> = {};
  for (const [key, value] of params.entries()) {
    if (key === "roles" || key === "permissions") {
      out[key] = value.split(",").map((item) => item.trim()).filter(Boolean);
    } else {
      out[key] = value;
    }
  }
  return out;
}

/** 旧管理接口删除时按指纹定位（PikaTestCert 的字段风格） */
export async function findLegacyRecord(
  c: Context<AppEnv>,
  params: URLSearchParams,
): Promise<{ id: string } | null> {
  const id = params.get("id");
  if (id) {
    const row = await getRecord(c.env, id);
    return row ? { id: row.id } : null;
  }
  const code = params.get("code");
  const pubkey = params.get("pubkey");
  const fingerprint = params.get("fingerprint");
  const cfg = settings(c.env);
  const value = fingerprint ?? (code ? await deliveryFingerprint("code", code, cfg.codePepper) : pubkey ? await deliveryFingerprint("key", pubkey, cfg.codePepper) : null);
  if (!value) return null;
  const row = await getRecordByFingerprint(c.env, value);
  return row ? { id: row.id } : null;
}
