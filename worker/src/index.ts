import { Hono } from "hono";
import { cors } from "hono/cors";
import { logger } from "hono/logger";
import type { AppEnv } from "./env";
import { loadAuth } from "./lib/rbac";
import { mountHealthRoutes } from "./routes/health";
import { mountAuthRoutes } from "./routes/auth";
import { mountCardRoutes } from "./routes/card";
import { mountLegacyAdminRoutes } from "./routes/legacy-admin";
import { mountAdminRoutes } from "./routes/admin";
import { mountDeliveryRoutes } from "./routes/delivery";

/**
 * Worker 入口。
 *
 * 路由分工：
 *   /card/*    —— 智能卡证书分发（与 PikaTestCert / SmartCardWEB.py 协议兼容）
 *   /api/v1/*  —— 管理台 API（登录、用户、角色、记录、审计、投递）
 *   /api/health —— 健康检查
 *   其余请求    —— 交给 Workers Static Assets（React 管理台 / 上传页），SPA 兜底
 */
const app = new Hono<AppEnv>();

app.use("*", logger());
app.use("*", async (c, next) => {
  c.set("requestId", crypto.randomUUID());
  await next();
  c.header("X-Content-Type-Options", "nosniff");
  c.header("Referrer-Policy", "same-origin");
  c.header("X-Frame-Options", "DENY");
});

const allowMethods = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"];
const allowHeaders = [
  "Content-Type",
  "Authorization",
  "X-Admin-Token",
  "Idempotency-Key",
  "X-Client-Id",
  "X-Timestamp",
  "X-Nonce",
  "X-Signature",
];

// 管理台 API：只允许同源（带 Cookie 时不回显任意 Origin）
app.use(
  "/api/*",
  cors({
    origin: (origin, c) => (origin === new URL(c.req.url).origin ? origin : new URL(c.req.url).origin),
    credentials: true,
    allowMethods,
    allowHeaders,
    exposeHeaders: ["Content-Disposition"],
    maxAge: 600,
  }),
);
// 智能卡客户端：旧版工具不发送 Origin，保持宽松
app.use(
  "/card/*",
  cors({
    origin: "*",
    allowMethods,
    allowHeaders,
    exposeHeaders: ["Content-Disposition"],
    maxAge: 600,
  }),
);

// 认证上下文全站解析一次：有凭证才查库，匿名请求只是一次空判断
app.use("*", loadAuth);

mountHealthRoutes(app);
mountAuthRoutes(app);
mountCardRoutes(app);
mountLegacyAdminRoutes(app);
mountAdminRoutes(app);
mountDeliveryRoutes(app);

app.onError((err, c) => {
  console.error("unhandled error", c.req.method, c.req.path, err);
  const path = c.req.path;
  if (path.startsWith("/api/") || path.startsWith("/card/")) {
    return c.json(
      { done: false, error: "服务端异常", code: "internal_error" },
      500,
    );
  }
  return c.text("Internal Server Error", 500);
});

app.notFound(async (c) => {
  const path = c.req.path;
  if (path.startsWith("/api/") || path.startsWith("/card/")) {
    return c.json({ done: false, error: "接口不存在", code: "not_found" }, 404);
  }
  // 静态资源优先；找不到时回退 SPA 入口
  if (c.env.ASSETS) {
    const asset = await c.env.ASSETS.fetch(c.req.raw);
    if (asset.status !== 404) return asset;
  }
  return c.text("Not Found", 404);
});

export default app;
