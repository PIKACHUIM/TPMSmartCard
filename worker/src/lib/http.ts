import type { Context } from "hono";
import type { ContentfulStatusCode } from "hono/utils/http-status";
import type { AppEnv } from "../env";
import { ERROR_CODES, type ErrorCode } from "@tpmsc/protocol";

/** 统一响应包络：{ done, data } / { done, error, code } */

export function ok<T>(c: Context<AppEnv>, data: T, status: ContentfulStatusCode = 200) {
  return c.json({ done: true as const, data }, status);
}

export function fail(
  c: Context<AppEnv>,
  status: ContentfulStatusCode,
  code: ErrorCode,
  error: string,
  detail?: string,
) {
  return c.json({ done: false as const, error, code, detail }, status);
}

export function badRequest(c: Context<AppEnv>, error: string, detail?: string) {
  return fail(c, 400, ERROR_CODES.badRequest, error, detail);
}

export function unauthorized(c: Context<AppEnv>, error = "需要登录") {
  return fail(c, 401, ERROR_CODES.unauthorized, error);
}

export function forbidden(c: Context<AppEnv>, error = "没有操作权限") {
  return fail(c, 403, ERROR_CODES.forbidden, error);
}

export function notFound(c: Context<AppEnv>, error = "资源不存在") {
  return fail(c, 404, ERROR_CODES.notFound, error);
}

export function serverError(c: Context<AppEnv>, error = "服务端处理失败", detail?: string) {
  return fail(c, 500, ERROR_CODES.internal, error, detail);
}

/**
 * 收集请求参数。
 *
 * 旧版智能卡工具用 `requests.get(url, data={...})` 把参数放在 **GET 的请求体**里，
 * 因此这里必须同时支持：query、urlencoded body、JSON body。
 * multipart 交给调用方用 `c.req.formData()`，此处提前返回避免消费 body。
 */
export async function collectParams(c: Context<AppEnv>): Promise<URLSearchParams> {
  const params = new URLSearchParams(new URL(c.req.url).search);
  const contentType = (c.req.header("content-type") ?? "").toLowerCase();

  if (contentType.includes("multipart/form-data")) return params;

  const text = await readBodyText(c);
  if (!text) return params;

  if (contentType.includes("application/json")) {
    try {
      const obj = JSON.parse(text) as Record<string, unknown>;
      for (const [key, value] of Object.entries(obj)) {
        if (value === null || value === undefined) continue;
        params.set(key, typeof value === "string" ? value : JSON.stringify(value));
      }
    } catch {
      // 非法 JSON 按「没有参数」处理，由调用方给出明确错误
    }
    return params;
  }

  for (const [key, value] of new URLSearchParams(text)) params.set(key, value);
  return params;
}

async function readBodyText(c: Context<AppEnv>): Promise<string> {
  // GET/HEAD 也可能带 body（旧客户端历史写法），Hono 允许读取
  const length = Number(c.req.header("content-length") ?? "0");
  if (c.req.method === "GET" && !length) return "";
  return await c.req.text();
}

export function clientIp(c: Context<AppEnv>): string {
  return (
    c.req.header("cf-connecting-ip") ??
    c.req.header("x-real-ip") ??
    (c.req.header("x-forwarded-for") ?? "").split(",")[0].trim() ??
    "unknown"
  );
}

export function userAgent(c: Context<AppEnv>): string {
  return (c.req.header("user-agent") ?? "").slice(0, 300);
}

/** 从请求中提取会话凭证：Bearer / x-admin-token / 查询参数 / Cookie */
export function extractToken(c: Context<AppEnv>): string {
  const authorization = c.req.header("authorization") ?? "";
  if (authorization.toLowerCase().startsWith("bearer ")) return authorization.slice(7).trim();
  const headerToken = c.req.header("x-admin-token");
  if (headerToken) return headerToken.trim();
  const queryToken = new URL(c.req.url).searchParams.get("token");
  if (queryToken) return queryToken.trim();
  const cookie = c.req.header("cookie") ?? "";
  const match = /(?:^|;\s*)tpmsc_session=([^;]+)/.exec(cookie);
  return match ? decodeURIComponent(match[1]) : "";
}
