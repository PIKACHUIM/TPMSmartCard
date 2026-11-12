//go:build darwin

package autostart

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

const label = "com.pikachuim.tpmsmartcard"

func plistPath() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(home, "Library", "LaunchAgents", label+".plist"), nil
}

// Enable 写入 LaunchAgent；下次登录生效（不主动 launchctl load，避免打扰当前会话）。
func Enable(exe string) error {
	if command(exe) == "" {
		return errors.New("autostart: 可执行文件路径为空")
	}
	path, err := plistPath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	content := fmt.Sprintf(`<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>%s</string>
  <key>ProgramArguments</key>
  <array>
    <string>%s</string>
    <string>%s</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Interactive</string>
</dict>
</plist>
`, label, exe, LaunchArgs)
	return os.WriteFile(path, []byte(content), 0o644)
}

// Disable 删除 LaunchAgent。
func Disable() error {
	path, err := plistPath()
	if err != nil {
		return err
	}
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

// Status 检查 plist 是否存在。
func Status() (bool, string, error) {
	path, err := plistPath()
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
