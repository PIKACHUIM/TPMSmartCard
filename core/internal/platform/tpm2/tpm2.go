//go:build linux

// Package tpm2 用 tpm2-pkcs11 在 Linux 上提供「类虚拟卡」：init token + 密钥 + 证书。
//
// 与 Windows 的 tpmvscmgr 形态不同：这里创建的是 PKCS#11 token，
// 由 NSS / OpenSSH / OpenSC 通过 `pkcs11:` provider 使用，而不是 PC/SC 读卡器。
package tpm2

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/PIKACHUIM/tpmsmartcard/internal/platform"
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform/p11"
)

// Slot 实现 Linux TPM2 token 管理。
type Slot struct {
	p11   *p11.Backend
	ptool string
}

// New 探测 tpm2_ptool 与 OpenSC。
func New() *Slot {
	tool, _ := exec.LookPath("tpm2_ptool")
	backend, _ := p11.Detect()
	return &Slot{p11: backend, ptool: tool}
}

func (s *Slot) ID() string          { return "tpm2-pkcs11" }
func (s *Slot) Kind() platform.Kind { return platform.KindTPM2 }

func (s *Slot) Info(ctx context.Context) (platform.SlotInfo, error) {
	detail := "未找到 tpm2_ptool（请安装 tpm2-pkcs11-tools）"
	if s.ptool != "" {
		detail = "tpm2_ptool: " + s.ptool
		if _, err := os.Stat("/dev/tpmrm0"); err == nil {
			detail += " · /dev/tpmrm0 可用"
		} else {
			detail += " · 未发现 /dev/tpmrm0"
		}
	}
	return platform.SlotInfo{
		ID:       s.ID(),
		Name:     "TPM2 / PKCS#11",
		Kind:     s.Kind(),
		Platform: "linux",
		Detail:   detail,
		Capability: platform.Capability{
			CreateCard:    s.ptool != "",
			DeleteCard:    s.ptool != "",
			SetPIN:        s.ptool != "",
			TPMBacked:     s.ptool != "",
			SecureEnclave: false,
			Backup:        false,
			SSH:           true,
			FIDO:          true,
		},
	}, nil
}

func (s *Slot) List(ctx context.Context) ([]platform.Card, error) {
	if s.ptool == "" {
		return nil, nil
	}
	out, err := run(ctx, s.ptool, "listtokens", "--pid=1")
	if err != nil {
		// 没有初始化过任何 token 时返回空列表，而不是让整个界面报错
		return nil, nil
	}
	var cards []platform.Card
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if !strings.Contains(line, "label:") {
			continue
		}
		label := strings.TrimSpace(strings.SplitN(line, "label:", 2)[1])
		if label == "" {
			continue
		}
		certCount := 0
		if s.p11 != nil {
			if certs, err := s.p11.ListCertificates(ctx, label); err == nil {
				certCount = len(certs)
			}
		}
		cards = append(cards, platform.Card{
			ID:               label,
			Name:             label,
			Kind:             platform.KindTPM2,
			Platform:         "linux",
			Security:         platform.SecurityHigh,
			Reader:           "/dev/tpmrm0",
			CertificateCount: certCount,
			CreatedAt:        platform.Now(),
		})
	}
	return cards, nil
}

func (s *Slot) Create(ctx context.Context, opt platform.CreateOptions) (platform.Card, error) {
	if s.ptool == "" {
		return platform.Card{}, platform.Unsupported("未安装 tpm2-pkcs11-tools（tpm2_ptool）")
	}
	if opt.Name == "" || opt.PIN == "" {
		return platform.Card{}, fmt.Errorf("%w: token 名称与 user PIN 不能为空", platform.ErrPinRequired)
	}
	// SO PIN 用 PUK 充当；未提供时随机生成并明确提示用户立即重置
	sopin := opt.PUK
	if sopin == "" {
		sopin = "tpm2-sopin-change-me"
	}
	args := []string{
		"addtoken", "--pid=1", "--label", opt.Name,
		"--sopin", sopin, "--userpin", opt.PIN,
	}
	if _, err := run(ctx, s.ptool, args...); err != nil {
		return platform.Card{}, err
	}
	return platform.Card{
		ID:        opt.Name,
		Name:      opt.Name,
		Kind:      platform.KindTPM2,
		Platform:  "linux",
		Security:  platform.SecurityHigh,
		Reader:    "/dev/tpmrm0",
		CreatedAt: platform.Now(),
	}, nil
}

