//go:build windows

// tpmsc-fido —— TPM 虚拟智能卡 FIDO2 虚拟 USB 设备服务。
//
// 数据流（与参考项目 PKCS11Driver 的 fido-go 一致，区别在于后端换成本项目的
// Python 服务，且 CTAP 错误码原样透传）：
//
//	浏览器 WebAuthn
//	  → Windows webauthn.dll
//	  → usbip 虚拟 USB 总线（usbip_vhci，一次性安装）
//	  → 本进程（USB/IP 服务器，监听 127.0.0.1:3240，虚拟 HID 设备 busid 2-2）
//	  → CTAP2 CBOR 透传（Named Pipe）
//	  → TPMSmartCard 后端（Python：FidoIpc/FidoCtap）
//
// 本程序只做「运输层」：CTAPHID 分帧、USB/IP 设备模拟、PIN 输入框。
// 凭据的生成/加密/签名全部在 Python 后端完成，私钥不会进入本进程。
package main

import (
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/bulwarkid/virtual-fido/ctap_hid"
	"github.com/bulwarkid/virtual-fido/usb"
	"github.com/bulwarkid/virtual-fido/usbip"
	"github.com/bulwarkid/virtual-fido/util"
)

const (
	// 虚拟设备的 busid：virtual-fido 的 USB 设备摘要里固定为 2-2，
	// attach 时必须与之一致，否则 Windows 端拿不到设备。
	deviceBusID = "2-2"
	// USB/IP 服务端口（全局固定，Windows 端就按这个端口连接）
	usbipPort = 3240
)

var (
	verbose  = flag.Bool("v", false, "输出 trace 级日志（默认 debug）")
	noAttach = flag.Bool("no-attach", false, "只启动 USB/IP 服务，不自动 attach（调试用）")
	usbipDir = flag.String("usbip-dir", "", "usbip 工具目录（默认：可执行文件同目录下的 usbip/）")
	pipeName = flag.String("pipe", `\\.\pipe\TPMFIDO`, "与后端通信的命名管道")
	logPath  = flag.String("log", "", "日志文件路径（为空则输出到标准输出）")

	// PIN 对话框文案由调用方（Python 侧按当前界面语言）传入
	pinTitle  = flag.String("pin-title", "TPM 智能卡", "PIN 对话框标题")
	pinCard   = flag.String("pin-card", "选择智能卡(&C):", "卡片下拉框标签")
	pinLabel  = flag.String("pin-label", "PIN 码(&P):", "PIN 输入框标签")
	pinOK     = flag.String("pin-ok", "确定", "确定按钮")
	pinCancel = flag.String("pin-cancel", "取消", "取消按钮")
	pinWrong  = flag.String("pin-wrong", "PIN 不正确，请重试", "PIN 校验失败提示")

	logger io.Writer = os.Stdout
	appLog          = log.New(os.Stdout, "[FIDO] ", log.LstdFlags)
)

