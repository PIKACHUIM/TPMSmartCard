// Package cloud 实现证书取回客户端（v1 传输密钥 / v2 取件码）。
//
// 与 Worker 的契约见 docs/protocol.md；两种模式最终都得到同一份 JSON：
//   {"v":1,"pfx":"<base64>","pfxkey":"…","label":"…"}    // PKCS#12
//   {"v":2,"cert_pem":"…","key_pem":"…","chain_pem":"…"}  // OpenCertRepo 投递
package cloud

import (
	"context"
	"crypto/ecdh"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/PIKACHUIM/tpmsmartcard/internal/crypto"
	"github.com/PIKACHUIM/tpmsmartcard/internal/protocol"
)

// Client 是下发服务的客户端。
type Client struct {
	BaseURL string
	HTTP    *http.Client
}

// New 构造客户端；BaseURL 形如 https://card.example.com。
func New(baseURL string) *Client {
	return &Client{
		BaseURL: strings.TrimRight(baseURL, "/"),
		HTTP:    &http.Client{Timeout: 30 * time.Second},
	}
}

type envelope struct {
	Flag bool            `json:"flag"`
	Data json.RawMessage `json:"data"`
}

type vaultData struct {
	Vaults     string `json:"vaults"`
	Pubkey     string `json:"pubkey"`
	PfxKey     string `json:"pfxkey"`
	Salt       string `json:"salt"`
	Iterations int    `json:"iterations"`
	KDF        string `json:"kdf"`
	Label      string `json:"label"`
	Contains   string `json:"contains"`
	Remaining  int    `json:"remaining"`
}

// Delivered 是解密后的载荷。
type Delivered struct {
	Payload   []byte
	PFXKey    string
	Label     string
	Contains  string
	Remaining int
	Raw       string
}

// DecodedPayload 是明文 JSON 结构，便于调用方决定如何导入卡片。
type DecodedPayload struct {
	Version  int    `json:"v"`
	PFX      string `json:"pfx"`
	PFXKey   string `json:"pfxkey"`
	Label    string `json:"label"`
	CertPEM  string `json:"cert_pem"`
	KeyPEM   string `json:"key_pem"`
	ChainPEM string `json:"chain_pem"`
}

// FetchByCode 用取件码取回并解密。
func (c *Client) FetchByCode(ctx context.Context, code string) (Delivered, error) {
	query := url.Values{"code": []string{code}}
	raw, err := c.get(ctx, protocol.PathGetCertByCode, query)
	if err != nil {
		// 兼容只实现 /card/get/cert 的旧部署
		raw, err = c.get(ctx, protocol.PathGetCertByKey, query)
		if err != nil {
			return Delivered{}, err
		}
	}
	if raw.Salt == "" {
		return Delivered{}, fmt.Errorf("服务端返回缺少 salt：该记录可能不是取件码模式")
	}
	payload, err := crypto.OpenWithCode(code, raw.Vaults, raw.Salt, raw.Iterations)
	if err != nil {
		return Delivered{}, fmt.Errorf("取件码解密失败（码错误或已过期）: %w", err)
	}
	return Delivered{
		Payload:   payload,
		Label:     raw.Label,
		Contains:  raw.Contains,
		Remaining: raw.Remaining,
		Raw:       raw.Vaults,
	}, nil
}

// FetchByPublicKey 生成一次性 X25519 密钥对并取回。
func (c *Client) FetchByPublicKey(ctx context.Context, baseURL string) (Delivered, error) {
	curve := ecdh.X25519()
	privateKey, err := curve.GenerateKey(rand.Reader)
	if err != nil {
		return Delivered{}, err
	}
	publicKey := base64.StdEncoding.EncodeToString(privateKey.PublicKey().Bytes())

	form := url.Values{"pubkey": []string{publicKey}}
	body, status, err := c.postForm(ctx, protocol.PathGetCertByKey, form)
	if err != nil {
		return Delivered{}, err
	}
	if status != http.StatusOK {
		return Delivered{}, fmt.Errorf("服务端返回 HTTP %d", status)
	}
	raw, err := parseVault(body)
	if err != nil {
		return Delivered{}, err
	}
	payload, err := crypto.OpenWithPublicKey(privateKey, raw.Pubkey, raw.Vaults)
	if err != nil {
		return Delivered{}, fmt.Errorf("传输密钥解密失败: %w", err)
	}
	return Delivered{
		Payload:  payload,
		PFXKey:   raw.PfxKey,
		Label:    raw.Label,
		Contains: raw.Contains,
		Raw:      raw.Vaults,
	}, nil
}

// Decode 解析明文载荷。
func Decode(payload []byte) (DecodedPayload, error) {
	var decoded DecodedPayload
	if err := json.Unmarshal(payload, &decoded); err != nil {
		return decoded, fmt.Errorf("载荷不是合法 JSON: %w", err)
	}
	return decoded, nil
}

func (c *Client) get(ctx context.Context, path string, query url.Values) (vaultData, error) {
	endpoint := c.BaseURL + path + "?" + query.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return vaultData{}, err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return vaultData{}, fmt.Errorf("请求下发服务失败: %w", err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 32<<20))
	if err != nil {
		return vaultData{}, err
	}
	return parseVault(body)
}

func (c *Client) postForm(ctx context.Context, path string, form url.Values) ([]byte, int, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.BaseURL+path, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, 0, fmt.Errorf("请求下发服务失败: %w", err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 32<<20))
	return body, resp.StatusCode, err
}

func parseVault(body []byte) (vaultData, error) {
	var env envelope
	if err := json.Unmarshal(body, &env); err != nil {
		return vaultData{}, fmt.Errorf("响应不是合法 JSON: %w", err)
	}
	if !env.Flag || len(env.Data) == 0 || string(env.Data) == "null" {
		return vaultData{}, fmt.Errorf("未找到可用的证书记录（可能已过期、用尽或取件码错误）")
	}
	var data vaultData
	if err := json.Unmarshal(env.Data, &data); err != nil {
		return vaultData{}, fmt.Errorf("解析证书记录失败: %w", err)
	}
	if data.Vaults == "" {
		return vaultData{}, fmt.Errorf("响应缺少 vaults 字段")
	}
	if data.Iterations <= 0 {
		data.Iterations = 100_000
	}
	return data, nil
}
