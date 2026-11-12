//go:build desktop

// Package ui 提供嵌入的前端静态资源。
//
// 构建桌面端时（CI 先 `npm run build -w @tpmsc/web` 再同步到 core/ui/dist），
// 前端产物通过 go:embed 打进单文件；`-tags desktop` 才会编译本文件。
package ui

import (
	"embed"
	"io/fs"
)

//go:embed all:dist
var embedded embed.FS

// FS 返回以 dist 为根的只读文件系统。
func FS() fs.FS {
	sub, err := fs.Sub(embedded, "dist")
	if err != nil {
		return nil
	}
	return sub
}

// Embedded 表示当前是内嵌资源构建。
func Embedded() bool { return true }
