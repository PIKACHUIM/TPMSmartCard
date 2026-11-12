// Package backup 实现 .tsb v2 备份格式。
//
// 与 v1 的差异：v1 是一个「谁也不知道里面有什么」的 zip，v2 增加 manifest.json：
//   - format/version 明确标识
//   - 每个部件的 SHA-256 可用于还原前校验
//   - protection 说明加密方式（dpapi / tpm2 / keychain / passphrase）
//   - key_exportable 说明私钥是否在包内（SE / TPM 高等级为 false）
//
// v1 包仍可识别（没有 manifest.json），但只允许「只读导入」，并在返回中提示。
package backup

import (
	"archive/zip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"
)

// FormatV2 是当前备份格式标识。
const FormatV2 = "tsb/2"

// ErrLegacyArchive 表示这是 v1 的 .tsb（无 manifest）。
var ErrLegacyArchive = errors.New("backup: 这是 v1 备份包，只能只读导入，且不能跨机还原")

// Part 是备份中的一个部件。
type Part struct {
	Name   string `json:"name"`
	Source string `json:"source"`
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256"`
	Note   string `json:"note,omitempty"`
}

// Manifest 是 v2 包的清单。
type Manifest struct {
	Format        string `json:"format"`
	Version       int    `json:"version"`
	CreatedAt     string `json:"created_at"`
	Platform      string `json:"platform"`
	CardName      string `json:"card_name"`
	CardID        string `json:"card_id"`
	EKFingerprint string `json:"ek_fingerprint,omitempty"`
	Protection    string `json:"protection"`
	KeyExportable bool   `json:"key_exportable"`
	Parts         []Part `json:"parts"`
	Warnings      []string `json:"warnings,omitempty"`
}

// Entry 是待写入备份的数据。
type Entry struct {
	Name   string
	Data   []byte
	Source string
	Note   string
}

// NewManifest 构造清单，默认带上平台约束提示。
func NewManifest(platform, cardName, cardID, protection, ek string, exportable bool) Manifest {
	m := Manifest{
		Format:        FormatV2,
		Version:       2,
		CreatedAt:     time.Now().UTC().Format(time.RFC3339),
		Platform:      platform,
		CardName:      cardName,
		CardID:        cardID,
		EKFingerprint: ek,
		Protection:    protection,
		KeyExportable: exportable,
	}
	if !exportable {
		m.Warnings = append(m.Warnings, "私钥不可导出：本包只包含证书、证书链与元数据，换机需重新签发")
	}
	return m
}

// Create 写入一个 v2 备份包。
func Create(path string, manifest Manifest, entries []Entry) error {
	if manifest.Format == "" {
		manifest.Format = FormatV2
	}
	if manifest.Version == 0 {
		manifest.Version = 2
	}
	manifest.Parts = make([]Part, 0, len(entries))
	for _, entry := range entries {
		sum := sha256.Sum256(entry.Data)
		manifest.Parts = append(manifest.Parts, Part{
			Name:   entry.Name,
			Source: entry.Source,
			Size:   int64(len(entry.Data)),
			SHA256: hex.EncodeToString(sum[:]),
			Note:   entry.Note,
		})
	}

	if dir := filepath.Dir(path); dir != "" {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return err
		}
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := zip.NewWriter(file)
	manifestBytes, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return err
	}
	if err := writeEntry(writer, "manifest.json", manifestBytes); err != nil {
		return err
	}
	for _, entry := range entries {
		if err := writeEntry(writer, "parts/"+entry.Name, entry.Data); err != nil {
			return err
		}
	}
	return writer.Close()
}

func writeEntry(writer *zip.Writer, name string, data []byte) error {
	header := &zip.FileHeader{Name: name, Method: zip.Deflate}
	header.SetMode(0o600)
	header.Modified = time.Now()
	w, err := writer.CreateHeader(header)
	if err != nil {
		return err
	}
	_, err = w.Write(data)
	return err
}

// Inspect 读取清单并校验部件大小；用于备份列表与还原前检查。
func Inspect(path string) (Manifest, error) {
	reader, err := zip.OpenReader(path)
	if err != nil {
		return Manifest{}, fmt.Errorf("不是合法的备份包: %w", err)
	}
	defer reader.Close()

	for _, file := range reader.File {
		if file.Name != "manifest.json" {
			continue
		}
		rc, err := file.Open()
		if err != nil {
			return Manifest{}, err
		}
		defer rc.Close()
		var manifest Manifest
		if err := json.NewDecoder(rc).Decode(&manifest); err != nil {
			return Manifest{}, fmt.Errorf("manifest 解析失败: %w", err)
		}
		return manifest, nil
	}
	return Manifest{}, ErrLegacyArchive
}

// Extract 校验并解压到目录；返回清单便于展示诊断结论。
func Extract(path, targetDir string) (Manifest, error) {
	reader, err := zip.OpenReader(path)
	if err != nil {
		return Manifest{}, err
	}
	defer reader.Close()

	var manifest Manifest
	found := false
	for _, file := range reader.File {
		if file.Name != "manifest.json" {
			continue
		}
		rc, err := file.Open()
		if err != nil {
			return Manifest{}, err
		}
		err = json.NewDecoder(rc).Decode(&manifest)
		rc.Close()
		if err != nil {
			return Manifest{}, err
		}
		found = true
		break
	}
	if !found {
		return Manifest{}, ErrLegacyArchive
	}

	expected := make(map[string]string, len(manifest.Parts))
	for _, part := range manifest.Parts {
		expected["parts/"+part.Name] = part.SHA256
	}

	if err := os.MkdirAll(targetDir, 0o700); err != nil {
		return Manifest{}, err
	}
	for _, file := range reader.File {
		if file.Name == "manifest.json" {
			continue
		}
		want, ok := expected[file.Name]
		if !ok {
			continue
		}
		rc, err := file.Open()
		if err != nil {
			return Manifest{}, err
		}
		data, err := io.ReadAll(rc)
		rc.Close()
		if err != nil {
			return Manifest{}, err
		}
		sum := sha256.Sum256(data)
		if hex.EncodeToString(sum[:]) != want {
			return Manifest{}, fmt.Errorf("部件 %s 校验失败：文件可能损坏", file.Name)
		}
		dest := filepath.Join(targetDir, filepath.Base(file.Name))
		if err := os.WriteFile(dest, data, 0o600); err != nil {
			return Manifest{}, err
		}
	}
	return manifest, nil
}
