// Package p11 通过 OpenSC 命令行工具访问 PC/SC 卡片。
//
// 选择 CLI 而不是 cgo 绑定，是为了保住 Windows 的交叉编译能力（CGO_ENABLED=0），
// 与 v1 的 SmartCardAPI 双后端思路一致：优先 OpenSC，失败时回退 certutil。
package p11

import (
	"bytes"
	"context"
	"crypto/sha1"
	"crypto/x509"
	"encoding/hex"
	"encoding/pem"
	"fmt"
	"io"
	"os/exec"
	"runtime"
	"strings"

	"github.com/PIKACHUIM/tpmsmartcard/internal/platform"
)

// Backend 实现只读证书能力；建卡由各平台专用 Slot 负责。
type Backend struct {
	pkcs15  string
	opensc  string
	pkcs11  string
	reader  string
	platform string
}

// Detect 探测可用的 OpenSC 工具链。
func Detect() (*Backend, bool) {
	b := &Backend{
		pkcs15:   lookPath("pkcs15-tool"),
		opensc:   lookPath("opensc-tool"),
		pkcs11:   lookPath("pkcs11-tool"),
		platform: runtime.GOOS,
	}
	if b.pkcs15 == "" && b.opensc == "" && b.pkcs11 == "" {
		return nil, false
	}
	return b, true
}

func lookPath(name string) string {
	path, err := exec.LookPath(name)
	if err != nil {
		return ""
	}
	return path
}

func (b *Backend) ID() string                    { return "opensc" }
func (b *Backend) Kind() platform.Kind           { return platform.KindLocal }

func (b *Backend) Info(ctx context.Context) (platform.SlotInfo, error) {
	detail := "OpenSC 未安装"
	if b.pkcs15 != "" {
		detail = "OpenSC: " + b.pkcs15
	}
	return platform.SlotInfo{
		ID:       b.ID(),
		Name:     "OpenSC 只读后端",
		Kind:     b.Kind(),
		Platform: b.platform,
		Detail:   detail,
		Capability: platform.Capability{
			CreateCard: false,
			DeleteCard: false,
			SetPIN:     b.pkcs15 != "",
			Backup:     false,
			SSH:        true,
			FIDO:       false,
		},
	}, nil
}

func (b *Backend) List(ctx context.Context) ([]platform.Card, error) {
	readers, err := b.Readers(ctx)
	if err != nil {
		return nil, err
	}
	cards := make([]platform.Card, 0, len(readers))
	for index, reader := range readers {
		cards = append(cards, platform.Card{
			ID:       fmt.Sprintf("opensc-%d", index),
			Name:     reader,
			Kind:     platform.KindLocal,
			Platform: b.platform,
			Security: platform.SecurityMedium,
			Reader:   reader,
			CreatedAt: platform.Now(),
		})
	}
	return cards, nil
}

// Readers 列出 PC/SC 读卡器（opensc-tool --list-readers）。
func (b *Backend) Readers(ctx context.Context) ([]string, error) {
	if b.opensc == "" {
		return nil, platform.Unsupported("未找到 opensc-tool，请先安装 OpenSC")
	}
	out, err := run(ctx, b.opensc, "--list-readers")
	if err != nil {
		return nil, err
	}
	var readers []string
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || !strings.HasPrefix(line, "#") {
			continue
		}
		// 形如 "#0  Microsoft Virtual Smart Card 0 00 00"
		if idx := strings.Index(line, "  "); idx >= 0 {
			line = strings.TrimSpace(line[idx:])
		}
		readers = append(readers, line)
	}
	return readers, nil
}

// ListCertificates 用 pkcs15-tool 读取证书并解析为 X.509 视图。
func (b *Backend) ListCertificates(ctx context.Context, cardID string) ([]platform.Certificate, error) {
	if b.pkcs15 == "" {
		return nil, platform.Unsupported("未找到 pkcs15-tool，请先安装 OpenSC")
	}
	args := []string{"--list-certificates"}
	if b.reader != "" {
		args = append(args, "--reader", b.reader)
	}
	out, err := run(ctx, b.pkcs15, args...)
	if err != nil {
		return nil, err
	}

	ids := parseCertificateIDs(out)
	certs := make([]platform.Certificate, 0, len(ids))
	for _, id := range ids {
		readArgs := []string{"--read-certificate", id}
		if b.reader != "" {
			readArgs = append(readArgs, "--reader", b.reader)
		}
		pemText, err := run(ctx, b.pkcs15, readArgs...)
		if err != nil {
			continue
		}
		parsed, err := parseCertificate([]byte(pemText))
		if err != nil {
			continue
		}
		certs = append(certs, toCertificate(cardID, id, parsed))
	}
	return certs, nil
}

