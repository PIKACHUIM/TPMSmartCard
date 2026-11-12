//go:build windows

package autostart

import (
	"os/exec"
	"strings"
)

const (
	runKey    = `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
	valueName = "TPMSmartCard"
)

// Enable 写 HKCU Run 项（用户级，不需要管理员）。
func Enable(exe string) error {
	if command(exe) == "" {
		return &execError{"可执行文件路径为空"}
	}
	cmd := exec.Command("reg", "add", runKey, "/v", valueName, "/t", "REG_SZ", "/d", command(exe), "/f")
	return cmd.Run()
}

// Disable 删除 Run 项；本来就不存在时视为成功。
func Disable() error {
	cmd := exec.Command("reg", "delete", runKey, "/v", valueName, "/f")
	if err := cmd.Run(); err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok && exitErr.ExitCode() == 1 {
			return nil
		}
		return err
	}
	return nil
}

// Status 查询当前是否已启用，并返回实际命令。
func Status() (bool, string, error) {
	out, err := exec.Command("reg", "query", runKey, "/v", valueName).Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok && exitErr.ExitCode() == 1 {
			return false, "", nil
		}
		return false, "", err
	}
	for _, line := range strings.Split(string(out), "\n") {
		fields := strings.Fields(line)
		if len(fields) >= 3 && fields[0] == valueName {
			return true, strings.Join(fields[2:], " "), nil
		}
	}
	return false, "", nil
}

type execError struct{ message string }

func (e *execError) Error() string { return e.message }
