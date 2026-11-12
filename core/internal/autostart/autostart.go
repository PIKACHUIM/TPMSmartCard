// Package autostart 管理「登录后自动启动」。
//
// 三个平台各自使用系统推荐机制：
//
//	Windows  HKCU\...\Run（用户级，无需管理员）
//	macOS    ~/Library/LaunchAgents/com.pikachuim.tpmsmartcard.plist
//	Linux    ~/.config/autostart/tpmsmartcard.desktop
//
// 统一以 `--minimized` 启动：只驻留托盘，不抢焦点。
package autostart

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
)

// LaunchArgs 是自启时附加的参数。
const LaunchArgs = "--minimized"

// ErrUnsupported 表示当前平台没有实现。
var ErrUnsupported = errors.New("autostart: 当前平台不支持")

// Executable 返回当前可执行文件路径。
func Executable() (string, error) {
	path, err := os.Executable()
	if err != nil {
		return "", err
	}
	return filepath.Clean(path), nil
}

// command 生成启动命令：路径带空格时用引号包裹。
func command(exe string) string {
	exe = strings.TrimSpace(exe)
	if exe == "" {
		return ""
	}
	return `"` + exe + `" ` + LaunchArgs
}
