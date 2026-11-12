import { describe, expect, it } from "vitest";
import { createSessionToken, verifySessionToken } from "../src/lib/session";
import { hashPassword, verifyPassword, checkPasswordStrength } from "../src/lib/password";
import { hasPermission } from "../src/lib/rbac";
import { ANONYMOUS, type AuthContext } from "../src/types";

const SECRET = "unit-test-secret";

function payload(overrides: Partial<{ exp: number; sub: string; sid: string }> = {}) {
  const now = Math.floor(Date.now() / 1000);
  return {
    sub: overrides.sub ?? "usr_1",
    sid: overrides.sid ?? "ses_1",
    iat: now,
    exp: overrides.exp ?? now + 600,
  };
}

describe("会话令牌", () => {
  it("签发后可验签并还原载荷", async () => {
    const token = await createSessionToken(SECRET, payload());
    const verified = await verifySessionToken(SECRET, token);
    expect(verified?.sub).toBe("usr_1");
    expect(verified?.sid).toBe("ses_1");
  });

  it("篡改载荷或签名会失败", async () => {
    const token = await createSessionToken(SECRET, payload());
    const parts = token.split(".");
    const tampered = [parts[0], parts[1], parts[3]].join(".");
    expect(await verifySessionToken(SECRET, tampered)).toBeNull();

    const forged = `${parts[0]}.${parts[1]}.${"A".repeat(43)}`;
    expect(await verifySessionToken(SECRET, forged)).toBeNull();
  });

  it("换密钥即失效", async () => {
    const token = await createSessionToken(SECRET, payload());
    expect(await verifySessionToken("another-secret", token)).toBeNull();
  });

  it("过期令牌被拒绝", async () => {
    const token = await createSessionToken(SECRET, payload({ exp: Math.floor(Date.now() / 1000) - 1 }));
    expect(await verifySessionToken(SECRET, token)).toBeNull();
  });

  it("兼容 cardadm.v1 前缀", async () => {
    const token = await createSessionToken(SECRET, payload());
    const swapped = token.replace(/^tpmsc\.v1/, "cardadm.v1");
    expect(await verifySessionToken(SECRET, swapped)).not.toBeNull();
  });
});

describe("口令哈希", () => {
  it("正确口令通过、错误口令失败", async () => {
    const record = await hashPassword("correct-horse-battery", 10_000);
    expect(record.iterations).toBe(10_000);
    expect(await verifyPassword("correct-horse-battery", record)).toBe(true);
    expect(await verifyPassword("wrong-password", record)).toBe(false);
  });

  it("同一口令每次盐不同", async () => {
    const a = await hashPassword("same-password", 10_000);
    const b = await hashPassword("same-password", 10_000);
    expect(a.salt).not.toBe(b.salt);
    expect(a.hash).not.toBe(b.hash);
  });

  it("强度校验拒绝弱口令", () => {
    expect(checkPasswordStrength("1234567890").ok).toBe(false);
    expect(checkPasswordStrength("short").ok).toBe(false);
    expect(checkPasswordStrength("Admin@2026!").ok).toBe(true);
  });
});

describe("权限判定", () => {
  const auth: AuthContext = {
    authenticated: true,
    via: "session",
    user: {
      id: "usr_1",
      username: "alice",
      displayName: null,
      roles: ["operator"],
      permissions: ["record:read", "cert:deliver"],
      mustChangePassword: false,
    },
  };

  it("有权限返回 true，无权限返回 false", () => {
    expect(hasPermission(auth, "record:read")).toBe(true);
    expect(hasPermission(auth, "record:delete")).toBe(false);
  });

  it("匿名永远无权限", () => {
    expect(hasPermission(ANONYMOUS, "record:read")).toBe(false);
  });
});
