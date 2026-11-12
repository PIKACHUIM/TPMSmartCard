//go:build windows

// Package win32 实现 Windows 虚拟智能卡卡槽（tpmvscmgr + PnP + PC/SC）。
package win32

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/PIKACHUIM/tpmsmartcard/internal/platform"
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform/p11"
)

// Slot 是 Windows 平台唯一负责建卡/删卡/改 PIN 的实现。
type Slot struct {
	p11 *p11.Backend
}

// New 构造 Windows 卡槽；OpenSC 不存在时证书读取会返回明确错误。
func New() *Slot {
	backend, _ := p11.Detect()
	return &Slot{p11: backend}
}

func (s *Slot) ID() string          { return "windows-vsc" }
func (s *Slot) Kind() platform.Kind { return platform.KindWindowsVSC }

func (s *Slot) Info(ctx context.Context) (platform.SlotInfo, error) {
	elevated := isElevated()
	remote := isRemoteSession()
	detail := "tpmvscmgr 就绪"
	if !elevated {
		detail = "未以管理员身份运行：建卡/删卡会失败"
	}
	if remote {
		detail = "当前是远程会话：Windows 禁止建卡/删卡（0x800704d3）"
	}
	_, tpmErr := tpmStatus(ctx)
	return platform.SlotInfo{
		ID:       s.ID(),
		Name:     "Windows 虚拟智能卡",
		Kind:     s.Kind(),
		Platform: "windows",
		Detail:   detail,
		Capability: platform.Capability{
			CreateCard:    tpmErr == nil && elevated && !remote,
			DeleteCard:    tpmErr == nil && elevated && !remote,
			SetPIN:        elevated && !remote,
			TPMBacked:     tpmErr == nil,
			SecureEnclave: false,
			Backup:        elevated,
			SSH:           true,
			FIDO:          true,
		},
	}, nil
}

func (s *Slot) List(ctx context.Context) ([]platform.Card, error) {
	readers, err := listReaders(ctx)
	if err != nil {
		return nil, err
	}
	cards := make([]platform.Card, 0, len(readers))
	for _, reader := range readers {
		certCount := 0
		if s.p11 != nil {
			// PnP 名称与 OpenSC 读卡器名可能差一个序号后缀，交给后端匹配
			s.p11.SetReader(s.p11.MatchReader(ctx, reader.Name))
			if certs, err := s.p11.ListCertificates(ctx, reader.InstanceID); err == nil {
				certCount = len(certs)
			}
		}
		cards = append(cards, platform.Card{
			ID:               reader.InstanceID,
			Name:             reader.Name,
			Kind:             platform.KindWindowsVSC,
			Platform:         "windows",
			Security:         platform.SecurityHigh,
			Reader:           reader.Name,
			CertificateCount: certCount,
			CreatedAt:        platform.Now(),
		})
	}
	return cards, nil
}

func (s *Slot) Create(ctx context.Context, opt platform.CreateOptions) (platform.Card, error) {
	if !isElevated() {
		return platform.Card{}, platform.ErrNotElevated
	}
	if isRemoteSession() {
		return platform.Card{}, platform.ErrRemoteSession
	}
	if opt.Name == "" || opt.PIN == "" {
		return platform.Card{}, fmt.Errorf("%w: 卡片名与 PIN 不能为空", platform.ErrPinRequired)
	}
	// tpmvscmgr 的 PIN 只能通过参数或交互输入；参数形式会在进程列表短暂可见，
	// 因此文档要求建卡期间不要共享桌面。
	args := []string{"create", "/name", opt.Name, "/pin", opt.PIN, "/adminkey", "random", "/generate"}
	if _, err := run(ctx, tpmvscMgrPath(), args...); err != nil {
		return platform.Card{}, err
	}
	return platform.Card{
		ID:        opt.Name,
		Name:      opt.Name,
		Kind:      platform.KindWindowsVSC,
		Platform:  "windows",
		Security:  platform.SecurityHigh,
		CreatedAt: platform.Now(),
	}, nil
}

func (s *Slot) Delete(ctx context.Context, id string) error {
	if !isElevated() {
		return platform.ErrNotElevated
	}
	if isRemoteSession() {
		return platform.ErrRemoteSession
	}
	_, err := run(ctx, tpmvscMgrPath(), "destroy", "/instance", id)
	return err
}

