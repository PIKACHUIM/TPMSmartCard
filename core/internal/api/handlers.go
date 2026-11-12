package api

import (
	"context"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"github.com/PIKACHUIM/tpmsmartcard/internal/autostart"
	"github.com/PIKACHUIM/tpmsmartcard/internal/backup"
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform"
	"github.com/PIKACHUIM/tpmsmartcard/internal/protocol"
)

type healthPayload struct {
	Platform      string              `json:"platform"`
	TPM           tpmInfo             `json:"tpm"`
	Reader        readerInfo          `json:"reader"`
	SecureEnclave seInfo              `json:"secure_enclave"`
	Backend       backendInfo         `json:"backend"`
	Capability    platform.Capability `json:"capability"`
	Slots         []platform.SlotInfo `json:"slots"`
}

type tpmInfo struct {
	Present bool   `json:"present"`
	Version string `json:"version"`
	Detail  string `json:"detail"`
}

type readerInfo struct {
	Present bool     `json:"present"`
	Readers []string `json:"readers"`
}

type seInfo struct {
	Available bool   `json:"available"`
	Detail    string `json:"detail"`
}

type backendInfo struct {
	Version       string `json:"version"`
	UptimeSeconds int64  `json:"uptime_seconds"`
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
	defer cancel()

	var infos []platform.SlotInfo
	var capability platform.Capability
	se := seInfo{Detail: "当前平台无 Secure Enclave"}
	tpm := tpmInfo{Detail: "未检测到 TPM"}
	readers := []string{}

	for _, slot := range s.opts.SlotsFunc() {
		info, err := slot.Info(ctx)
		if err != nil {
			continue
		}
		infos = append(infos, info)
		capability = mergeCapability(capability, info.Capability)
		if info.Capability.SecureEnclave {
			se = seInfo{Available: true, Detail: info.Detail}
		}
		if info.Capability.TPMBacked {
			tpm = tpmInfo{Present: true, Version: "2.0", Detail: info.Detail}
		}
	}

	if cards, _ := s.catalog(ctx); len(cards) > 0 {
		for _, card := range cards {
			if card.Reader != "" {
				readers = append(readers, card.Reader)
			}
		}
		readers = unique(readers)
	}

	writeJSON(w, http.StatusOK, healthPayload{
		Platform:      platformOf(s.opts.Platform),
		TPM:           tpm,
		Reader:        readerInfo{Present: len(readers) > 0, Readers: readers},
		SecureEnclave: se,
		Backend: backendInfo{
			Version:       s.opts.Version,
			UptimeSeconds: int64(time.Since(s.startedAt).Seconds()),
		},
		Capability: capability,
		Slots:      infos,
	})
}

func platformOf(value string) string {
	if value != "" {
		return value
	}
	switch runtime.GOOS {
	case "windows":
		return "windows"
	case "darwin":
		return "macos"
	default:
		return runtime.GOOS
	}
}

func mergeCapability(a, b platform.Capability) platform.Capability {
	return platform.Capability{
		CreateCard:    a.CreateCard || b.CreateCard,
		DeleteCard:    a.DeleteCard || b.DeleteCard,
		SetPIN:        a.SetPIN || b.SetPIN,
		TPMBacked:     a.TPMBacked || b.TPMBacked,
		SecureEnclave: a.SecureEnclave || b.SecureEnclave,
		Backup:        a.Backup || b.Backup,
		SSH:           a.SSH || b.SSH,
		FIDO:          a.FIDO || b.FIDO,
		ExportableKey: a.ExportableKey || b.ExportableKey,
	}
}

func unique(values []string) []string {
	seen := make(map[string]struct{}, len(values))
	out := make([]string, 0, len(values))
	for _, value := range values {
		if _, ok := seen[value]; ok {
			continue
		}
		seen[value] = struct{}{}
		out = append(out, value)
	}
	return out
}

func (s *Server) handleListCards(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
	defer cancel()
	cards, warnings := s.catalog(ctx)
	if cards == nil {
		cards = []platform.Card{}
	}
	writeJSON(w, http.StatusOK, map[string]any{"cards": cards, "warnings": warnings})
}

type createCardRequest struct {
	Name string `json:"name"`
	PIN  string `json:"pin"`
	PUK  string `json:"puk"`
}