func main() {
	flag.Parse()

	// 日志：写文件时关闭控制台输出依赖，避免父进程管道阻塞
	if *logPath != "" {
		file, err := os.OpenFile(*logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
		if err == nil {
			logger = file
			appLog = log.New(file, "[FIDO] ", log.LstdFlags)
			defer file.Close()
		}
	}
	util.SetLogOutput(logger)
	if *verbose {
		util.SetLogLevel(util.LogLevelTrace)
	} else {
		util.SetLogLevel(util.LogLevelDebug)
	}

	appLog.Printf("启动：pipe=%s busid=%s usbip-dir=%s", *pipeName, deviceBusID, *usbipDir)

	proxy := NewCTAPProxy(*pipeName, PINStrings{
		Title:  *pinTitle,
		Card:   *pinCard,
		PIN:    *pinLabel,
		OK:     *pinOK,
		Cancel: *pinCancel,
		Wrong:  *pinWrong,
	})
	// PIN 登录成功后必须让 Windows 重新枚举设备：当前那条 CTAP 请求已经以
	// 0x27 结束，浏览器会随设备重新出现而自动重试。
	proxy.onPINSuccess = func() {
		time.Sleep(400 * time.Millisecond)
		if err := detachUSBIP(*usbipDir); err != nil {
			appLog.Printf("USB/IP detach 失败（可能设备未挂载）：%v", err)
		}
		time.Sleep(900 * time.Millisecond)
		if err := attachUSBIP(*usbipDir); err != nil {
			appLog.Printf("USB/IP re-attach 失败：%v", err)
		} else {
			appLog.Printf("设备已重新挂载，等待 Windows 重新发起请求")
		}
	}

	serverDone := make(chan struct{})
	ctapHID := ctap_hid.NewCTAPHIDServer(proxy, &unsupportedU2F{})
	device := usb.NewUSBDevice(ctapHID)
	server := usbip.NewUSBIPServer([]usbip.USBIPDevice{device})

	if listener, err := net.Listen("tcp", fmt.Sprintf(":%d", usbipPort)); err != nil {
		appLog.Printf("端口 %d 已被占用，可能已有实例在运行：%v", usbipPort, err)
		os.Exit(3)
	} else {
		listener.Close()
	}

	go func() {
		defer close(serverDone)
		appLog.Printf("USB/IP 服务器启动（127.0.0.1:%d）", usbipPort)
		server.Start()
	}()

	if !*noAttach {
		go func() {
			time.Sleep(400 * time.Millisecond)
			if err := attachUSBIP(*usbipDir); err != nil {
				appLog.Printf("USB/IP attach 失败：%v", err)
			}
		}()
	}

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	select {
	case <-sigCh:
		appLog.Printf("收到退出信号")
	case <-serverDone:
		appLog.Printf("USB/IP 服务器已停止")
	}
	detachUSBIP(*usbipDir)
}

// attachUSBIP 把虚拟设备挂到 Windows 的 usbip 虚拟总线上。
// attacher.exe 必须与 usbip.exe 同目录，所以工作目录切到 usbip.exe 所在目录。
func attachUSBIP(override string) error {
	exe := findUSBIPExe(override)
	if exe == "" {
		return fmt.Errorf("找不到 usbip.exe")
	}
	cmd := exec.Command(exe, "attach", "-r", "127.0.0.1", "-b", deviceBusID)
	cmd.Dir = filepath.Dir(exe)
	output, err := cmd.CombinedOutput()
	if len(output) > 0 {
		appLog.Printf("usbip attach: %s", trimOutput(output))
	}
	return err
}

// detachUSBIP 断开虚拟设备（端口固定为 0：本机只有这一个虚拟设备）。
func detachUSBIP(override string) error {
	exe := findUSBIPExe(override)
	if exe == "" {
		return fmt.Errorf("找不到 usbip.exe")
	}
	cmd := exec.Command(exe, "detach", "-p", "0")
	cmd.Dir = filepath.Dir(exe)
	output, err := cmd.CombinedOutput()
	if len(output) > 0 {
		appLog.Printf("usbip detach: %s", trimOutput(output))
	}
	return err
}

// findUSBIPExe 依次在 --usbip-dir、可执行文件同目录/usbip、PATH 中查找 usbip.exe。
func findUSBIPExe(override string) string {
	candidates := []string{}
	if override != "" {
		candidates = append(candidates, filepath.Join(override, "usbip.exe"), override)
	}
	if exeDir, err := filepath.Abs(filepath.Dir(os.Args[0])); err == nil {
		candidates = append(candidates,
			filepath.Join(exeDir, "usbip", "usbip.exe"),
			filepath.Join(exeDir, "usbip.exe"))
	}
	for _, path := range candidates {
		if info, err := os.Stat(path); err == nil && !info.IsDir() {
			return path
		}
	}
	if path, err := exec.LookPath("usbip.exe"); err == nil {
		return path
	}
	return ""
}

func trimOutput(data []byte) string {
	text := string(data)
	for len(text) > 0 && (text[len(text)-1] == '\n' || text[len(text)-1] == '\r' || text[len(text)-1] == ' ') {
		text = text[:len(text)-1]
	}
	if len(text) > 300 {
		text = text[:300] + "…"
	}
	return text
}

// unsupportedU2F 让 CTAPHID 的 CTAP1/U2F 通道返回 6D00（不支持），
// 避免库在收到 U2F 报文时 panic。
type unsupportedU2F struct{}

func (server *unsupportedU2F) HandleMessage(data []byte) []byte {
	return []byte{0x6D, 0x00}
}
