/**
 * Worker 运行时环境。
 *
 * 约定：所有数值型配置都以字符串进入（wrangler 的 [vars] 只能是字符串），
 * 由 `settings.ts` 统一解析并钳制，避免各路由各写一套 parseInt。
 */
export interface Env {
  /** D1：用户 / 角色 / 记录 / 审计 / 服务客户端 */
  DB: D1Database;
  /** KV：证书密文载荷（v1: card:v1:*，v2: card:v2:code:*） */
  CARD_KV: KVNamespace;
  /** 前端静态资源（wrangler [assets]） */
  ASSETS?: Fetcher;

  /** 会话 HMAC 密钥；未配置时回退 CARD_ADMIN_PASSWORD */
  SESSION_SECRET?: string;
  /** 引导管理员口令（首次部署登录用，也是旧管理接口的兼容凭据） */
  CARD_ADMIN_PASSWORD?: string;
  /** 旧版静态管理令牌 */
  CARD_ADMIN_TOKEN?: string;
  /** 取件码 pepper 的次级回退 */
  CARD_MASTER_KEY?: string;
  /** 取件码指纹 pepper */
  CARD_CODE_PEPPER?: string;

  CARD_ALLOW_ANONYMOUS?: string;
  CARD_TTL_SECONDS?: string;
  CARD_CODE_TTL_SECONDS?: string;
  CARD_CODE_USES?: string;
  CARD_CODE_ITERATIONS?: string;
  CARD_MAX_BYTES?: string;
  CARD_ADMIN_SESSION_SECONDS?: string;
  CARD_LOGIN_MAX_FAILURES?: string;

  /** 外部投递客户端的 ID（默认 opencert） */
  DELIVERY_CLIENT_ID?: string;
  /** 外部投递客户端的 HMAC 密钥 */
  DELIVERY_CLIENT_SECRET?: string;

  /** 密码哈希迭代次数（默认 100000，免费套餐可下调） */
  PBKDF2_ITERATIONS?: string;
}

/** Hono 上下文变量 */
export interface Variables {
  auth: import("./types").AuthContext;
  requestId: string;
}

export type AppEnv = { Bindings: Env; Variables: Variables };