func (s *Server) handleCreateCard(w http.ResponseWriter, r *http.Request) {
	var req createCardRequest
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, protocol.ErrBadRequest, "请求体不是合法 JSON")
		return
	}
	if strings.TrimSpace(req.Name) == "" || req.PIN == "" {
		writeError(w, http.StatusBadRequest, protocol.ErrBadRequest, "卡片名与 PIN 不能为空")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 120*time.Second)
	defer cancel()

	for _, slot := range s.opts.SlotsFunc() {
		info, err := slot.Info(ctx)
		if err != nil || !info.Capability.CreateCard {
			continue
		}
		s.broker.publish(map[string]any{"stage": "create", "slot": slot.ID(), "status": "running"})
		card, err := slot.Create(ctx, platform.CreateOptions{Name: req.Name, PIN: req.PIN, PUK: req.PUK})
		if err != nil {
			s.broker.publish(map[string]any{"stage": "create", "status": "failed", "message": err.Error()})
			writePlatformError(w, err)
			return
		}
		s.broker.publish(map[string]any{"stage": "create", "status": "ok", "card": card.ID})
		writeJSON(w, http.StatusCreated, card)
		return
	}
	writeError(w, http.StatusNotImplemented, protocol.ErrBadRequest, "当前平台没有可用的建卡后端")
}

func (s *Server) handleDeleteCard(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 90*time.Second)
	defer cancel()
	id := r.PathValue("id")
	slot, _, err := s.resolve(ctx, id)
	if err != nil {
		writePlatformError(w, err)
		return
	}
	if err := slot.Delete(ctx, id); err != nil {
		writePlatformError(w, err)
		return
	}
	s.broker.publish(map[string]any{"stage": "delete", "status": "ok", "card": id})
	writeJSON(w, http.StatusOK, map[string]any{"done": true})
}

func (s *Server) handleSetPIN(w http.ResponseWriter, r *http.Request) {
	var req struct {
		OldPIN string `json:"old_pin"`
		NewPIN string `json:"new_pin"`
	}
	if err := decodeJSON(r, &req); err != nil || req.NewPIN == "" {
		writeError(w, http.StatusBadRequest, protocol.ErrBadRequest, "缺少新 PIN")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	id := r.PathValue("id")
	slot, _, err := s.resolve(ctx, id)
	if err != nil {
		writePlatformError(w, err)
		return
	}
	if err := slot.SetPIN(ctx, id, req.OldPIN, req.NewPIN); err != nil {
		writePlatformError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"done": true})
}

func (s *Server) handleListCertificates(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()

	cardID := r.URL.Query().Get("card_id")
	if cardID != "" {
		slot, _, err := s.resolve(ctx, cardID)
		if err != nil {
			writePlatformError(w, err)
			return
		}
		certs, err := slot.ListCertificates(ctx, cardID)
		if err != nil {
			writePlatformError(w, err)
			return
		}
		if certs == nil {
			certs = []platform.Certificate{}
		}
		writeJSON(w, http.StatusOK, map[string]any{"certificates": certs})
		return
	}

	var all []platform.Certificate
	for _, slot := range s.opts.SlotsFunc() {
		cards, err := slot.List(ctx)
		if err != nil {
			continue
		}
		for _, card := range cards {
			if certs, err := slot.ListCertificates(ctx, card.ID); err == nil {
				all = append(all, certs...)
			}
		}
	}
	if all == nil {
		all = []platform.Certificate{}
	}
	sort.SliceStable(all, func(i, j int) bool { return all[i].NotAfter < all[j].NotAfter })
	writeJSON(w, http.StatusOK, map[string]any{"certificates": all})
}

