//go:build windows

// Package factory 按平台装配可用卡槽，避免上层出现 runtime.GOOS 分支。
package factory

import (
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform"
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform/p11"
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform/win32"
)

// Slots 返回当前平台可用的卡槽（顺序即前端展示顺序）。
func Slots() []platform.Slot {
	slots := []platform.Slot{win32.New()}
	if backend, ok := p11.Detect(); ok {
		slots = append(slots, backend)
	}
	return slots
}
