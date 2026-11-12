//go:build !windows && !darwin && !linux

package autostart

// Enable 在不支持的平台上返回明确错误。
func Enable(string) error { return ErrUnsupported }

// Disable 在不支持的平台上返回明确错误。
func Disable() error { return ErrUnsupported }

// Status 在不支持的平台上返回未启用。
func Status() (bool, string, error) { return false, "", ErrUnsupported }