// handleImportCertificate 接收 PEM 文本，交给平台槽写入卡片。
//
// 只接受公钥证书：私钥必须留在 TPM / Secure Enclave，不能经 HTTP 传输。
func (s *Server) handleImportCertificate(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CardID string `json:"card_id"`
		PEM    string `json:"pem"`
		PIN    string `json:"pin"`
		Label  string `json:"label"`
		CertID string `json:"cert_id"`
	}
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, protocol.ErrBadRequest, "请求体不是合法 JSON")
		return
	}
	if strings.TrimSpace(req.CardID) == "" {
		writeError(w, http.StatusBadRequest, protocol.ErrBadRequest, "缺少 card_id")
		return
	}
	block, _ := pem.Decode([]byte(req.PEM))
	if block == nil || block.Type != "CERTIFICATE" {
		writeError(w, http.StatusBadRequest, protocol.ErrBadRequest, "请提供 PEM 格式的证书（BEGIN CERTIFICATE）")
		return
	}
	parsed, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		writeError(w, http.StatusBadRequest, protocol.ErrBadRequest, "证书解析失败："+err.Error())
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 90*time.Second)
	defer cancel()
	slot, card, err := s.resolve(ctx, req.CardID)
	if err != nil {
		writePlatformError(w, err)
		return
	}

	label := req.Label
	if label == "" {
		label = parsed.Subject.CommonName
	}
	opt := platform.ImportOptions{
		Reader: card.Reader,
		Label:  label,
		ID:     req.CertID,
		PIN:    req.PIN,
		Data:   pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: parsed.Raw}),
	}
	if err := slot.ImportCertificate(ctx, req.CardID, opt); err != nil {
		writePlatformError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{
		"imported": true,
		"subject":  parsed.Subject.String(),
		"serial":   fmt.Sprintf("%X", parsed.SerialNumber),
	})
}

// handleExportCertificate 输出 PEM，供前端直接下载。
func (s *Server) handleExportCertificate(w http.ResponseWriter, r *http.Request) {
	cardID := r.URL.Query().Get("card_id")
	certID := r.PathValue("certID")
	if cardID == "" || certID == "" {
		writeError(w, http.StatusBadRequest, protocol.ErrBadRequest, "缺少 card_id 或证书 ID")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	slot, _, err := s.resolve(ctx, cardID)
	if err != nil {
		writePlatformError(w, err)
		return
	}
	pemBytes, err := slot.ExportCertificate(ctx, cardID, certID)
	if err != nil {
		writePlatformError(w, err)
		return
	}
	if len(pemBytes) == 0 {
		writeError(w, http.StatusNotFound, protocol.ErrNotFound, "证书内容为空")
		return
	}
	w.Header().Set("Content-Type", "application/x-pem-file; charset=utf-8")
	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=\"%s.pem\"", sanitize(certID)))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(pemBytes)
}

func (s *Server) handleListBackups(w http.ResponseWriter, r *http.Request) {
	entries := []map[string]any{}
	if s.opts.BackupsDir != "" {
		files, err := filepath.Glob(filepath.Join(s.opts.BackupsDir, "*.tsb"))
		if err == nil {
			sort.Sort(sort.Reverse(sort.StringSlice(files)))
			for _, file := range files {
				info, statErr := os.Stat(file)
				if statErr != nil {
					continue
				}
				manifest, inspectErr := backup.Inspect(file)
				status := "verified"
				if inspectErr != nil {
					status = "failed"
				}
				entry := map[string]any{
					"id":             filepath.Base(file),
					"file":           filepath.Base(file),
					"card_name":      manifest.CardName,
					"created_at":     manifest.CreatedAt,
					"size_bytes":     info.Size(),
					"protected_by":   manifest.Protection,
					"key_exportable": manifest.KeyExportable,
					"status":         status,
				}
				if entry["card_name"] == "" {
					entry["card_name"] = "未知卡片"
				}
				if entry["created_at"] == "" {
					entry["created_at"] = info.ModTime().UTC().Format(time.RFC3339)
				}
				entries = append(entries, entry)
			}
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"backups": entries})
}

