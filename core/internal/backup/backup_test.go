package backup

import (
	"archive/zip"
	"os"
	"path/filepath"
	"testing"
)

func TestCreateInspectExtract(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "card.tsb")

	manifest := NewManifest("windows", "财务部-李雷", "store-guid", "dpapi", "8F:3A", false)
	entries := []Entry{
		{Name: "keymaps", Data: []byte("cipher-keymaps"), Source: "Tpm/<guid>/keymaps"},
		{Name: "registry.reg", Data: []byte("Windows Registry Editor Version 5.00"), Source: "Enum\\ROOT\\SMARTCARDREADER"},
	}
	if err := Create(path, manifest, entries); err != nil {
		t.Fatal(err)
	}

	info, err := Inspect(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Format != FormatV2 || len(info.Parts) != 2 {
		t.Fatalf("unexpected manifest: %+v", info)
	}
	if info.KeyExportable {
		t.Fatal("key_exportable should be false")
	}
	if len(info.Warnings) == 0 {
		t.Fatal("expected warning about non-exportable key")
	}

	target := filepath.Join(dir, "out")
	if _, err := Extract(path, target); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(target, "keymaps"))
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "cipher-keymaps" {
		t.Fatalf("extracted = %q", data)
	}
}

func TestLegacyArchiveDetected(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "legacy.tsb")
	file, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	writer := zip.NewWriter(file)
	w, _ := writer.Create("card/keymaps")
	_, _ = w.Write([]byte("old"))
	_ = writer.Close()
	_ = file.Close()

	if _, err := Inspect(path); err == nil {
		t.Fatal("expected legacy archive error")
	}
}
