import type { Context, MiddlewareHandler, Next } from "hono";
import type { AppEnv } from "../env";
import type { AuthContext } from "../types";
import { ANONYMOUS } from "../types";
import { PERMISSIONS, ROLE_PERMISSIONS } from "@tpmsc/protocol";
import { timingSafeEqualString } from "./bytes";
import { getSessionRow, loadAuthUser } from "./db";
import { extractToken, forbidden, unauthorized } from "./http";
import { legacyAdminToken, settings } from "./settings";
import { verifySessionToken } from "./session";
import { auditFromContext } from "./audit";

/**
 * 认证与授权。
 *
 * 凭证来源优先级：静态令牌（脚本）> 会话令牌（浏览器/管理台）。
 * 静态令牌被当作 super_admin，仅用于旧脚本与运维，不落审计的 actor 记为 `static-token`。
 */
export async function resolveAuth(c: Context<AppEnv>): Promise<AuthContext> {
  const token = extractToken(c);
  if (!token) return ANONYMOUS;

  const env = c.env;
  const staticToken = legacyAdminToken(env);
  if (staticToken && timingSafeEqualString(token, staticToken)) {
    return {
      authenticated: true,
      via: "token",
      user: {
        id: "static-token",
        username: "static-token",
        displayName: "静态令牌",
        roles: ["super_admin"],
        permissions: [...PERMISSIONS],
        mustChangePassword: false,
      },
    };
  }

  const cfg = settings(env);
  const verified = await verifySessionToken(cfg.sessionSecret, token);
  if (!verified) return ANONYMOUS;

  const row = await getSessionRow(env, verified.sid);
  if (!row || row.revoked_at) return ANONYMOUS;
  if (Date.parse(row.expires_at) <= Date.now()) return ANONYMOUS;

  const user = await loadAuthUser(env, row.user_id);
  if (!user) return ANONYMOUS;
  return { authenticated: true, via: "session", user, expiresAt: row.expires_at };
}

/** 所有 /api/v1 路由的前置中间件：解析一次认证上下文 */
export const loadAuth: MiddlewareHandler<AppEnv> = async (c, next) => {
  c.set("auth", await resolveAuth(c));
  await next();
};

export function hasPermission(auth: AuthContext, permission: string): boolean {
  if (!auth.authenticated || !auth.user) return false;
  return auth.user.permissions.includes(permission);
}

/**
 * 权限中间件。每请求重新从 D1 读角色权限（索引查询，成本可控），
 * 避免「刚被降权但旧会话仍可操作」的窗口。
 */
export function requirePermission(permission: string): MiddlewareHandler<AppEnv> {
  return async (c: Context<AppEnv>, next: Next) => {
    const auth = c.get("auth") ?? (await resolveAuth(c));
    c.set("auth", auth);

    if (!auth.authenticated || !auth.user) {
      await auditFromContext(c, {
        actor: "anonymous",
        action: `deny:${permission}`,
        result: "deny",
        target: new URL(c.req.url).pathname,
      });
      return unauthorized(c);
    }
    if (!auth.user.permissions.includes(permission)) {
      await auditFromContext(c, {
        actor: auth.user.username,
        action: `deny:${permission}`,
        result: "deny",
        target: new URL(c.req.url).pathname,
      });
      return forbidden(c, `缺少权限：${permission}`);
    }
    await next();
  };
}

export function requireAuth(): MiddlewareHandler<AppEnv> {
  return async (c: Context<AppEnv>, next: Next) => {
    const auth = c.get("auth") ?? (await resolveAuth(c));
    c.set("auth", auth);
    if (!auth.authenticated || !auth.user) {
      return unauthorized(c);
    }
    await next();
  };
}

/** 内置角色权限（迁移种子与前端菜单共用；自定义角色从 D1 读取） */
export function builtinPermissions(role: string): string[] {
  return ROLE_PERMISSIONS[role] ?? [];
}
