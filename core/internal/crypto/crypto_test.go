package crypto

import (
	"bytes"
	"crypto/ecdh"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"testing"
)

func TestNormalizeCode(t *testing.T) {
	cases := []struct{ in, want string }{
		{"abcd-efgh jkmn/pqrs", "ABCDEFGHJKMNPQRS"},
		{"OIL", "011"},
		{"i-l-o", "110"},
		{"中文@@@", ""},
	}
	for _, c := range cases {
		if got := NormalizeCode(c.in); got != c.want {
			t.Fatalf("NormalizeCode(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestPBKDF2Vector(t *testing.T) {
	// RFC 7914 §11：PBKDF2-HMAC-SHA256("password", "salt", 1, 32)
	got := PBKDF2SHA256([]byte("password"), []byte("salt"), 1, 32)
	want := "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b"
	if hex.EncodeToString(got) != want {
		t.Fatalf("PBKDF2 = %x, want %s", got, want)
	}
}

func TestAESRoundTrip(t *testing.T) {
	key := bytes.Repeat([]byte{0x2a}, 32)
	plaintext := []byte(`{"v":1,"pfx":"AA==","pfxkey":"pw"}`)
	ciphertext, err := AESEncrypt(key, plaintext)
	if err != nil {
		t.Fatal(err)
	}
	if len(ciphertext)%16 != 0 {
		t.Fatalf("ciphertext length %d", len(ciphertext))
	}
	opened, err := AESDecrypt(key, ciphertext)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(opened, plaintext) {
		t.Fatalf("round trip mismatch")
	}
}

func TestCodeModeRoundTrip(t *testing.T) {
	salt := NewSalt()
	plaintext := []byte("payload")
	vaults, err := SealWithCode("ABCD-EFGH-JKMN-PQRS", salt, 1000, plaintext)
	if err != nil {
		t.Fatal(err)
	}
	opened, err := OpenWithCode("abcd efgh jkmn pqrs", vaults, base64.StdEncoding.EncodeToString(salt), 1000)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(opened, plaintext) {
		t.Fatal("code round trip mismatch")
	}
	if _, err := OpenWithCode("ZZZZ-ZZZZ-ZZZZ-ZZZZ", vaults, base64.StdEncoding.EncodeToString(salt), 1000); err == nil {
		t.Fatal("expected decryption failure with wrong code")
	}
}

func TestX25519SealOpen(t *testing.T) {
	curve := ecdh.X25519()
	clientPriv, err := curve.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	clientPub := base64.StdEncoding.EncodeToString(clientPriv.PublicKey().Bytes())

	plaintext := []byte("PKCS12-BYTES")
	sealed, err := SealForPublicKey(clientPub, plaintext)
	if err != nil {
		t.Fatal(err)
	}
	opened, err := OpenWithPublicKey(clientPriv, sealed.PublicKey, sealed.Vaults)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(opened, plaintext) {
		t.Fatal("x25519 round trip mismatch")
	}
}

func TestSealRejectsBadKey(t *testing.T) {
	if _, err := SealForPublicKey("not-base64", []byte("x")); err == nil {
		t.Fatal("expected error")
	}
	if _, err := SealForPublicKey(base64.StdEncoding.EncodeToString([]byte("short")), []byte("x")); err == nil {
		t.Fatal("expected length error")
	}
}
