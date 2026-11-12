//go:build !windows

package main

// startTray 在非 Windows 平台暂不启用托盘：
// Linux 需要 libayatana-appindicator、macOS 需要额外模板图标，
// 这些在 P2 的安装包阶段一并接入；当前关闭窗口直接退出。
func (d *Desktop) startTray() {}

func (d *Desktop) stopTray() {}
