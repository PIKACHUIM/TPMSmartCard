/** 时间工具：全站统一用 UTC ISO 字符串落库，避免 D1 与浏览器时区错位。 */

export function nowIso(): string {
  return new Date().toISOString();
}

export function isoFromSeconds(seconds: number): string {
  return new Date(Date.now() + seconds * 1000).toISOString();
}

export function isoFromMs(ms: number): string {
  return new Date(ms).toISOString();
}

export function isExpired(value: string | null | undefined): boolean {
  if (!value) return false;
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return true;
  return ts <= Date.now();
}

/** 剩余秒数（已过期返回 0） */
export function secondsLeft(value: string | null | undefined): number {
  if (!value) return 0;
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return 0;
  return Math.max(0, Math.floor((ts - Date.now()) / 1000));
}
