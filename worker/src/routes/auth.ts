import type { Context, Hono } from "hono";
import type { AppEnv } from "../env";
import { deleteCookie, setCookie } from "hono/cookie";
import { API_PREFIX, CARD_ROUTES } from "@tpmsc/protocol";
import {
  countUsers,
  createSessionRow,
  ensureBootstrapAdmin,
  getUserByUsername,
  revokeSession,
  revokeUserSessions,
  touchLogin,
  verifyUserPassword,
} from "../lib/db";
import { hashPassword, checkPasswordStrength } from "../lib/password";
import { createSessionToken } from "../lib/session";
import { settings } from "../lib/settings";
import { auditFromContext } from "../lib/audit";
import { badRequest, clientIp, collectParams, fail, ok, unauthorized } from "../lib/http";
import { clearLoginFailures, loginFailureState, recordLoginFailure } from "../lib/ratelimit";
import { loadAuthUser, getUserById } from "../lib/db";
import { resolveAuth } from "../lib/rbac";
import { isoFromSeconds } from "../lib/time";

/**
 * 登录 / 登出 / 当前身份 / 改密。
 *
 * 同时注册旧版 `/card/admin/login` 与 `/card/admin/session`，
 * 让 PikaTestCert 时代的管理脚本可以不改代码继续用。
 */
export function mountAuthRoutes(app: Hono<AppEnv>): void {
  app.post(`${API_PREFIX}/auth/login`, handleLogin);
  app.post(CARD_ROUTES.adminLogin, handleLogin);
  app.post(`${API_PREFIX}/auth/logout`, handleLogout);
  app.get(`${API_PREFIX}/auth/me`, handleMe);
  app.get(CARD_ROUTES.adminSession, handleSession);
  app.post(CARD_ROUTES.adminSession, handleSession);
  app.post(`${API_PREFIX}/auth/password`, handleChangePassword);
  app.get(`${API_PREFIX}/policy`, handlePolicy);
}

async function handleLogin(c: Context<AppEnv>) {
  const cfg = settings(c.env);
  const params = await collectParams(c);
  const password = (params.get("password") ?? "").trim();
  let username = (params.get("username") ?? "").trim();

  if (!password) return badRequest(c, "请输入口令");

  const ip = clientIp(c);
  const state = await loginFailureState(c.env, ip, cfg.loginMaxFailures);
  if (state.blocked) {
    await auditFromContext(c, {
      actor: username || "unknown",
      action: "auth.login",
      result: "deny",
      detail: "rate limited",
    });
    return fail(c, 429, "rate_limited", "登录失败次数过多，请 10 分钟后再试");
  }

  // 首次部署：没有用户时用引导口令创建 admin
  if ((await countUsers(c.env)) === 0) {
    await ensureBootstrapAdmin(c.env, cfg.passwordIterations);
  }
  if (!username) username = "admin";

  const user = await getUserByUsername(c.env, username);
  const passwordOk = user ? await verifyUserPassword(user, password) : false;
  if (!user || !passwordOk || user.status !== "active") {
    await recordLoginFailure(c.env, ip);
    await auditFromContext(c, {
      actor: username || "unknown",
      action: "auth.login",
      result: "deny",
      detail: "invalid credentials",
    });
    return unauthorized(c, "用户名或口令不正确");
  }

  await clearLoginFailures(c.env, ip);
  await touchLogin(c.env, user.id);
  const session = await issueSession(c, user.id, cfg.sessionSeconds);
  const authUser = await loadAuthUser(c.env, user.id);
  await auditFromContext(c, { actor: user.username, action: "auth.login", result: "ok" });

  return ok(c, {
    token: session.token,
    expires_at: session.expiresAt,
    user: authUser,
    policy: policyPayload(c),
  });
}

async function handleLogout(c: Context<AppEnv>) {
  const auth = await resolveAuth(c);
  if (auth.via === "session") {
    // 从令牌中取 sid 需要重新验签，这里直接吊销该用户全部会话更安全
    if (auth.user) await revokeUserSessions(c.env, auth.user.id);
  }
  deleteCookie(c, "tpmsc_session", { path: "/" });
  await auditFromContext(c, {
    actor: auth.user?.username ?? "anonymous",
    action: "auth.logout",
    result: "ok",
  });
  return ok(c, { done: true });
}