func (s *Slot) SetPIN(ctx context.Context, id, oldPIN, newPIN string) error {
	if isRemoteSession() {
		return platform.ErrRemoteSession
	}
	// 新版 tpmvscmgr 支持 changePin；旧版会返回用法错误，调用方据此提示改用控制面板
	_, err := run(ctx, tpmvscMgrPath(), "changePin", "/instance", id, "/pin", newPIN)
	return err
}

func (s *Slot) ListCertificates(ctx context.Context, cardID string) ([]platform.Certificate, error) {
	if s.p11 == nil {
		return nil, platform.Unsupported("未找到 OpenSC 工具，无法读取卡片证书")
	}
	return s.p11.ListCertificates(ctx, cardID)
}

func (s *Slot) ExportCertificate(ctx context.Context, cardID, certID string) ([]byte, error) {
	if s.p11 == nil {
		return nil, platform.Unsupported("未找到 OpenSC 工具，无法读取卡片证书")
	}
	return s.p11.ExportCertificate(ctx, cardID, certID)
}

func (s *Slot) ImportCertificate(ctx context.Context, cardID string, opt platform.ImportOptions) error {
	if s.p11 == nil {
		return platform.Unsupported("未找到 OpenSC 工具，无法导入证书")
	}
	return s.p11.ImportCertificate(ctx, cardID, opt)
}

func (s *Slot) GenerateKey(ctx context.Context, cardID string, opt platform.KeyOptions) (platform.PublicKey, error) {
	return platform.PublicKey{}, platform.Unsupported("密钥生成需 PKCS#11 引擎（pkcs11-tool --keypairgen），P1 待接入")
}

func (s *Slot) Sign(ctx context.Context, cardID, keyID string, digest []byte, mechanism string) ([]byte, error) {
	return nil, platform.Unsupported("签名需 PKCS#11 引擎，P1 待接入")
}

func (s *Slot) Backup(ctx context.Context, cardID string, w io.Writer) error {
	return platform.Unsupported("整卡备份（DPAPI 层）迁移中：需要借用 SYSTEM 令牌重新加密")
}

// ---- Windows 平台探测 ----

type readerInfo struct {
	Name       string
	InstanceID string
}

func listReaders(ctx context.Context) ([]readerInfo, error) {
	script := `[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; $ErrorActionPreference='Stop'; ` +
		`Get-PnpDevice -Class SmartCardReader -Status OK | ` +
		`Select-Object -Property FriendlyName,InstanceId | ConvertTo-Json -Compress`
	out, err := run(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script)
	if err != nil {
		return nil, err
	}
	trimmed := strings.TrimSpace(out)
	if trimmed == "" || trimmed == "null" {
		return nil, nil
	}
	if strings.HasPrefix(trimmed, "{") {
		trimmed = "[" + trimmed + "]"
	}
	var raw []struct {
		FriendlyName string `json:"FriendlyName"`
		InstanceID   string `json:"InstanceId"`
	}
	if err := json.Unmarshal([]byte(trimmed), &raw); err != nil {
		return nil, fmt.Errorf("解析读卡器列表失败: %w", err)
	}
	readers := make([]readerInfo, 0, len(raw))
	for _, item := range raw {
		readers = append(readers, readerInfo{Name: item.FriendlyName, InstanceID: item.InstanceID})
	}
	return readers, nil
}

func tpmStatus(ctx context.Context) (string, error) {
	out, err := run(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
		`(Get-Tpm | Select-Object TpmPresent,TpmReady,TpmVersion | ConvertTo-Json -Compress)`)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(out), nil
}

func tpmvscMgrPath() string {
	root := os.Getenv("SystemRoot")
	if root == "" {
		root = `C:\Windows`
	}
	return filepath.Join(root, "System32", "tpmvscmgr.exe")
}

var (
	modshell32 = syscall.NewLazyDLL("shell32.dll")
	moduser32  = syscall.NewLazyDLL("user32.dll")
	procAdmin  = modshell32.NewProc("IsUserAnAdmin")
	procMetric = moduser32.NewProc("GetSystemMetrics")
)

func isElevated() bool {
	ret, _, _ := procAdmin.Call()
	return ret != 0
}

func isRemoteSession() bool {
	const smRemoteSession = 0x1000
	ret, _, _ := procMetric.Call(uintptr(smRemoteSession))
	return ret != 0
}

func run(ctx context.Context, name string, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
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
