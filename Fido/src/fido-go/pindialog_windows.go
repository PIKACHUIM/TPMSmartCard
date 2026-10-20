//go:build windows

package main

import (
	"fmt"
	"runtime"
	"sync"
	"syscall"
	"unsafe"
)

// 纯 Win32 自绘的 PIN 对话框：
//   - 只有一张可用卡片时禁用下拉框，直接把焦点给 PIN 输入框；
//   - PIN 输错时不关窗重开，而是在同一窗口里显示错误文案并清空输入框，
//     避免用户以为程序卡住（每次重试都会消耗卡片 PIN 重试次数，故最多 3 次）。
var (
	user32 = syscall.NewLazyDLL("user32.dll")

	procCreateWindowExW      = user32.NewProc("CreateWindowExW")
	procDefWindowProcW       = user32.NewProc("DefWindowProcW")
	procRegisterClassExW     = user32.NewProc("RegisterClassExW")
	procShowWindow           = user32.NewProc("ShowWindow")
	procUpdateWindow         = user32.NewProc("UpdateWindow")
	procGetMessageW          = user32.NewProc("GetMessageW")
	procTranslateMessage     = user32.NewProc("TranslateMessage")
	procDispatchMessageW     = user32.NewProc("DispatchMessageW")
	procPostQuitMessage      = user32.NewProc("PostQuitMessage")
	procDestroyWindow        = user32.NewProc("DestroyWindow")
	procSendMessageW         = user32.NewProc("SendMessageW")
	procSetFocus             = user32.NewProc("SetFocus")
	procSetWindowTextW       = user32.NewProc("SetWindowTextW")
	procGetWindowTextW       = user32.NewProc("GetWindowTextW")
	procGetWindowTextLengthW = user32.NewProc("GetWindowTextLengthW")
	procSetForegroundWindow  = user32.NewProc("SetForegroundWindow")
	procIsDialogMessageW     = user32.NewProc("IsDialogMessageW")
	procGetSystemMetrics     = user32.NewProc("GetSystemMetrics")
	procSetWindowPos         = user32.NewProc("SetWindowPos")
	procEnableWindow         = user32.NewProc("EnableWindow")
	procGetDlgCtrlID         = user32.NewProc("GetDlgCtrlID")

	kernel32             = syscall.NewLazyDLL("kernel32.dll")
	procGetModuleHandleW = kernel32.NewProc("GetModuleHandleW")

	gdi32              = syscall.NewLazyDLL("gdi32.dll")
	procGetStockObject = gdi32.NewProc("GetStockObject")
)

const (
	wsOverlapped   = 0x00000000
	wsCaption      = 0x00C00000
	wsSysMenu      = 0x00080000
	wsVisible      = 0x10000000
	wsChild        = 0x40000000
	wsTabStop      = 0x00010000
	wsClipChildren = 0x02000000
	wsBorder       = 0x00800000
	wsVScroll      = 0x00200000

	wsExClientEdge = 0x00000200

	esPassword    = 0x0020
	esAutoHScroll = 0x0080

	cbsDropDownList = 0x0003
	cbsHasStrings   = 0x0200

	bsPushButton    = 0x00000000
	bsDefPushButton = 0x00000001

	ssLeft = 0x00000000

	wmCreate   = 0x0001
	wmDestroy  = 0x0002
	wmClose    = 0x0010
	wmCommand  = 0x0111
	wmSetFont  = 0x0030
	wmSetFocus = 0x0007

	cbAddString = 0x0143
	cbSetCurSel = 0x014E
	cbGetCurSel = 0x0147

	bnClicked = 0

	swShow = 5

	smCXScreen = 0
	smCYScreen = 1

	defaultGUIFont = 17

	idOK     = 1
	idCancel = 2
	idCombo  = 100
	idEdit   = 101
	idLabel1 = 102
	idLabel2 = 103
	idErr    = 104
)