async function handleMe(c: Context<AppEnv>) {
  const auth = await resolveAuth(c);
  if (!auth.authenticated) return unauthorized(c);
  return ok(c, { user: auth.user, via: auth.via, expires_at: auth.expiresAt, policy: policyPayload(c) });
}

function handleSession(c: Context<AppEnv>) {
  const auth = c.get("auth");
  return ok(c, {
    authenticated: Boolean(auth?.authenticated),
    user: auth?.user ?? null,
    policy: policyPayload(c),
  });
}

function handlePolicy(c: Context<AppEnv>) {
  return ok(c, policyPayload(c));
}

async function handleChangePassword(c: Context<AppEnv>) {
  const auth = await resolveAuth(c);
  if (!auth.authenticated || !auth.user) return unauthorized(c);
  if (auth.user.id === "static-token") return badRequest(c, "静态令牌账号不能改密");

  const params = await collectParams(c);
  const current = (params.get("current_password") ?? "").trim();
  const next = (params.get("new_password") ?? "").trim();
  const strength = checkPasswordStrength(next);
  if (!strength.ok) return badRequest(c, strength.reason);

  const user = await getUserById(c.env, auth.user.id);
  if (!user) return unauthorized(c);
  if (!(await verifyUserPassword(user, current))) return unauthorized(c, "当前口令不正确");

  const cfg = settings(c.env);
  const record = await hashPassword(next, cfg.passwordIterations);
  await c.env.DB.prepare(
    `UPDATE users SET password_hash = ?1, password_salt = ?2, password_algo = ?3,
       password_iterations = ?4, must_change_password = 0, updated_at = ?5 WHERE id = ?6`,
  )
    .bind(record.hash, record.salt, record.algo, record.iterations, new Date().toISOString(), user.id)
    .run();
  await revokeUserSessions(c.env, user.id);
  await auditFromContext(c, {
    actor: auth.user.username,
    action: "auth.password.change",
    target: user.id,
    result: "ok",
  });
  deleteCookie(c, "tpmsc_session", { path: "/" });
  return ok(c, { done: true });
}

/** 登录成功后签发会话并写 Cookie */
async function issueSession(
  c: Context<AppEnv>,
  userId: string,
  seconds: number,
): Promise<{ token: string; expiresAt: string }> {
  const cfg = settings(c.env);
  const sid = `ses_${crypto.randomUUID().replace(/-/g, "").slice(0, 20)}`;
  const expiresAt = isoFromSeconds(seconds);
  await createSessionRow(c.env, userId, sid, seconds, clientIp(c), c.req.header("user-agent") ?? null);
  const token = await createSessionToken(cfg.sessionSecret, {
    sub: userId,
    sid,
    iat: Math.floor(Date.now() / 1000),
    exp: Math.floor(Date.now() / 1000) + seconds,
  });
  setCookie(c, "tpmsc_session", token, {
    path: "/",
    httpOnly: true,
    sameSite: "Lax",
    secure: new URL(c.req.url).protocol === "https:",
    maxAge: seconds,
  });
  return { token, expiresAt };
}

function policyPayload(c: Context<AppEnv>) {
  const cfg = settings(c.env);
  return {
    allow_anonymous: cfg.allowAnonymous,
    // 用户表存在即支持口令登录；引导口令只是「第一个管理员」的来源
    password_login: true,
    code_ttl_seconds: cfg.codeTtlSeconds,
    code_iterations: cfg.codeIterations,
    max_pfx_bytes: cfg.maxBytes,
    session_seconds: cfg.sessionSeconds,
  };
}

/** 吊销指定会话（管理台「退出其他设备」用） */
export async function forceLogout(env: AppEnv["Bindings"], sessionId: string): Promise<void> {
  await revokeSession(env, sessionId);
}