func (s *Slot) Delete(ctx context.Context, id string) error {
	if s.ptool == "" {
		return platform.Unsupported("未安装 tpm2_ptool")
	}
	_, err := run(ctx, s.ptool, "rmtoken", "--pid=1", "--label", id)
	return err
}

func (s *Slot) SetPIN(ctx context.Context, id, oldPIN, newPIN string) error {
	module := modulePath()
	if module == "" {
		return platform.Unsupported("未找到 tpm2-pkcs11 模块，可用 TPM2_PKCS11_MODULE 指定")
	}
	_, err := run(ctx, "pkcs11-tool", "--module", module, "--token-label", id,
		"--login", "--pin", oldPIN, "--change-pin", "--new-pin", newPIN)
	return err
}

func (s *Slot) ListCertificates(ctx context.Context, cardID string) ([]platform.Certificate, error) {
	if s.p11 == nil {
		return nil, platform.Unsupported("未找到 OpenSC 工具")
	}
	return s.p11.ListCertificates(ctx, cardID)
}

func (s *Slot) ExportCertificate(ctx context.Context, cardID, certID string) ([]byte, error) {
	if s.p11 == nil {
		return nil, platform.Unsupported("未找到 OpenSC 工具")
	}
	return s.p11.ExportCertificate(ctx, cardID, certID)
}

func (s *Slot) ImportCertificate(ctx context.Context, cardID string, opt platform.ImportOptions) error {
	if s.p11 == nil {
		return platform.Unsupported("未找到 pkcs15-init")
	}
	return s.p11.ImportCertificate(ctx, cardID, opt)
}

func (s *Slot) GenerateKey(ctx context.Context, cardID string, opt platform.KeyOptions) (platform.PublicKey, error) {
	return platform.PublicKey{}, platform.Unsupported("密钥生成需 tpm2tss-genkey + PKCS#11，P1 待接入")
}

func (s *Slot) Sign(ctx context.Context, cardID, keyID string, digest []byte, mechanism string) ([]byte, error) {
	return nil, platform.Unsupported("签名需 PKCS#11 引擎，P1 待接入")
}

func (s *Slot) Backup(ctx context.Context, cardID string, w io.Writer) error {
	return platform.Unsupported("TPM2 sealed 备份（.tsb v2）P1 待接入")
}

func modulePath() string {
	if custom := os.Getenv("TPM2_PKCS11_MODULE"); custom != "" {
		return custom
	}
	candidates := []string{
		"/usr/lib/x86_64-linux-gnu/pkcs11/libtpm2_pkcs11.so",
		"/usr/lib/aarch64-linux-gnu/pkcs11/libtpm2_pkcs11.so",
		"/usr/lib64/pkcs11/libtpm2_pkcs11.so",
		"/usr/lib/pkcs11/libtpm2_pkcs11.so",
		"/usr/local/lib/libtpm2_pkcs11.so",
	}
	for _, path := range candidates {
		if _, err := os.Stat(path); err == nil {
			return path
		}
	}
	matches, _ := filepath.Glob("/usr/lib/*/pkcs11/libtpm2_pkcs11.so")
	if len(matches) > 0 {
		return matches[0]
	}
	return ""
}

func run(ctx context.Context, name string, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	out, err := cmd.CombinedOutput()
	text := strings.TrimSpace(string(out))
	if err != nil {
		if text == "" {
			text = err.Error()
		}
		return "", fmt.Errorf("%s 执行失败: %s", filepath.Base(name), text)
	}
	return text, nil
}