type wndClassExW struct {
	cbSize        uint32
	style         uint32
	lpfnWndProc   uintptr
	cbClsExtra    int32
	cbWndExtra    int32
	hInstance     uintptr
	hIcon         uintptr
	hCursor       uintptr
	hbrBackground uintptr
	lpszMenuName  *uint16
	lpszClassName *uint16
	hIconSm       uintptr
}

type msg struct {
	hwnd    uintptr
	message uint32
	wParam  uintptr
	lParam  uintptr
	time    uint32
	pt      struct{ x, y int32 }
}

// CardInfo 是后端返回的一张可用卡片。
type CardInfo struct {
	CardUUID string `json:"card_uuid"`
	CardName string `json:"card_name"`
}

// PINResult 是 PIN 对话框的结果。
type PINResult struct {
	CardUUID string
	PIN      string
}

type dialogState struct {
	cards     []CardInfo
	strings   PINStrings
	errorText string

	result *PINResult
	err    error

	hwnd       uintptr
	hCombo     uintptr
	hEdit      uintptr
	hErr       uintptr
	hBtnOK     uintptr
	hBtnCancel uintptr
	hFont      uintptr
}

var (
	currentDialog *dialogState
	dialogMu      sync.Mutex
)

// PromptPIN 在固定的 OS 线程上弹窗（Win32 要求窗口与消息循环同线程）。
func PromptPIN(cards []CardInfo, strings PINStrings, errorText string) (*PINResult, error) {
	if len(cards) == 0 {
		return nil, fmt.Errorf("没有可用的卡片")
	}
	var result *PINResult
	var err error
	done := make(chan struct{})
	go func() {
		runtime.LockOSThread()
		defer runtime.UnlockOSThread()
		result, err = showPINDialog(cards, strings, errorText)
		close(done)
	}()
	<-done
	return result, err
}

func showPINDialog(cards []CardInfo, strings PINStrings, errorText string) (*PINResult, error) {
	dialogMu.Lock()
	currentDialog = &dialogState{
		cards:     cards,
		strings:   strings,
		errorText: errorText,
		err:       fmt.Errorf("用户取消"),
	}
	dialogMu.Unlock()

	hInstance, _, _ := procGetModuleHandleW.Call(0)

	className, _ := syscall.UTF16PtrFromString("TPMSmartCardPINDialog")
	wc := wndClassExW{
		cbSize:        uint32(unsafe.Sizeof(wndClassExW{})),
		style:         0x0003,
		lpfnWndProc:   syscall.NewCallback(pinDialogProc),
		hInstance:     hInstance,
		hbrBackground: 16,
		lpszClassName: className,
	}
	procRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc)))

	dlgWidth := int32(400)
	dlgHeight := int32(250)
	screenW, _, _ := procGetSystemMetrics.Call(uintptr(smCXScreen))
	screenH, _, _ := procGetSystemMetrics.Call(uintptr(smCYScreen))
	x := (int32(screenW) - dlgWidth) / 2
	y := (int32(screenH) - dlgHeight) / 2

	title, _ := syscall.UTF16PtrFromString(strings.Title)
	hwnd, _, _ := procCreateWindowExW.Call(
		0,
		uintptr(unsafe.Pointer(className)),
		uintptr(unsafe.Pointer(title)),
		uintptr(wsOverlapped|wsCaption|wsSysMenu|wsClipChildren),
		uintptr(x), uintptr(y),
		uintptr(dlgWidth), uintptr(dlgHeight),
		0, 0, hInstance, 0,
	)
	if hwnd == 0 {
		return nil, fmt.Errorf("创建对话框窗口失败")
	}

	procShowWindow.Call(hwnd, uintptr(swShow))
	procUpdateWindow.Call(hwnd)
	procSetForegroundWindow.Call(hwnd)

	var m msg
	for {
		ret, _, _ := procGetMessageW.Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if ret == 0 || int32(ret) == -1 {
			break
		}
		if isDialog, _, _ := procIsDialogMessageW.Call(hwnd, uintptr(unsafe.Pointer(&m))); isDialog == 0 {
			procTranslateMessage.Call(uintptr(unsafe.Pointer(&m)))
			procDispatchMessageW.Call(uintptr(unsafe.Pointer(&m)))
		}
	}

	dialogMu.Lock()
	result := currentDialog.result
	err := currentDialog.err
	currentDialog = nil
	dialogMu.Unlock()

	return result, err
}

