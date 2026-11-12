//go:build linux

package autostart

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

func desktopPath() (string, error) {
	config, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(config, "autostart", "tpmsmartcard.desktop"), nil
}

// Enable 写入 XDG autostart 条目。
func Enable(exe string) error {
	if command(exe) == "" {
		return errors.New("autostart: 可执行文件路径为空")
	}
	path, err := desktopPath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	content := fmt.Sprintf(`[Desktop Entry]
Type=Application
Name=TPMSmartCard
Comment=TPM 虚拟智能卡管理器（托盘常驻）
Exec=%s
Terminal=false
X-GNOME-Autostart-enabled=true
`, command(exe))
	return os.WriteFile(path, []byte(content), 0o644)
}

// Disable 删除 XDG autostart 条目。
func Disable() error {
	path, err := desktopPath()
	if err != nil {
		return err
	}
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

// Status 检查 .desktop 是否存在。
func Status() (bool, string, error) {
	path, err := desktopPath()
	if err != nil {
		return false, "", err
	}
	if _, err := os.Stat(path); err != nil {
		if os.IsNotExist(err) {
			return false, "", nil
		}
		return false, "", err
	}
	return true, path, nil
}
