import type { AuditRow, RecordRow } from "@tpmsc/protocol";
import { useAppStore, type SessionUser } from "./store";
import type {
  AdminRole,
  AdminUser,
  BackupEntry,
  CardInfo,
  CertificateInfo,
  OverviewStat,
  SystemHealth,
} from "./types";
import * as mock from "./mock";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";
/** 桌面端与 Worker 都用同一份前端；离线时自动降级到演示数据，保证界面可评审 */
const ALLOW_DEMO = (import.meta.env.VITE_DISABLE_DEMO as string | undefined) !== "1";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal } = options;
  const token = useAppStore.getState().token;
  const headers: Record<string, string> = {
    // 本地后端用这个头做 CSRF 防线：跨站请求无法在不触发预检的情况下携带自定义头
    "X-Requested-With": "tpmsc",
  };
  if (body !== undefined) headers["content-type"] = "application/json";
  if (token) headers.authorization = `Bearer ${token}`;

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    credentials: "include",
    signal,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    parsed = JSON.parse(text) as unknown;
  }

  const envelope = parsed as
    | { done?: boolean; data?: unknown; error?: string; code?: string }
    | null;

  if (!response.ok || envelope?.done === false) {
    throw new ApiError(
      envelope?.error ?? `请求失败（HTTP ${response.status}）`,
      envelope?.code ?? "http_error",
      response.status,
    );
  }

  useAppStore.getState().setOnline(true);
  return (envelope && "data" in envelope ? envelope.data : parsed) as T;
}

function withDemo<T>(path: string, fallback: () => T, options?: RequestOptions): Promise<T> {
  return request<T>(path, options).catch((err: unknown) => {
    if (err instanceof ApiError) throw err;
    if (!ALLOW_DEMO) throw err;
    console.error("backend unreachable, falling back to demo data:", path, err);
    useAppStore.getState().setDemo(true);
    useAppStore.getState().setOnline(false);
    return fallback();
  });
}

export interface LoginResult {
  token: string;
  expires_at: string;
  user: SessionUser;
  policy: Record<string, unknown>;
}

export const api = {
  login(username: string, password: string): Promise<LoginResult> {
    return request<LoginResult>("/api/v1/auth/login", {
      method: "POST",
      body: { username, password },
    });
  },

  logout(): Promise<{ done: boolean }> {
    return request<{ done: boolean }>("/api/v1/auth/logout", { method: "POST" }).catch(() => ({ done: true }));
  },

  me(): Promise<{ user: SessionUser | null }> {
    return request("/api/v1/auth/me");
  },

  health(): Promise<SystemHealth> {
    return withDemo("/api/health", () => mock.mockHealth);
  },

  stats(): Promise<OverviewStat[]> {
    return withDemo("/api/v1/desktop/stats", () => mock.mockStats);
  },

  cards(): Promise<{ cards: CardInfo[] }> {
    return withDemo("/api/v1/desktop/cards", () => ({ cards: mock.mockCards }));
  },

  certificates(cardId?: string): Promise<{ certificates: CertificateInfo[] }> {
    const query = cardId ? `?card_id=${encodeURIComponent(cardId)}` : "";
    return withDemo(`/api/v1/desktop/certificates${query}`, () => ({
      certificates: cardId ? mock.mockCerts.filter((c) => c.card_id === cardId) : mock.mockCerts,
    }));
  },

  backups(): Promise<{ backups: BackupEntry[] }> {
    return withDemo("/api/v1/desktop/backups", () => ({ backups: mock.mockBackups }));
  },

  autostart(): Promise<{ enabled: boolean; detail: string; args: string }> {
    return withDemo("/api/v1/desktop/autostart", () => ({ enabled: true, detail: "", args: "--minimized" }));
  },

  setAutostart(enabled: boolean): Promise<{ enabled: boolean; detail: string }> {
    if (useAppStore.getState().demo) return Promise.resolve({ enabled, detail: "" });
    return request("/api/v1/desktop/autostart", { method: "POST", body: { enabled } });
  },

  records(query: { q?: string; mode?: string; state?: string; limit?: number; offset?: number } = {}): Promise<{
    rows: RecordRow[];
    total: number;
  }> {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== "") params.set(key, String(value));
    });
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return withDemo(`/api/v1/records${suffix}`, () => ({
      rows: mock.mockRecords.filter((row) => {
        if (query.mode && row.mode !== query.mode) return false;
        if (query.state && row.state !== query.state) return false;
        if (query.q && !`${row.label ?? ""}${row.common_name ?? ""}${row.serial_number ?? ""}`.includes(query.q)) return false;
        return true;
      }),
      total: mock.mockRecords.length,
    }));
  },

  deleteRecord(id: string): Promise<{ done: boolean }> {
    if (useAppStore.getState().demo) return Promise.resolve({ done: true });
    return request(`/api/v1/records/${encodeURIComponent(id)}`, { method: "DELETE" });
  },

  users(): Promise<{ users: AdminUser[] }> {
    return withDemo("/api/v1/users", () => ({ users: mock.mockUsers }));
  },

  createUser(payload: {
    username: string;
    password: string;
    display_name?: string;
    email?: string;
    roles: string[];
  }): Promise<{ id: string }> {
    return request("/api/v1/users", { method: "POST", body: payload });
  },

  updateUser(id: string, payload: { display_name?: string; status?: string; roles?: string[] }): Promise<{ done: boolean }> {
    return request(`/api/v1/users/${encodeURIComponent(id)}`, { method: "PATCH", body: payload });
  },

  roles(): Promise<{ roles: AdminRole[] }> {
    return withDemo("/api/v1/roles", () => ({ roles: mock.mockRoles }));
  },

  audit(query: { actor?: string; action?: string; limit?: number; offset?: number } = {}): Promise<{
    rows: AuditRow[];
    total: number;
  }> {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== "") params.set(key, String(value));
    });
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return withDemo(`/api/v1/audit${suffix}`, () => ({ rows: mock.mockAudit, total: mock.mockAudit.length }));
  },
};

export type { RecordRow, AuditRow };
