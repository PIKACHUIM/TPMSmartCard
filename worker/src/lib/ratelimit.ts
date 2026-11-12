import type { Env } from "../env";

/**
 * 登录失败限流：按来源 IP 在 KV 计数，默认 5 次 / 10 分钟。
 * 用 KV 而不是 D1，是因为这类计数写入频繁、没有关系查询需求，
 * 且 KV 的 TTL 天然实现了窗口滚动。
 */
const WINDOW_SECONDS = 600;

function key(ip: string): string {
  return `auth:fail:${ip || "unknown"}`;
}

export interface FailureState {
  blocked: boolean;
  failures: number;
  max: number;
}

export async function loginFailureState(env: Env, ip: string, max: number): Promise<FailureState> {
  const raw = await env.CARD_KV.get(key(ip));
  const failures = Number.parseInt(raw ?? "0", 10) || 0;
  return { blocked: failures >= max, failures, max };
}

export async function recordLoginFailure(env: Env, ip: string): Promise<void> {
  const current = Number.parseInt((await env.CARD_KV.get(key(ip))) ?? "0", 10) || 0;
  await env.CARD_KV.put(key(ip), String(current + 1), { expirationTtl: WINDOW_SECONDS });
}

export async function clearLoginFailures(env: Env, ip: string): Promise<void> {
  await env.CARD_KV.delete(key(ip));
}
