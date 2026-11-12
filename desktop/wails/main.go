// TPMSmartCard 桌面端（Go + Wails v2）。
//
// 结构沿用 OpenCertRepo 已验证的模式：
//
//	Wails WebView ──► AssetServer（反向代理）──► 同进程内嵌的本地 API + 前端资源
//
// 好处是前端只有一份构建产物（web/dist），浏览器与桌面端行为完全一致；
// 后端初始化期间的请求由内置等待页兜底，不会白屏。
package main

import (
	"log"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

// 由 -ldflags 注入。
var (
	Version   = "2.0.0"
	BuildTime = "unknown"
	Commit    = "unknown"
)

const singleInstanceID = "com.pikachuim.tpmsmartcard"

func main() {
	desktop := NewDesktop()

	err := wails.Run(&options.App{
		Title:            "TPM 虚拟智能卡管理器",
		Width:            1360,
		Height:           860,
		MinWidth:         1080,
		MinHeight:        680,
		BackgroundColour: &options.RGBA{R: 14, G: 17, B: 22, A: 255},
		AssetServer: &assetserver.Options{
			Handler: desktop.assetHandler(),
		},
		Bind:          []any{desktop},
		OnStartup:     desktop.onStartup,
		OnShutdown:    desktop.onShutdown,
		OnBeforeClose: desktop.onBeforeClose,
		SingleInstanceLock: &options.SingleInstanceLock{
			UniqueId:               singleInstanceID,
			OnSecondInstanceLaunch: desktop.onSecondInstance,
		},
	})
	if err != nil {
		log.Fatalf("启动桌面端失败: %v", err)
	}
}