func pinDialogProc(hwnd, message, wParam, lParam uintptr) uintptr {
	switch message {
	case wmCreate:
		createDialogControls(hwnd)
		return 0
	case wmCommand:
		ctrlID := int32(wParam & 0xFFFF)
		notifyCode := int32((wParam >> 16) & 0xFFFF)
		if notifyCode == bnClicked {
			switch ctrlID {
			case idOK:
				handleOK()
			case idCancel:
				handleCancel()
			}
		}
		return 0
	case wmClose:
		handleCancel()
		return 0
	case wmDestroy:
		procPostQuitMessage.Call(0)
		return 0
	}
	ret, _, _ := procDefWindowProcW.Call(hwnd, message, wParam, lParam)
	return ret
}

func createDialogControls(hwnd uintptr) {
	dialogMu.Lock()
	ds := currentDialog
	ds.hwnd = hwnd
	dialogMu.Unlock()

	hInstance, _, _ := procGetModuleHandleW.Call(0)
	hFont, _, _ := procGetStockObject.Call(uintptr(defaultGUIFont))
	ds.hFont = hFont

	staticClass, _ := syscall.UTF16PtrFromString("STATIC")
	comboClass, _ := syscall.UTF16PtrFromString("COMBOBOX")
	editClass, _ := syscall.UTF16PtrFromString("EDIT")
	buttonClass, _ := syscall.UTF16PtrFromString("BUTTON")

	label1Text, _ := syscall.UTF16PtrFromString(ds.strings.Card)
	hLabel1, _, _ := procCreateWindowExW.Call(
		0, uintptr(unsafe.Pointer(staticClass)),
		uintptr(unsafe.Pointer(label1Text)),
		uintptr(wsChild|wsVisible|ssLeft),
		20, 16, 350, 20,
		hwnd, idLabel1, hInstance, 0,
	)
	setFont(hLabel1, hFont)

	ds.hCombo, _, _ = procCreateWindowExW.Call(
		0, uintptr(unsafe.Pointer(comboClass)),
		0,
		uintptr(wsChild|wsVisible|wsTabStop|wsVScroll|cbsDropDownList|cbsHasStrings),
		20, 38, 350, 200,
		hwnd, idCombo, hInstance, 0,
	)
	setFont(ds.hCombo, hFont)
	for _, card := range ds.cards {
		itemText, _ := syscall.UTF16PtrFromString(card.CardName)
		procSendMessageW.Call(ds.hCombo, uintptr(cbAddString), 0, uintptr(unsafe.Pointer(itemText)))
	}
	procSendMessageW.Call(ds.hCombo, uintptr(cbSetCurSel), 0, 0)

	label2Text, _ := syscall.UTF16PtrFromString(ds.strings.PIN)
	hLabel2, _, _ := procCreateWindowExW.Call(
		0, uintptr(unsafe.Pointer(staticClass)),
		uintptr(unsafe.Pointer(label2Text)),
		uintptr(wsChild|wsVisible|ssLeft),
		20, 74, 350, 20,
		hwnd, idLabel2, hInstance, 0,
	)
	setFont(hLabel2, hFont)

	ds.hEdit, _, _ = procCreateWindowExW.Call(
		uintptr(wsExClientEdge), uintptr(unsafe.Pointer(editClass)),
		0,
		uintptr(wsChild|wsVisible|wsTabStop|esPassword|esAutoHScroll|wsBorder),
		20, 96, 350, 26,
		hwnd, idEdit, hInstance, 0,
	)
	setFont(ds.hEdit, hFont)

	errorText, _ := syscall.UTF16PtrFromString(ds.errorText)
	ds.hErr, _, _ = procCreateWindowExW.Call(
		0, uintptr(unsafe.Pointer(staticClass)),
		uintptr(unsafe.Pointer(errorText)),
		uintptr(wsChild|wsVisible|ssLeft),
		20, 132, 350, 20,
		hwnd, idErr, hInstance, 0,
	)
	setFont(ds.hErr, hFont)

	okText, _ := syscall.UTF16PtrFromString(ds.strings.OK)
	ds.hBtnOK, _, _ = procCreateWindowExW.Call(
		0, uintptr(unsafe.Pointer(buttonClass)),
		uintptr(unsafe.Pointer(okText)),
		uintptr(wsChild|wsVisible|wsTabStop|bsDefPushButton),
		170, 168, 95, 30,
		hwnd, idOK, hInstance, 0,
	)
	setFont(ds.hBtnOK, hFont)

	cancelText, _ := syscall.UTF16PtrFromString(ds.strings.Cancel)
	ds.hBtnCancel, _, _ = procCreateWindowExW.Call(
		0, uintptr(unsafe.Pointer(buttonClass)),
		uintptr(unsafe.Pointer(cancelText)),
		uintptr(wsChild|wsVisible|wsTabStop|bsPushButton),
		275, 168, 95, 30,
		hwnd, idCancel, hInstance, 0,
	)
	setFont(ds.hBtnCancel, hFont)

	if len(ds.cards) == 1 {
		procEnableWindow.Call(ds.hCombo, 0)
		procSetFocus.Call(ds.hEdit)
	} else {
		procSetFocus.Call(ds.hCombo)
	}
}

