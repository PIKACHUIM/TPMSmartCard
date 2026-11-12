//go:build darwin

// Package darwin 实现 macOS 的「钥匙串 + 安全隔区」卡槽。
//
// 事实约束（必须显式呈现给用户，不能伪装成功能对等）：
//   - macOS 没有 Windows 虚拟智能卡，也没有 tpmvscmgr；
//   - 私钥由 Secure Enclave（T1/T2 或 Apple Silicon）生成时**永不导出**；
//   - Secure Enclave 只支持 P-256 ECDSA，RSA 必须降级为钥匙串软件密钥；
//   - 备份只能包含证书、证书链与元数据。
package darwin

import (
	"context"
	"crypto/sha1"
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"io"
	"os/exec"
	"strings"

	"github.com/PIKACHUIM/tpmsmartcard/internal/platform"
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform/p11"
)

// Slot 是 macOS 的钥匙串卡槽。
type Slot struct {
	p11      *p11.Backend
	security string
}

// New 探测 security 命令与 OpenSC。
func New() *Slot {
	path, _ := exec.LookPath("security")
	backend, _ := p11.Detect()
	return &Slot{p11: backend, security: path}
}

func (s *Slot) ID() string          { return "darwin-keychain" }
func (s *Slot) Kind() platform.Kind { return platform.KindDarwinKeychain }

func (s *Slot) Info(ctx context.Context) (platform.SlotInfo, error) {
	detail := "未找到 security 命令（需要 Xcode Command Line Tools）"
	if s.security != "" {
		detail = "钥匙串可用；Secure Enclave 需 Developer ID 签名与 cgo 构建"
	}
	return platform.SlotInfo{
		ID:       s.ID(),
		Name:     "钥匙串 + Secure Enclave",
		Kind:     s.Kind(),
		Platform: "macos",
		Detail:   detail,
		Capability: platform.Capability{
			// macOS 不能创建「虚拟智能卡」；CreateCard 表示创建钥匙串条目
			CreateCard:    s.security != "",
			DeleteCard:    s.security != "",
			SetPIN:        false,
			TPMBacked:     false,
			SecureEnclave: false,
			Backup:        false,
			SSH:           s.security != "",
			FIDO:          true,
		},
	}, nil
}

func (s *Slot) List(ctx context.Context) ([]platform.Card, error) {
	if s.security == "" {
		return nil, nil
	}
	certs, err := s.ListCertificates(ctx, "login")
	if err != nil {
		return nil, err
	}
	return []platform.Card{{
		ID:               "login",
		Name:             "登录钥匙串",
		Kind:             platform.KindDarwinKeychain,
		Platform:         "macos",
		Security:         platform.SecurityMedium,
		Reader:           "Keychain",
		CertificateCount: len(certs),
		CreatedAt:        platform.Now(),
	}}, nil
}

func (s *Slot) Create(ctx context.Context, opt platform.CreateOptions) (platform.Card, error) {
	return platform.Card{}, platform.Unsupported("macOS 不支持创建虚拟智能卡：请使用钥匙串条目 + 云端下发证书")
}

func (s *Slot) Delete(ctx context.Context, id string) error {
	return platform.Unsupported("macOS 卡槽不提供整卡删除；请在钥匙串访问中删除条目")
}

func (s *Slot) SetPIN(ctx context.Context, id, oldPIN, newPIN string) error {
	return platform.Unsupported("钥匙串没有 PIN/PUK 语义：由系统登录密码与 Touch ID 控制访问")
}

func (s *Slot) ListCertificates(ctx context.Context, cardID string) ([]platform.Certificate, error) {
	if s.security == "" {
		return nil, platform.Unsupported("未找到 security 命令")
	}
	out, err := exec.CommandContext(ctx, s.security, "find-certificate", "-a", "-p").Output()
	if err != nil {
		return nil, fmt.Errorf("读取钥匙串证书失败: %w", err)
	}
	var certs []platform.Certificate
	rest := out
	for {
		block, remaining := pem.Decode(rest)
		if block == nil {
			break
		}
		rest = remaining
		if block.Type != "CERTIFICATE" {
			continue
		}
		parsed, err := x509.ParseCertificate(block.Bytes)
		if err != nil {
			continue
		}
		sum := sha1.Sum(parsed.Raw)
		certs = append(certs, platform.Certificate{
			ID:            fmt.Sprintf("%X", parsed.SerialNumber),
			CardID:        cardID,
			Subject:       parsed.Subject.String(),
			Issuer:        parsed.Issuer.String(),
			Serial:        strings.ToUpper(fmt.Sprintf("%X", parsed.SerialNumber)),
			KeyAlgorithm:  parsed.PublicKeyAlgorithm.String(),
			KeyUsage:      []string{"digitalSignature"},
			NotBefore:     parsed.NotBefore.UTC().Format("2006-01-02T15:04:05Z"),
			NotAfter:      parsed.NotAfter.UTC().Format("2006-01-02T15:04:05Z"),
			Fingerprint:   strings.ToUpper(fmt.Sprintf("%X", sum)),
			HasPrivateKey: false,
		})
	}
	return certs, nil
}

func (s *Slot) ExportCertificate(ctx context.Context, cardID, certID string) ([]byte, error) {
	if s.security == "" {
		return nil, platform.Unsupported("未找到 security 命令")
	}
	out, err := exec.CommandContext(ctx, s.security, "find-certificate", "-a", "-p").Output()
	if err != nil {
		return nil, fmt.Errorf("读取钥匙串证书失败: %w", err)
	}
	rest := out
	for {
		block, remaining := pem.Decode(rest)
		if block == nil {
			break
		}
		rest = remaining
		parsed, parseErr := x509.ParseCertificate(block.Bytes)
		if parseErr != nil {
			continue
		}
		if strings.EqualFold(fmt.Sprintf("%X", parsed.SerialNumber), certID) {
			return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: parsed.Raw}), nil
		}
	}
	return nil, platform.ErrNotFound
}

func (s *Slot) ImportCertificate(ctx context.Context, cardID string, opt platform.ImportOptions) error {
	if s.security == "" {
		return platform.Unsupported("未找到 security 命令")
	}
	if opt.Path == "" {
		return platform.Unsupported("暂只支持从文件路径导入证书")
	}
	_, err := exec.CommandContext(ctx, s.security, "add-certificates", "-k", "~/Library/Keychains/login.keychain-db", opt.Path).CombinedOutput()
	if err != nil {
		return fmt.Errorf("导入证书失败: %w", err)
	}
	return nil
}

func (s *Slot) GenerateKey(ctx context.Context, cardID string, opt platform.KeyOptions) (platform.PublicKey, error) {
	return platform.PublicKey{}, platform.Unsupported("Secure Enclave 密钥生成需要 cgo 绑定 Security.framework，当前构建未启用")
}

func (s *Slot) Sign(ctx context.Context, cardID, keyID string, digest []byte, mechanism string) ([]byte, error) {
	return nil, platform.Unsupported("Secure Enclave 签名需要 cgo 绑定 Security.framework，当前构建未启用")
}

func (s *Slot) Backup(ctx context.Context, cardID string, w io.Writer) error {
	return platform.Unsupported("钥匙串备份只能导出证书与证书链（私钥不可导出），P1 待接入")
}
