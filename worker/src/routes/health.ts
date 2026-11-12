import type { Context, Hono } from "hono";
import type { AppEnv } from "../env";
import { settings } from "../lib/settings";

/** 健康检查：同时探测 D1 与 KV，失败也要给出可读原因而不是 500 */
export function mountHealthRoutes(app: Hono<AppEnv>): void {
  app.get("/api/health", handleHealth);
  app.get("/api/v1/health", handleHealth);
}

async function handleHealth(c: Context<AppEnv>) {
  const started = Date.now();
  let db: { ok: boolean; detail?: string } = { ok: false };
  let kv: { ok: boolean; detail?: string } = { ok: false };

  try {
    await c.env.DB.prepare("SELECT 1 AS ok").first();
    db = { ok: true };
  } catch (err) {
    db = { ok: false, detail: err instanceof Error ? err.message : String(err) };
  }

  try {
    await c.env.CARD_KV.get("health:probe");
    kv = { ok: true };
  } catch (err) {
    kv = { ok: false, detail: err instanceof Error ? err.message : String(err) };
  }

  const cfg = settings(c.env);
  return c.json(
    {
      done: true,
      service: "tpmsmartcard-worker",
      version: "2.0.0",
      ts: new Date().toISOString(),
      latency_ms: Date.now() - started,
      db,
      kv,
      policy: {
        allow_anonymous: cfg.allowAnonymous,
        code_iterations: cfg.codeIterations,
        session_seconds: cfg.sessionSeconds,
      },
      routes: [
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/records",
        "/api/v1/audit",
        "/api/v1/deliveries",
        "/card/get/cert",
        "/card/put/cert",
        "/card/get/code",
        "/card/put/code",
        "/card/web/cert",
      ],
    },
    db.ok && kv.ok ? 200 : 503,
  );
}
