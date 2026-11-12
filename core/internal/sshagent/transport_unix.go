//go:build !windows

package sshagent

import (
	"context"
	"errors"
	"net"
	"os"
	"path/filepath"
)

// Listen 在 Unix domain socket 上监听（Linux / macOS）。
//
// SSH 客户端通过 SSH_AUTH_SOCK 找到 agent，因此路径需要由调用方写进环境变量。
func Listen(path string) (net.Listener, error) {
	if path == "" {
		return nil, errors.New("sshagent: socket 路径不能为空")
	}
	if dir := filepath.Dir(path); dir != "" {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return nil, err
		}
	}
	// 上次异常退出可能留下残留 socket
	if info, err := os.Stat(path); err == nil && info.Mode()&os.ModeSocket != 0 {
		_ = os.Remove(path)
	}
	listener, err := net.Listen("unix", path)
	if err != nil {
		return nil, err
	}
	if err := os.Chmod(path, 0o600); err != nil {
		_ = listener.Close()
		return nil, err
	}
	return listener, nil
}

// ServeListener 接受连接并逐个处理；ctx 取消时关闭监听。
func ServeListener(ctx context.Context, listener net.Listener, agent *Agent) error {
	go func() {
		<-ctx.Done()
		_ = listener.Close()
	}()
	for {
		conn, err := listener.Accept()
		if err != nil {
			select {
			case <-ctx.Done():
				return nil
			default:
				return err
			}
		}
		go func() {
			if serveErr := agent.Serve(ctx, conn); serveErr != nil {
				agent.logf("sshagent: 连接结束: %v", serveErr)
			}
		}()
	}
}
