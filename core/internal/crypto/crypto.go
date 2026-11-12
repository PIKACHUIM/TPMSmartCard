// Package crypto 实现与 v1（Python）逐字节互通的取件码 / 传输密钥协议。
//
// 兼容性红线（改动前先看 docs/protocol.md）：
//   - 取件码规范化：去掉非 [0-9A-Z]，O→0、I→1、L→1（顺序不能变）
//   - 取件码密钥：PBKDF2-HMAC-SHA256(code, salt, iterations) → 32 字节
//   - 载荷加密：AES-256-CBC + 16 字节零 IV + PKCS#7
//   - 传输密钥：X25519 原始 32 字节公钥，共享密钥直接作为 AES-256 密钥
package crypto

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"regexp"
	"strings"
)

var (
	// ErrInvalidKey 表示 AES 密钥长度非法
	ErrInvalidKey = errors.New("crypto: AES 密钥必须是 16/24/32 字节")
	// ErrInvalidBlock 表示密文长度不是分组大小的整数倍
	ErrInvalidBlock = errors.New("crypto: 密文长度非法")
	// ErrPadding 表示 PKCS#7 填充非法（通常是密钥或 IV 错误）
	ErrPadding = errors.New("crypto: PKCS#7 填充非法")
)

var nonCode = regexp.MustCompile(`[^0-9A-Z]`)

// NormalizeCode 与 Python `Crypto.normalize_code` 完全一致。
func NormalizeCode(input string) string {
	upper := strings.ToUpper(input)
	text := nonCode.ReplaceAllString(upper, "")
	text = strings.ReplaceAll(text, "O", "0")
	text = strings.ReplaceAll(text, "I", "1")
	text = strings.ReplaceAll(text, "L", "1")
	return text
}

// FormatCode 把 16 位码按 4 位分组展示。
func FormatCode(code string) string {
	normalized := NormalizeCode(code)
	var parts []string
	for len(normalized) > 4 {
		parts = append(parts, normalized[:4])
		normalized = normalized[4:]
	}
	if normalized != "" {
		parts = append(parts, normalized)
	}
	return strings.Join(parts, "-")
}

// PBKDF2SHA256 是标准 PBKDF2 实现（没有引入 x/crypto，避免额外依赖）。
func PBKDF2SHA256(password, salt []byte, iterations, keyLen int) []byte {
	if iterations <= 0 {
		iterations = 1
	}
	hashLen := sha256.Size
	blocks := (keyLen + hashLen - 1) / hashLen
	out := make([]byte, 0, blocks*hashLen)
	buf := make([]byte, 4)
	for block := 1; block <= blocks; block++ {
		buf[0] = byte(block >> 24)
		buf[1] = byte(block >> 16)
		buf[2] = byte(block >> 8)
		buf[3] = byte(block)
		mac := hmac.New(sha256.New, password)
		mac.Write(salt)
		mac.Write(buf)
		u := mac.Sum(nil)
		t := make([]byte, len(u))
		copy(t, u)
		for i := 1; i < iterations; i++ {
			mac.Reset()
			mac.Write(u)
			u = mac.Sum(nil)
			for j := range t {
				t[j] ^= u[j]
			}
		}
		out = append(out, t...)
	}
	return out[:keyLen]
}

// CodeKey 由取件码派生 AES-256 密钥。
func CodeKey(code string, salt []byte, iterations int) []byte {
	return PBKDF2SHA256([]byte(NormalizeCode(code)), salt, iterations, 32)
}

func pkcs7Pad(data []byte, blockSize int) []byte {
	pad := blockSize - len(data)%blockSize
	out := make([]byte, len(data)+pad)
	copy(out, data)
	for i := len(data); i < len(out); i++ {
		out[i] = byte(pad)
	}
	return out
}

func pkcs7Unpad(data []byte, blockSize int) ([]byte, error) {
	if len(data) == 0 || len(data)%blockSize != 0 {
		return nil, ErrInvalidBlock
	}
	pad := int(data[len(data)-1])
	if pad == 0 || pad > blockSize || pad > len(data) {
		return nil, ErrPadding
	}
	for _, b := range data[len(data)-pad:] {
		if int(b) != pad {
			return nil, ErrPadding
		}
	}
	return data[:len(data)-pad], nil
}