func parseCertificateIDs(output string) []string {
	var ids []string
	for _, line := range strings.Split(output, "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "ID") && strings.Contains(trimmed, ":") {
			value := strings.TrimSpace(strings.SplitN(trimmed, ":", 2)[1])
			if value != "" && !strings.Contains(value, " ") {
				ids = append(ids, value)
			}
		}
	}
	return ids
}

func parseCertificate(data []byte) (*x509.Certificate, error) {
	block, _ := pem.Decode(data)
	if block != nil {
		return x509.ParseCertificate(block.Bytes)
	}
	return x509.ParseCertificate(data)
}

func toCertificate(cardID, id string, cert *x509.Certificate) platform.Certificate {
	sum := sha1.Sum(cert.Raw)
	usages := make([]string, 0, 4)
	if cert.KeyUsage&x509.KeyUsageDigitalSignature != 0 {
		usages = append(usages, "digitalSignature")
	}
	if cert.KeyUsage&x509.KeyUsageKeyEncipherment != 0 {
		usages = append(usages, "keyEncipherment")
	}
	if cert.KeyUsage&x509.KeyUsageKeyAgreement != 0 {
		usages = append(usages, "keyAgreement")
	}
	if cert.KeyUsage&x509.KeyUsageContentCommitment != 0 {
		usages = append(usages, "nonRepudiation")
	}
	return platform.Certificate{
		ID:            id,
		CardID:        cardID,
		Subject:       cert.Subject.String(),
		Issuer:        cert.Issuer.String(),
		Serial:        formatSerial(cert.SerialNumber.Bytes()),
		KeyAlgorithm:  cert.PublicKeyAlgorithm.String(),
		KeyUsage:      usages,
		NotBefore:     cert.NotBefore.UTC().Format("2006-01-02T15:04:05Z"),
		NotAfter:      cert.NotAfter.UTC().Format("2006-01-02T15:04:05Z"),
		Fingerprint:   formatSerial(sum[:]),
		HasPrivateKey: true,
	}
}

func formatSerial(raw []byte) string {
	var parts []string
	for _, b := range raw {
		parts = append(parts, strings.ToUpper(hex.EncodeToString([]byte{b})))
	}
	return strings.Join(parts, ":")
}

// ImportCertificate 使用 pkcs15-init 写入证书（私钥需已在卡上）。
func (b *Backend) ImportCertificate(ctx context.Context, cardID string, opt platform.ImportOptions) error {
	initTool := lookPath("pkcs15-init")
	if initTool == "" {
		return platform.Unsupported("未找到 pkcs15-init，无法导入证书")
	}
	if opt.Path == "" {
		return platform.Unsupported("暂只支持从文件路径导入")
	}
	args := []string{"--store-certificate", opt.Path}
	if opt.ID != "" {
		args = append(args, "--id", opt.ID)
	}
	if opt.Label != "" {
		args = append(args, "--label", opt.Label)
	}
	if opt.Reader != "" {
		args = append(args, "--reader", opt.Reader)
	}
	if opt.PIN == "" {
		return platform.ErrPinRequired
	}
	args = append(args, "--pin", opt.PIN)
	_, err := run(ctx, initTool, args...)
	return err
}

func (b *Backend) Create(ctx context.Context, opt platform.CreateOptions) (platform.Card, error) {
	return platform.Card{}, platform.Unsupported("OpenSC 后端不负责建卡，请使用平台专用卡槽")
}
func (b *Backend) Delete(ctx context.Context, id string) error {
	return platform.Unsupported("OpenSC 后端不负责删卡")
}
func (b *Backend) SetPIN(ctx context.Context, id, oldPIN, newPIN string) error {
	return platform.Unsupported("OpenSC 后端暂不支持改 PIN")
}
func (b *Backend) GenerateKey(ctx context.Context, cardID string, opt platform.KeyOptions) (platform.PublicKey, error) {
	return platform.PublicKey{}, platform.Unsupported("密钥在卡片内生成，CSR 需由 PKCS#11 引擎完成")
}
func (b *Backend) Sign(ctx context.Context, cardID, keyID string, digest []byte, mechanism string) ([]byte, error) {
	return nil, platform.Unsupported("OpenSC 后端为只读，签名请使用平台卡槽")
}
func (b *Backend) Backup(ctx context.Context, cardID string, w io.Writer) error {
	return platform.Unsupported("OpenSC 后端不负责备份")
}

func run(ctx context.Context, name string, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(stderr.String())
		if msg == "" {
			msg = err.Error()
		}
		return "", fmt.Errorf("%s 执行失败: %s", name, msg)
	}
	return stdout.String(), nil
}

// SetReader 指定后续操作使用的读卡器。
func (b *Backend) SetReader(reader string) { b.reader = reader }

// Reader 返回当前绑定的读卡器。
func (b *Backend) Reader() string { return b.reader }
