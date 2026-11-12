// Package platform 定义跨平台卡片抽象。
//
// 设计原则：平台差异全部收敛到 Slot 实现与 Capability 上报，
// 上层（API / CLI / 前端）不出现 runtime.GOOS 判断。
package platform

import (
	"context"
	"errors"
	"io"
	"time"
)

// Kind 是卡片形态，与前端 CardInfo.kind 对应。
type Kind string

const (
	KindWindowsVSC     Kind = "windows_vsc"
	KindTPM2           Kind = "tpm2"
	KindDarwinKeychain Kind = "darwin_keychain"
	KindLocal          Kind = "local"
	KindCloud          Kind = "cloud"
)

// Security 是密钥安全等级；低等级必须显式标注，不能伪装成高等级。
type Security string

const (
	SecurityHigh   Security = "high"
	SecurityMedium Security = "medium"
	SecurityLow    Security = "low"
)

// Capability 由各平台实现上报，前端据此置灰并给出原因。
type Capability struct {
	CreateCard    bool `json:"create_card"`
	DeleteCard    bool `json:"delete_card"`
	SetPIN        bool `json:"set_pin"`
	TPMBacked     bool `json:"tpm_backed"`
	SecureEnclave bool `json:"secure_enclave"`
	Backup        bool `json:"backup"`
	SSH           bool `json:"ssh"`
	FIDO          bool `json:"fido"`
	ExportableKey bool `json:"exportable_key"`
}

// Card 是一张可用卡片（Windows 虚拟卡 / TPM2 token / 钥匙串条目）。
type Card struct {
	ID               string   `json:"id"`
	Name             string   `json:"name"`
	Kind             Kind     `json:"kind"`
	Platform         string   `json:"platform"`
	Security         Security `json:"security"`
	Reader           string   `json:"reader"`
	CertificateCount int      `json:"certificate_count"`
	CreatedAt        string   `json:"created_at"`
	LastUsedAt       string   `json:"last_used_at,omitempty"`
}

// Certificate 是卡上证书的展示视图。
type Certificate struct {
	ID            string   `json:"id"`
	CardID        string   `json:"card_id"`
	Subject       string   `json:"subject"`
	Issuer        string   `json:"issuer"`
	Serial        string   `json:"serial"`
	KeyAlgorithm  string   `json:"key_algorithm"`
	KeyUsage      []string `json:"key_usage"`
	NotBefore     string   `json:"not_before"`
	NotAfter      string   `json:"not_after"`
	Fingerprint   string   `json:"fingerprint"`
	HasPrivateKey bool     `json:"has_private_key"`
}

// SlotInfo 描述一个可用的卡槽。
type SlotInfo struct {
	ID         string     `json:"id"`
	Name       string     `json:"name"`
	Kind       Kind       `json:"kind"`
	Platform   string     `json:"platform"`
	Detail     string     `json:"detail"`
	Capability Capability `json:"capability"`
}

// CreateOptions 建卡参数。PIN/PUK 只发往本地后端。
type CreateOptions struct {
	Name     string
	PIN      string
	PUK      string
	AdminKey string
}

// ImportOptions 导入证书。
type ImportOptions struct {
	Reader string
	Path   string
	Label  string
	ID     string
	PIN    string
	Data   []byte
}

// KeyOptions 生成密钥（私钥永不导出）。
type KeyOptions struct {
	Algorithm string
	Bits      int
	Label     string
	PIN       string
}

// PublicKey 是密钥生成的返回：只有公钥与（可选的）CSR。
type PublicKey struct {
	Algorithm    string `json:"algorithm"`
	PublicKeyPEM string `json:"public_key_pem"`
	CSRPEM       string `json:"csr_pem,omitempty"`
}

// Slot 是平台抽象的核心接口。
type Slot interface {
	ID() string
	Kind() Kind
	Info(ctx context.Context) (SlotInfo, error)
	List(ctx context.Context) ([]Card, error)
	Create(ctx context.Context, opt CreateOptions) (Card, error)
	Delete(ctx context.Context, id string) error
	SetPIN(ctx context.Context, id, oldPIN, newPIN string) error
	ListCertificates(ctx context.Context, cardID string) ([]Certificate, error)
	ImportCertificate(ctx context.Context, cardID string, opt ImportOptions) error
	GenerateKey(ctx context.Context, cardID string, opt KeyOptions) (PublicKey, error)
	Sign(ctx context.Context, cardID, keyID string, digest []byte, mechanism string) ([]byte, error)
	Backup(ctx context.Context, cardID string, w io.Writer) error
}

// 统一错误：调用方据此映射成可读提示，而不是把 raw error 抛给用户。
var (
	ErrUnsupported  = errors.New("platform: 当前平台不支持该操作")
	ErrNotElevated  = errors.New("platform: 需要管理员权限")
	ErrRemoteSession = errors.New("platform: 不能在远程会话中操作虚拟智能卡（0x800704d3）")
	ErrNotFound     = errors.New("platform: 卡片或对象不存在")
	ErrPinRequired  = errors.New("platform: 该操作需要 PIN")
)

// Unsupported 返回带原因的错误（原因会原样展示给用户）。
func Unsupported(reason string) error {
	return errors.Join(ErrUnsupported, errors.New(reason))
}

// Now 统一时间格式，避免各平台各写一套。
func Now() string {
	return time.Now().UTC().Format(time.RFC3339)
}
