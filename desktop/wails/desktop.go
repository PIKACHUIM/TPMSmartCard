package main

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sync"
	"sync/atomic"
	"time"

	"github.com/PIKACHUIM/tpmsmartcard/internal/api"
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform/factory"
	"github.com/PIKACHUIM/tpmsmartcard/ui"
	"github.com/wailsapp/wails/v2/pkg/options"
	wailsruntime "github.com/wailsapp/wails/v2/pkg/runtime"
)

// Desktop 是 Wails 桌面端对象：负责内嵌后端生命周期与原生能力。
// 导出的方法会通过 Wails 绑定暴露给前端（window.go.main.Desktop.*）。
type Desktop struct {
	ctx context.Context

	mu     sync.Mutex
	srv    *http.Server
	apiURL string
	err    error

	proxy       *proxyHandler
	quitting    atomic.Bool
	trayStarted atomic.Bool
}

// NewDesktop 创建桌面端对象（此时尚未启动后端）。
func NewDesktop() *Desktop {
	return &Desktop{proxy: newProxyHandler()}
}

func (d *Desktop) onStartup(ctx context.Context) {
	d.ctx = ctx
	d.startTray()
	go func() {
		if err := d.startBackend(); err != nil {
			d.mu.Lock()
			d.err = err
			d.mu.Unlock()
			fmt.Fprintln(os.Stderr, "本地后端启动失败:", err)
		}
	}()
}

func (d *Desktop) onShutdown(context.Context) {
	d.quitting.Store(true)
	d.stopTray()
	d.stopBackend()
}

// onBeforeClose 拦截关闭：托盘可用时隐藏窗口，否则正常退出。
func (d *Desktop) onBeforeClose(ctx context.Context) bool {
	if d.quitting.Load() || !d.trayStarted.Load() {
		return false
	}
	wailsruntime.WindowHide(ctx)
	return true
}

func (d *Desktop) onSecondInstance(_ options.SecondInstanceData) {
	if d.ctx != nil {
		d.showWindow()
	}
}

func (d *Desktop) assetHandler() http.Handler {
	return d.proxy
}

// startBackend 在随机本地端口启动 API，并把它挂到反向代理上。
func (d *Desktop) startBackend() error {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	addr := listener.Addr().String()

	backupDir := filepath.Join(userDataDir(), "backups")
	_ = os.MkdirAll(backupDir, 0o700)

	server := api.New(api.Options{
		Slots:      factory.Slots(),
		UIFS:       ui.FS(),
		BackupsDir: backupDir,
		Token:      os.Getenv("TPMSC_LOCAL_TOKEN"),
		Platform:   "",
		Version:    Version,
	})

	srv := &http.Server{
		Handler:           server.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
	}
	go func() {
		if serveErr := srv.Serve(listener); serveErr != nil && !errors.Is(serveErr, http.ErrServerClosed) {
			fmt.Fprintln(os.Stderr, "本地 API 退出:", serveErr)
		}
	}()

	target, _ := url.Parse("http://" + addr)
	d.proxy.setTarget(target)

	d.mu.Lock()
	d.srv = srv
	d.apiURL = target.String()
	d.err = nil
	d.mu.Unlock()
	return nil
}

func (d *Desktop) stopBackend() {
	d.mu.Lock()
	srv := d.srv
	d.srv = nil
	d.apiURL = ""
	d.mu.Unlock()

	d.proxy.clearTarget()
	if srv == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
}

// ---- 暴露给前端的绑定 ----

// Status 返回桌面端与后端状态。
func (d *Desktop) Status() map[string]any {
	d.mu.Lock()
	defer d.mu.Unlock()
	status := map[string]any{
		"version":     Version,
		"build_time":  BuildTime,
		"commit":      Commit,
		"api_url":     d.apiURL,
		"running":     d.srv != nil,
		"embedded_ui": ui.Embedded(),
		"platform":    runtime.GOOS,
		"data_dir":    userDataDir(),
	}
	if d.err != nil {
		status["error"] = d.err.Error()
	}
	return status
}

// VersionString 返回版本号。
func (d *Desktop) VersionString() string { return Version }

// RestartBackend 重启本地后端。
func (d *Desktop) RestartBackend() map[string]any {
	d.stopBackend()
	if err := d.startBackend(); err != nil {
		d.mu.Lock()
		d.err = err
		d.mu.Unlock()
	}
	return d.Status()
}

// OpenInBrowser 用系统浏览器打开管理界面（便于多屏或调试）。
func (d *Desktop) OpenInBrowser() {
	d.mu.Lock()
	url := d.apiURL
	d.mu.Unlock()
	if url == "" {
		return
	}
	openURL(url)
}

// OpenDataDir 打开数据目录。
func (d *Desktop) OpenDataDir() {
	openURL(userDataDir())
}

// Quit 退出应用。
func (d *Desktop) Quit() {
	d.quitting.Store(true)
	d.stopBackend()
	os.Exit(0)
}

func (d *Desktop) showWindow() {
	// 托盘与窗口唤起在 Wails v2 中通过 runtime 包实现；
	// 这里保持最小依赖，避免在无托盘环境下引入额外平台库。
}

func openURL(target string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", target)
	case "darwin":
		cmd = exec.Command("open", target)
	default:
		cmd = exec.Command("xdg-open", target)
	}
	_ = cmd.Start()
}

func userDataDir() string {
	if dir, err := os.UserConfigDir(); err == nil {
		return filepath.Join(dir, "TPMSmartCard")
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".tpmsmartcard")
}
