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

  /** 导入公钥证书（PEM）。私钥必须在 TPM / Secure Enclave 内生成，不能经网络传输。 */
  importCertificate(input: {
    card_id: string;
    pem: string;
    pin?: string;
    label?: string;
  }): Promise<{ imported: boolean; subject: string; serial: string }> {
    if (useAppStore.getState().demo) {
      return Promise.resolve({ imported: true, subject: "CN=演示证书", serial: "2A" });
    }
    return request("/api/v1/desktop/certificates", { method: "POST", body: input });
  },

  /** 导出证书 PEM（只含公钥证书）。 */
  async exportCertificate(cardId: string, certId: string): Promise<string> {
    if (useAppStore.getState().demo) {
      return `-----BEGIN CERTIFICATE-----\nMIIB演示数据仅用于演示模式导出\n-----END CERTIFICATE-----\n`;
    }
    const response = await fetch(
      `${API_BASE}/api/v1/desktop/certificates/${encodeURIComponent(certId)}/pem?card_id=${encodeURIComponent(cardId)}`,
      { headers: { "X-Requested-With": "tpmsc" }, credentials: "include" },
    );
    if (!response.ok) {
      throw new ApiError(`导出失败（HTTP ${response.status}）`, "export_failed", response.status);
    }
    return response.text();
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

  /**
   * 从管理台上传 PFX（走与桌面端相同的 /card/put/cert 协议）。
   * 注意：这个接口返回 `{flag,data}` 而不是标准包络，所以单独实现。
   */
  async uploadCertificate(input: {
    mode: "code" | "key";
    file: File;
    pfxKey: string;
    pubkey?: string;
    code?: string;
    ttlHours: number;
    maxUses: number;
    label?: string;
  }): Promise<{ id: string; code?: string; expires_at?: string; max_uses: number }> {
    const form = new FormData();
    form.set("vaults", input.file);
    form.set("pfxkey", input.pfxKey);
    form.set("mode", input.mode);
    form.set("ttl", String(Math.max(0, Math.round(input.ttlHours * 3600))));
    form.set("max_uses", String(input.maxUses));
    if (input.label) form.set("label", input.label);
    if (input.mode === "key" && input.pubkey) form.set("pubkey", input.pubkey.trim());
    if (input.mode === "code" && input.code) form.set("code", input.code.trim());

    const response = await fetch(`${API_BASE}/card/put/cert`, {
      method: "POST",
      headers: { "X-Requested-With": "tpmsc" },
      credentials: "include",
      body: form,
    });
    const body = (await response.json().catch(() => null)) as
      | { flag?: boolean; data?: { error?: string; id?: string; code?: string; expires_at?: string; max_uses?: number } }
      | null;
    if (!response.ok || !body?.flag) {
      throw new ApiError(body?.data?.error ?? `上传失败（HTTP ${response.status}）`, "upload_failed", response.status);
    }
    return {
      id: body.data?.id ?? "",
      code: body.data?.code,
      expires_at: body.data?.expires_at,
      max_uses: body.data?.max_uses ?? input.maxUses,
    };
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

  createRole(payload: {
    name: string;
    description?: string;
    permissions: string[];
  }): Promise<{ id: string; name: string; permissions: string[] }> {
    return request("/api/v1/roles", { method: "POST", body: payload });
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
