//go:build windows

package sshagent

import (
	"context"
	"errors"
	"net"
)

// Windows 的 OpenSSH 通过命名管道 \\.\pipe\openssh-ssh-agent 访问 agent，
// 需要 go-winio 依赖；当前优先保证 Linux/macOS 的 PKCS#11 场景。
var ErrNamedPipeUnsupported = errors.New("sshagent: Windows 命名管道待接入（需要 go-winio），当前请使用 OpenSSH 的 PKCS#11 提供程序")

// Listen 在 Windows 上暂不支持命名管道。
func Listen(path string) (net.Listener, error) {
	return nil, ErrNamedPipeUnsupported
}

// ServeListener 保留签名以便跨平台调用。
func ServeListener(ctx context.Context, listener net.Listener, agent *Agent) error {
	return ErrNamedPipeUnsupported
}
