//go:build !windows && !linux && !darwin

package factory

import (
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform"
)

// Slots 在没有专用实现的平台上返回空集：界面据此只展示云端卡槽能力。
func Slots() []platform.Slot {
	return nil
}