// AESEncrypt 使用零 IV + PKCS#7，与 Python 版输出一致。
func AESEncrypt(key, plaintext []byte) ([]byte, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, ErrInvalidKey
	}
	iv := make([]byte, aes.BlockSize)
	padded := pkcs7Pad(plaintext, aes.BlockSize)
	out := make([]byte, len(padded))
	cipher.NewCBCEncrypter(block, iv).CryptBlocks(out, padded)
	return out, nil
}

// AESDecrypt 对应 AESEncrypt。
func AESDecrypt(key, ciphertext []byte) ([]byte, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, ErrInvalidKey
	}
	if len(ciphertext) == 0 || len(ciphertext)%aes.BlockSize != 0 {
		return nil, ErrInvalidBlock
	}
	iv := make([]byte, aes.BlockSize)
	out := make([]byte, len(ciphertext))
	cipher.NewCBCDecrypter(block, iv).CryptBlocks(out, ciphertext)
	return pkcs7Unpad(out, aes.BlockSize)
}

// Sealed 是 v1 上传接口的响应载荷。
type Sealed struct {
	Vaults    string
	PublicKey string
}

// SealForPublicKey 用客户端 X25519 公钥（Base64 原始字节）加密载荷。
func SealForPublicKey(clientPubBase64 string, plaintext []byte) (Sealed, error) {
	raw, err := base64.StdEncoding.DecodeString(strings.TrimSpace(clientPubBase64))
	if err != nil {
		return Sealed{}, fmt.Errorf("crypto: 公钥 Base64 非法: %w", err)
	}
	if len(raw) != 32 {
		return Sealed{}, fmt.Errorf("crypto: 公钥必须是 32 字节，实际 %d", len(raw))
	}
	curve := ecdh.X25519()
	clientPub, err := curve.NewPublicKey(raw)
	if err != nil {
		return Sealed{}, err
	}
	serverPriv, err := curve.GenerateKey(rand.Reader)
	if err != nil {
		return Sealed{}, err
	}
	shared, err := serverPriv.ECDH(clientPub)
	if err != nil {
		return Sealed{}, err
	}
	ciphertext, err := AESEncrypt(shared, plaintext)
	if err != nil {
		return Sealed{}, err
	}
	return Sealed{
		Vaults:    base64.StdEncoding.EncodeToString(ciphertext),
		PublicKey: base64.StdEncoding.EncodeToString(serverPriv.PublicKey().Bytes()),
	}, nil
}

// OpenWithPublicKey 用客户端私钥解开 v1 载荷（客户端取回时使用）。
func OpenWithPublicKey(clientPriv *ecdh.PrivateKey, serverPubBase64, vaultsBase64 string) ([]byte, error) {
	raw, err := base64.StdEncoding.DecodeString(strings.TrimSpace(serverPubBase64))
	if err != nil {
		return nil, err
	}
	serverPub, err := ecdh.X25519().NewPublicKey(raw)
	if err != nil {
		return nil, err
	}
	shared, err := clientPriv.ECDH(serverPub)
	if err != nil {
		return nil, err
	}
	ciphertext, err := base64.StdEncoding.DecodeString(vaultsBase64)
	if err != nil {
		return nil, err
	}
	return AESDecrypt(shared, ciphertext)
}

// OpenWithCode 用取件码解开 v2 载荷。
func OpenWithCode(code, vaultsBase64, saltBase64 string, iterations int) ([]byte, error) {
	salt, err := base64.StdEncoding.DecodeString(saltBase64)
	if err != nil {
		return nil, err
	}
	ciphertext, err := base64.StdEncoding.DecodeString(vaultsBase64)
	if err != nil {
		return nil, err
	}
	return AESDecrypt(CodeKey(code, salt, iterations), ciphertext)
}

// SealWithCode 主要供测试与自检使用。
func SealWithCode(code string, salt []byte, iterations int, plaintext []byte) (string, error) {
	ciphertext, err := AESEncrypt(CodeKey(code, salt, iterations), plaintext)
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(ciphertext), nil
}

// NewSalt 生成 16 字节盐。
func NewSalt() []byte {
	salt := make([]byte, 16)
	if _, err := rand.Read(salt); err != nil {
		panic(err)
	}
	return salt
}
