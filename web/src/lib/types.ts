/** 前端使用的领域类型（与后端 JSON 对齐，命名保持 snake_case 以免两层转换） */

export type PlatformKind = "windows" | "linux" | "macos" | "web";

export interface Capability {
  create_card: boolean;
  delete_card: boolean;
  set_pin: boolean;
  tpm_backed: boolean;
  secure_enclave: boolean;
  backup: boolean;
  ssh: boolean;
  fido: boolean;
  exportable_key: boolean;
}

export interface CardInfo {
  id: string;
  name: string;
  kind: "windows_vsc" | "tpm2" | "darwin_keychain" | "local" | "cloud";
  platform: PlatformKind;
  security: "high" | "medium" | "low";
  reader: string | null;
  certificate_count: number;
  created_at: string;
  last_used_at: string | null;
}

export interface CertificateInfo {
  id: string;
  card_id: string;
  subject: string;
  issuer: string;
  serial: string;
  key_algorithm: string;
  key_usage: string[];
  not_before: string;
  not_after: string;
  fingerprint: string;
  has_private_key: boolean;
}

export interface BackupEntry {
  id: string;
  file: string;
  card_name: string;
  created_at: string;
  size_bytes: number;
  /** certificates = 只含公钥证书与元数据（当前默认），私钥永不导出 */
  protected_by: "dpapi" | "tpm2" | "keychain" | "passphrase" | "certificates";
  key_exportable: boolean;
  status: "verified" | "unverified" | "failed";
  warnings?: string[];
  certificates?: number;
}

export interface SystemHealth {
  platform: PlatformKind;
  tpm: { present: boolean; version: string | null; detail: string };
  reader: { present: boolean; readers: string[] };
  secure_enclave: { available: boolean; detail: string };
  backend: { version: string; uptime_seconds: number };
  capability: Capability;
}

export interface OverviewStat {
  label: string;
  value: string;
  hint: string;
  trend?: number[];
}

export interface AdminUser {
  id: string;
  username: string;
  display_name: string | null;
  email: string | null;
  roles: string[];
  status: "active" | "disabled";
  must_change_password: number;
  created_at: string;
  last_login_at: string | null;
}

export interface AdminRole {
  id: string;
  name: string;
  description: string | null;
  builtin: number;
  permissions: string[];
}
