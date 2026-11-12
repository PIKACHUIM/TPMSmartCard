import { describe, expect, it } from "vitest";
import { openWithCode, openWithPrivateKey, sealForCode, sealForPubkey } from "../src/lib/card-vault";
import { newSalt } from "../src/lib/card-code";
import { fromBase64, toBase64, toHex, utf8 } from "../src/lib/bytes";

/** AES-CBC 零 IV + PKCS#7：与 Python `Crypto.aes_encrypt` 相同的结构 */
describe("取件码模式加密", () => {
  it("加密后可解密回原文，且密文长度为 16 的整数倍", async () => {
    const salt = newSalt();
    const plaintext = utf8(JSON.stringify({ v: 1, pfx: "AA==", pfxkey: "pw", label: "demo" }));
    const sealed = await sealForCode("ABCD-EFGH-JKMN-PQRS", plaintext, salt.bytes, 1000);

    expect(sealed.kdf).toBe("PBKDF2-SHA256");
    expect(sealed.iterations).toBe(1000);
    const cipher = fromBase64(sealed.vaults);
    expect(cipher.length % 16).toBe(0);

    const opened = await openWithCode("abcd efgh jkmn pqrs", sealed);
    expect(new TextDecoder().decode(opened)).toBe(new TextDecoder().decode(plaintext));
  });

  it("换一个取件码解不开（PKCS#7 校验失败）", async () => {
    const salt = newSalt();
    const sealed = await sealForCode("ABCD-EFGH-JKMN-PQRS", utf8("secret"), salt.bytes, 1000);
    await expect(openWithCode("ZZZZ-ZZZZ-ZZZZ-ZZZZ", sealed)).rejects.toBeTruthy();
  });
});

const x25519Supported = await (async () => {
  try {
    const subtle = crypto.subtle as unknown as {
      generateKey(a: { name: string }, b: boolean, c: string[]): Promise<CryptoKeyPair>;
    };
    await subtle.generateKey({ name: "X25519" }, true, ["deriveBits"]);
    return true;
  } catch {
    return false;
  }
})();

describe.skipIf(!x25519Supported)("传输密钥模式加密", () => {
  it("服务端加密后客户端可用私钥解开", async () => {
    const subtle = crypto.subtle as unknown as {
      generateKey(a: { name: string }, b: boolean, c: string[]): Promise<CryptoKeyPair>;
      exportKey(format: string, key: CryptoKey): Promise<ArrayBuffer>;
    };
    const clientPair = await subtle.generateKey({ name: "X25519" }, true, ["deriveBits"]);
    const clientPub = toBase64(new Uint8Array(await subtle.exportKey("raw", clientPair.publicKey)));

    const plaintext = utf8("PKCS12-CONTENT");
    const sealed = await sealForPubkey(clientPub, plaintext);
    expect(fromBase64(sealed.pubkey).length).toBe(32);

    const opened = await openWithPrivateKey(sealed.pubkey, clientPair.privateKey, sealed.vaults);
    expect(toHex(opened)).toBe(toHex(plaintext));
  });
});
