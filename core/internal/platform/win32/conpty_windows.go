//go:build windows

package win32

import (
	"bytes"
	"context"
	"fmt"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/UserExistsError/conpty"
)

// ansiEscape 匹配 ConPTY 输出里的光标控制序列。
var ansiEscape = regexp.MustCompile(`\x1b\[[0-9;?]*[a-zA-Z]`)

// runInteractive 用 ConPTY 启动 tpmvscmgr 并回答它的交互提示。
//
// 背景：`tpmvscmgr create` 的 /PIN、/PUK、/AdminKey 只接受
// PROMPT | DEFAULT | RANDOM，**没有**「密码写在命令行」的写法；
// 而 PROMPT 从控制台读输入，管道的 stdin 喂不进去（v1 用 PtyCompat 解决）。
// 这里用 Windows 10 1809+ 的 ConPTY 达到同样效果。
func runInteractive(
	ctx context.Context,
	exe string,
	args []string,
	answers []string,
	timeout time.Duration,
) (string, error) {
	if !conpty.IsConPtyAvailable() {
		return "", fmt.Errorf("当前系统不支持 ConPTY（需要 Windows 10 1809 及以上）")
	}

	commandLine := quoteArg(exe)
	for _, arg := range args {
		commandLine += " " + quoteArg(arg)
	}

	cpty, err := conpty.Start(commandLine)
	if err != nil {
		return "", fmt.Errorf("启动伪控制台失败: %w", err)
	}
	defer cpty.Close()

	var mu sync.Mutex
	var buf bytes.Buffer
	go func() {
		chunk := make([]byte, 4096)
		for {
			n, readErr := cpty.Read(chunk)
			if n > 0 {
				mu.Lock()
				buf.Write(chunk[:n])
				mu.Unlock()
			}
			if readErr != nil {
				return
			}
		}
	}()

	// tpmvscmgr 的提示是顺序出现的；逐条写入，给前一条提示留出显示时间。
	for index, answer := range answers {
		delay := 900*time.Millisecond + time.Duration(index)*400*time.Millisecond
		select {
		case <-ctx.Done():
			return "", ctx.Err()
		case <-time.After(delay):
		}
		if _, writeErr := cpty.Write([]byte(answer + "\r\n")); writeErr != nil {
			return "", fmt.Errorf("写入交互输入失败: %w", writeErr)
		}
	}

	waitCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	code, waitErr := cpty.Wait(waitCtx)

	// 进程退出后可能还有尾部输出没读完
	time.Sleep(300 * time.Millisecond)
	mu.Lock()
	output := stripANSI(buf.String())
	mu.Unlock()

	if waitErr != nil {
		return output, fmt.Errorf("等待 tpmvscmgr 超时或被取消: %w", waitErr)
	}
	if code != 0 {
		return output, fmt.Errorf("tpmvscmgr 退出码 %d：%s", code, lastLines(output, 4))
	}
	return output, nil
}

func quoteArg(arg string) string {
	if arg == "" {
		return `""`
	}
	if !strings.ContainsAny(arg, " \t\"") {
		return arg
	}
	return `"` + strings.ReplaceAll(arg, `"`, `\"`) + `"`
}

func stripANSI(text string) string {
	cleaned := ansiEscape.ReplaceAllString(text, "")
	cleaned = strings.ReplaceAll(cleaned, "\r\n", "\n")
	cleaned = strings.ReplaceAll(cleaned, "\r", "\n")
	// tpmvscmgr 会输出大量空行与进度点
	lines := strings.Split(cleaned, "\n")
	kept := make([]string, 0, len(lines))
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" {
			continue
		}
		kept = append(kept, trimmed)
	}
	return strings.Join(kept, "\n")
}

func lastLines(text string, count int) string {
	lines := strings.Split(text, "\n")
	if len(lines) > count {
		lines = lines[len(lines)-count:]
	}
	return strings.Join(lines, " / ")
}
