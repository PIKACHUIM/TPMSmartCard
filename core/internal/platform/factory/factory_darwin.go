//go:build darwin

package factory

import (
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform"
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform/darwin"
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform/p11"
)

// Slots 返回当前平台可用的卡槽。
func Slots() []platform.Slot {
	slots := []platform.Slot{darwin.New()}
	if backend, ok := p11.Detect(); ok {
		slots = append(slots, backend)
	}
	return slots
}