func (s *Server) handleCreateBackup(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CardID string `json:"card_id"`
	}
	if err := decodeJSON(r, &req); err != nil || req.CardID == "" {
		writeError(w, http.StatusBadRequest, protocol.ErrBadRequest, "缺少 card_id")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 180*time.Second)
	defer cancel()
	slot, card, err := s.resolve(ctx, req.CardID)
	if err != nil {
		writePlatformError(w, err)
		return
	}

	dir := s.opts.BackupsDir
	if dir == "" {
		dir = "."
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		writeError(w, http.StatusInternalServerError, protocol.ErrInternal, "无法创建备份目录")
		return
	}
	name := sanitize(card.Name) + "-" + time.Now().Format("20060102-150405") + ".tsb"
	path := filepath.Join(dir, name)
	file, err := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		writeError(w, http.StatusInternalServerError, protocol.ErrInternal, "无法写入备份文件")
		return
	}
	defer file.Close()

	s.broker.publish(map[string]any{"stage": "backup", "status": "running", "card": card.ID})
	if err := slot.Backup(ctx, card.ID, file); err != nil {
		_ = os.Remove(path)
		s.broker.publish(map[string]any{"stage": "backup", "status": "failed", "message": err.Error()})
		writePlatformError(w, err)
		return
	}
	s.broker.publish(map[string]any{"stage": "backup", "status": "ok", "file": name})
	writeJSON(w, http.StatusCreated, map[string]any{"file": name})
}

func (s *Server) handleAutostart(w http.ResponseWriter, r *http.Request) {
	enabled, detail, err := autostart.Status()
	if err != nil && !errors.Is(err, autostart.ErrUnsupported) {
		writeError(w, http.StatusInternalServerError, protocol.ErrInternal, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"enabled": enabled,
		"detail":  detail,
		"args":    autostart.LaunchArgs,
	})
}

func (s *Server) handleSetAutostart(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Enabled bool   `json:"enabled"`
		Exe     string `json:"exe"`
	}
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, protocol.ErrBadRequest, "请求体不是合法 JSON")
		return
	}
	exe := req.Exe
	if exe == "" {
		resolved, err := autostart.Executable()
		if err != nil {
			writeError(w, http.StatusInternalServerError, protocol.ErrInternal, "无法确定可执行文件路径")
			return
		}
		exe = resolved
	}
	var err error
	if req.Enabled {
		err = autostart.Enable(exe)
	} else {
		err = autostart.Disable()
	}
	if err != nil {
		if errors.Is(err, autostart.ErrUnsupported) {
			writeError(w, http.StatusNotImplemented, protocol.ErrBadRequest, "当前平台不支持自动启动")
			return
		}
		writeError(w, http.StatusInternalServerError, protocol.ErrInternal, err.Error())
		return
	}
	enabled, detail, _ := autostart.Status()
	writeJSON(w, http.StatusOK, map[string]any{"enabled": enabled, "detail": detail})
}

func sanitize(name string) string {
	replacer := strings.NewReplacer("\\", "-", "/", "-", ":", "-", "*", "-", "?", "-", "\"", "-", "<", "-", ">", "-", "|", "-", " ", "-")
	cleaned := strings.TrimSpace(replacer.Replace(name))
	if cleaned == "" {
		return "card"
	}
	return cleaned
}

func (s *Server) handleStats(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
	defer cancel()

	cards, _ := s.catalog(ctx)
	totalCerts := 0
	expiring := 0
	for _, slot := range s.opts.SlotsFunc() {
		items, err := slot.List(ctx)
		if err != nil {
			continue
		}
		for _, card := range items {
			totalCerts += card.CertificateCount
			certs, err := slot.ListCertificates(ctx, card.ID)
			if err != nil {
				continue
			}
			for _, cert := range certs {
				deadline, err := time.Parse(time.RFC3339, cert.NotAfter)
				if err == nil && time.Until(deadline) < 90*24*time.Hour {
					expiring++
				}
			}
		}
	}

	writeJSON(w, http.StatusOK, []map[string]any{
		{
			"label": "卡片总数",
			"value": itoa(len(cards)),
			"hint":  "由当前平台卡槽枚举",
		},
		{
			"label": "证书",
			"value": itoa(totalCerts),
			"hint":  "卡上证书数量（含无对应私钥的证书）",
		},
		{
			"label": "即将到期",
			"value": itoa(expiring),
			"hint":  "90 天内到期，需要重新签发",
		},
		{
			"label": "离线可用",
			"value": "100%",
			"hint":  "除云端下发外全部本地完成",
		},
	})
}

func itoa(value int) string {
	if value == 0 {
		return "0"
	}
	digits := []byte{}
	for value > 0 {
		digits = append([]byte{byte('0' + value%10)}, digits...)
		value /= 10
	}
	return string(digits)
}
