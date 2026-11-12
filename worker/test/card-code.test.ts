import { describe, expect, it } from "vitest";
import {
  codeFingerprint,
  deriveCodeKey,
  formatCode,
  generateCode,
  normalizeCode,
  pbkdf2Sha256,
  validateCustomCode,
} from "../src/lib/card-code";
import { toHex, utf8 } from "../src/lib/bytes";

/**
 * 取件码必须与 Python `Module/Cryptography.py` 行为一致：
 *   normalize_code: 去非 [0-9A-Z] → O→0、I→1、L→1
 *   code_key:       PBKDF2-SHA256(code, salt, iterations, 32)
 */
describe("normalizeCode", () => {
  it("忽略大小写与分隔符", () => {
    expect(normalizeCode("abcd-efgh jkmn/pqrs")).toBe("ABCDEFGHJKMNPQRS");
  });

  it("把易混字符归一化（顺序 O→0、I→1、L→1，与 Python 一致）", () => {
    expect(normalizeCode("OIL")).toBe("011");
    // ILO：先 O→0 得 IL0，再 I→1 得 1L0，最后 L→1 得 110
    expect(normalizeCode("i-l-o")).toBe("110");
  });

  it("空值与非法输入不抛异常", () => {
    expect(normalizeCode(null)).toBe("");
    expect(normalizeCode("中文@@@")).toBe("");
  });
});

describe("formatCode / generateCode", () => {
  it("每 4 位分组", () => {
    expect(formatCode("ABCDEFGHJKMNPQRS")).toBe("ABCD-EFGH-JKMN-PQRS");
  });

  it("生成 16 位、且字母表不含 I/L/O", () => {
    for (let i = 0; i < 50; i += 1) {
      const code = generateCode();
      expect(code).toMatch(/^[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}$/);
      expect(code).not.toMatch(/[ILO]/);
    }
  });
});

describe("validateCustomCode", () => {
  it("拒绝低强度取件码", () => {
    expect(validateCustomCode("1111111111111111").ok).toBe(false);
    expect(validateCustomCode("ABABABABABABABAB").ok).toBe(false);
    expect(validateCustomCode("short").ok).toBe(false);
  });

  it("接受 8 个以上不同字符", () => {
    expect(validateCustomCode("ABCD-EFGH-JKMN-PQRS").ok).toBe(true);
  });
});

describe("PBKDF2-SHA256", () => {
  it("匹配 RFC 7914 §11 向量（与 hashlib 一致）", async () => {
    const key = await pbkdf2Sha256(utf8("password"), utf8("salt"), 1);
    expect(toHex(key)).toBe(
      "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b",
    );
  });

  it("取件码派生稳定且为 32 字节", async () => {
    const salt = new Uint8Array(16).fill(7);
    const a = await deriveCodeKey("ABCD-EFGH-JKMN-PQRS", salt, 1000);
    const b = await deriveCodeKey("abcd efgh jkmn pqrs", salt, 1000);
    expect(a.length).toBe(32);
    expect(toHex(a)).toBe(toHex(b));
  });

  it("指纹不可逆且与码归一化相关", async () => {
    const a = await codeFingerprint("ABCD-EFGH-JKMN-PQRS", "pepper");
    const b = await codeFingerprint("abcd efgh jkmn pqrs", "pepper");
    const c = await codeFingerprint("ABCD-EFGH-JKMN-PQRS", "other-pepper");
    expect(a).toBe(b);
    expect(a).not.toBe(c);
    expect(a).toHaveLength(64);
  });
});
