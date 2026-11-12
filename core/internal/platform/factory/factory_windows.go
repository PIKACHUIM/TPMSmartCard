//go:build windows

// Package factory 按平台装配可用卡槽，避免上层出现 runtime.GOOS 分支。
package factory

import (
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform"
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform/win32"
)

// Slots 返回当前平台可用的卡槽。
//
// Windows 只需要一个卡槽：win32 内部已经复用 OpenSC 读取证书，
// 再挂一个 p11 后端会在界面上出现同一张卡的两个条目。
func Slots() []platform.Slot {
	return []platform.Slot{win32.New()}
}
