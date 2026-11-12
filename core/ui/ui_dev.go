//go:build !desktop

package ui

import (
	"io/fs"
	"os"
	"path/filepath"
)

// FS 在开发构建下从磁盘读取 web/dist，方便前端热更新。
func FS() fs.FS {
	candidates := []string{
		filepath.Join("web", "dist"),
		filepath.Join("..", "web", "dist"),
		filepath.Join("..", "..", "web", "dist"),
	}
	for _, candidate := range candidates {
		if info, err := os.Stat(candidate); err == nil && info.IsDir() {
			return os.DirFS(candidate)
		}
	}
	return nil
}

// Embedded 表示当前不是内嵌资源构建。
func Embedded() bool { return false }