func setFont(hwnd, hFont uintptr) {
	procSendMessageW.Call(hwnd, uintptr(wmSetFont), hFont, 1)
}

func handleOK() {
	dialogMu.Lock()
	ds := currentDialog
	dialogMu.Unlock()
	if ds == nil {
		return
	}

	idx, _, _ := procSendMessageW.Call(ds.hCombo, uintptr(cbGetCurSel), 0, 0)
	if int32(idx) < 0 || int(idx) >= len(ds.cards) {
		idx = 0
	}

	pinLen, _, _ := procGetWindowTextLengthW.Call(ds.hEdit)
	if pinLen == 0 {
		procSetFocus.Call(ds.hEdit)
		return
	}
	pinBuf := make([]uint16, pinLen+1)
	procGetWindowTextW.Call(ds.hEdit, uintptr(unsafe.Pointer(&pinBuf[0])), uintptr(pinLen+1))
	pin := syscall.UTF16ToString(pinBuf)

	emptyStr, _ := syscall.UTF16PtrFromString("")
	procSetWindowTextW.Call(ds.hEdit, uintptr(unsafe.Pointer(emptyStr)))

	dialogMu.Lock()
	ds.result = &PINResult{CardUUID: ds.cards[idx].CardUUID, PIN: pin}
	ds.err = nil
	dialogMu.Unlock()

	for i := range pinBuf {
		pinBuf[i] = 0
	}
	procDestroyWindow.Call(ds.hwnd)
}

func handleCancel() {
	dialogMu.Lock()
	ds := currentDialog
	dialogMu.Unlock()
	if ds == nil {
		return
	}
	emptyStr, _ := syscall.UTF16PtrFromString("")
	procSetWindowTextW.Call(ds.hEdit, uintptr(unsafe.Pointer(emptyStr)))

	dialogMu.Lock()
	ds.result = nil
	ds.err = fmt.Errorf("用户取消了认证")
	dialogMu.Unlock()
	procDestroyWindow.Call(ds.hwnd)
}
