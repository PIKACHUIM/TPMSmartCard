//go:build windows

package main

import (
	_ "embed"

	"fyne.io/systray"
	"github.com/wailsapp/wails/v2/pkg/runtime"
)

//go:embed assets/tray.ico
var trayIcon []byte

// startTray 在 Windows 上启动托盘。
//
// 托盘不可用（例如精简系统或远程会话）时 win32 会返回错误，
// systray.Run 内部会直接退出，不影响主窗口。
func (d *Desktop) startTray() {
	go systray.Run(func() {
		d.trayStarted.Store(true)
		systray.SetIcon(trayIcon)
		systray.SetTooltip("TPMSmartCard · TPM 虚拟智能卡管理器")

		show := systray.AddMenuItem("显示主窗口", "从托盘恢复窗口")
		browser := systray.AddMenuItem("在浏览器打开", "使用系统浏览器打开本地界面")
		restart := systray.AddMenuItem("重启本地服务", "重建读卡器与 TPM 会话")
		systray.AddSeparator()
		quit := systray.AddMenuItem("退出", "关闭本地服务并退出")

		for {
			select {
			case <-show.ClickedCh:
				if d.ctx != nil {
					runtime.WindowShow(d.ctx)
				}
			case <-browser.ClickedCh:
				d.OpenInBrowser()
			case <-restart.ClickedCh:
				d.RestartBackend()
			case <-quit.ClickedCh:
				d.Quit()
				return
			}
		}
	}, func() {
		d.trayStarted.Store(false)
	})
}

// stopTray 关闭托盘图标。
func (d *Desktop) stopTray() {
	if d.trayStarted.Load() {
		systray.Quit()
	}
}
