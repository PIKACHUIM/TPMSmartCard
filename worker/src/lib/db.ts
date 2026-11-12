import type { Env } from "../env";
import type { AuthUser } from "../types";
import { randomBytes, toHex } from "./bytes";
import { hashPassword, verifyPassword } from "./password";
import { nowIso, isoFromSeconds } from "./time";

/** D1 访问层：只放跨路由复用的查询，业务逻辑留在 lib/routes 里。 */

export interface UserRow {
  id: string;
  username: string;
  display_name: string | null;
  email: string | null;
  password_hash: string;
  password_salt: string;
  password_algo: string;
  password_iterations: number;
  status: string;
  must_change_password: number;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
}

export function newId(prefix: string): string {
  return `${prefix}_${toHex(randomBytes(12))}`;
}

export async function getUserByUsername(env: Env, username: string): Promise<UserRow | null> {
  return await env.DB.prepare("SELECT * FROM users WHERE username = ?1 COLLATE NOCASE")
    .bind(username)
    .first<UserRow>();
}

export async function getUserById(env: Env, id: string): Promise<UserRow | null> {
  return await env.DB.prepare("SELECT * FROM users WHERE id = ?1").bind(id).first<UserRow>();
}

export async function countUsers(env: Env): Promise<number> {
  const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM users").first<{ n: number }>();
  return Number(row?.n ?? 0);
}

/**
 * 首次部署引导：数据库没有任何用户且配置了 CARD_ADMIN_PASSWORD 时，
 * 自动创建 super_admin 账号（用户名 admin）。只在登录时触发一次。
 */
export async function ensureBootstrapAdmin(env: Env, iterationDefault: number): Promise<UserRow | null> {
  const existing = await countUsers(env);
  if (existing > 0) return null;
  const password = (env.CARD_ADMIN_PASSWORD ?? "").trim();
  if (!password) return null;

  const record = await hashPassword(password, iterationDefault);
  const id = newId("usr");
  const timestamp = nowIso();
  await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO users (id, username, display_name, email, password_hash, password_salt,
        password_algo, password_iterations, status, must_change_password, created_at, updated_at)
       VALUES (?1, 'admin', '引导管理员', NULL, ?2, ?3, ?4, ?5, 'active', 1, ?6, ?6)`,
    ).bind(id, record.hash, record.salt, record.algo, record.iterations, timestamp),
    env.DB.prepare(
      "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?1, 'super_admin')",
    ).bind(id),
  ]);
  return await getUserById(env, id);
}

/** 加载用户 + 角色 + 权限（每次请求一次查询，D1 索引足够快） */
export async function loadAuthUser(env: Env, userId: string): Promise<AuthUser | null> {
  const user = await getUserById(env, userId);
  if (!user || user.status !== "active") return null;

  const roles = await env.DB.prepare(
    `SELECT r.name AS name FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = ?1`,
  )
    .bind(userId)
    .all<{ name: string }>();

  const permissions = await env.DB.prepare(
    `SELECT DISTINCT rp.permission_code AS code
       FROM user_roles ur
       JOIN role_permissions rp ON rp.role_id = ur.role_id
      WHERE ur.user_id = ?1`,
  )
    .bind(userId)
    .all<{ code: string }>();

  return {
    id: user.id,
    username: user.username,
    displayName: user.display_name,
    roles: (roles.results ?? []).map((r) => r.name),
    permissions: (permissions.results ?? []).map((r) => r.code),
    mustChangePassword: user.must_change_password === 1,
  };
}

export async function verifyUserPassword(user: UserRow, password: string): Promise<boolean> {
  return await verifyPassword(password, {
    hash: user.password_hash,
    salt: user.password_salt,
    algo: user.password_algo,
    iterations: user.password_iterations,
  });
}

export async function createSessionRow(
  env: Env,
  userId: string,
  sessionId: string,
  seconds: number,
  ip: string | null,
  userAgent: string | null,
): Promise<void> {
  await env.DB.prepare(
    `INSERT INTO sessions (id, user_id, created_at, expires_at, ip, user_agent)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6)`,
  )
    .bind(sessionId, userId, nowIso(), isoFromSeconds(seconds), ip, userAgent)
    .run();
}

export async function getSessionRow(
  env: Env,
  sessionId: string,
): Promise<{ id: string; user_id: string; expires_at: string; revoked_at: string | null } | null> {
  return await env.DB.prepare(
    "SELECT id, user_id, expires_at, revoked_at FROM sessions WHERE id = ?1",
  )
    .bind(sessionId)
    .first();
}

export async function revokeSession(env: Env, sessionId: string): Promise<void> {
  await env.DB.prepare("UPDATE sessions SET revoked_at = ?1 WHERE id = ?2 AND revoked_at IS NULL")
    .bind(nowIso(), sessionId)
    .run();
}

export async function revokeUserSessions(env: Env, userId: string): Promise<void> {
  await env.DB.prepare("UPDATE sessions SET revoked_at = ?1 WHERE user_id = ?2 AND revoked_at IS NULL")
    .bind(nowIso(), userId)
    .run();
}

export async function touchLogin(env: Env, userId: string): Promise<void> {
  await env.DB.prepare("UPDATE users SET last_login_at = ?1 WHERE id = ?2").bind(nowIso(), userId).run();
}
