//go:build windows

package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
)

// CTAP2 命令码
const (
	ctapMakeCredential byte = 0x01
	ctapGetAssertion   byte = 0x02
	ctapGetInfo        byte = 0x04
	ctapClientPin      byte = 0x06
	ctapCancel         byte = 0x11
)

// CTAP 状态码
const (
	ctapOK              byte = 0x00
	ctapInvalidCommand  byte = 0x01
	ctapOther           byte = 0x7F
	ctapOperationDenied byte = 0x27
	ctapPINRequired     byte = 0x36
)

// 后端登录返回值（非 CTAP 状态码，仅本协议内部使用）
const (
	loginPINIncorrect = 0xA0
	loginPINLocked    = 0xA1
	loginNoSuchCard   = 0xA2
)

// PINStrings 是 PIN 对话框的界面文案，由 Python 侧按当前语言传入。
type PINStrings struct {
	Title  string
	Card   string
	PIN    string
	OK     string
	Cancel string
	Wrong  string
}

// CTAPProxy 实现 virtual-fido 的 CTAPHIDClient：把 CTAP2 CBOR 原样转发给
// Python 后端，并把后端的 CTAP 状态码原样返回（不再做 PKCS#11 错误码映射，
// 这样 NO_CREDENTIALS / CREDENTIAL_EXCLUDED 等错误语义不会丢失）。
type CTAPProxy struct {
	pipe         string
	strings      PINStrings
	onPINSuccess func()
}

func NewCTAPProxy(pipe string, strings PINStrings) *CTAPProxy {
	return &CTAPProxy{pipe: pipe, strings: strings}
}

// HandleMessage 处理一条 CTAP2 消息：data = [1 字节命令码][CBOR 参数]。
func (proxy *CTAPProxy) HandleMessage(data []byte) []byte {
	if len(data) == 0 {
		return []byte{ctapInvalidCommand}
	}
	cmd := data[0]
	body := data[1:]

	if cmd == ctapGetInfo {
		return proxy.getInfo()
	}
	if cmd == ctapCancel {
		// Cancel 没有响应体；后端只做清理
		if _, err := ipcCall(proxy.pipe, cmdCancel, []byte(`{}`)); err != nil {
			appLog.Printf("Cancel 转发失败: %v", err)
		}
		return []byte{}
	}

	var ipcCmd uint32
	switch cmd {
	case ctapMakeCredential:
		ipcCmd = cmdMakeCredential
	case ctapGetAssertion:
		ipcCmd = cmdGetAssertion
	case ctapClientPin:
		// clientPIN：PIN 由平台（Windows 安全对话框）收集，这里只做透传，
		// 弹窗逻辑绝不能介入，否则又会出现「两个框并存 + 触摸超时」
		ipcCmd = cmdClientPin
	default:
		appLog.Printf("不支持的 CTAP2 命令: 0x%02X", cmd)
		return []byte{ctapInvalidCommand}
	}

	reqJSON, _ := json.Marshal(map[string]string{
		"cbor_req": base64.StdEncoding.EncodeToString(body),
	})

	wrongPIN := ""
	for attempt := 0; attempt < 3; attempt++ {
		respJSON, err := ipcCall(proxy.pipe, ipcCmd, reqJSON)
		if err != nil {
			appLog.Printf("IPC 调用失败: %v", err)
			return []byte{ctapOther}
		}
		var wrapper ipcResponse
		if err := json.Unmarshal(respJSON, &wrapper); err != nil {
			appLog.Printf("解析后端响应失败: %v", err)
			return []byte{ctapOther}
		}

		// clientPIN 模式：后端明确要求「交给平台处理 PIN」，直接把 0x36 返回，
		// 让 Windows 弹它自己的 PIN 对话框（只有这一个框，也不会撞上触摸超时）
		if wrapper.RV == uint32(ctapPINRequired) && platformPin(wrapper.Data) {
			appLog.Printf("CTAP 命令 0x%02X 需要平台输入 PIN（clientPIN 模式）", cmd)
			return []byte{ctapPINRequired}
		}

		// 内置 UV 模式：弹窗 → 登录 → 让 Windows 重新枚举设备 → 浏览器重试
		if wrapper.RV == uint32(ctapPINRequired) && (cmd == ctapMakeCredential || cmd == ctapGetAssertion) {
			cards, err := parseCards(wrapper.Data)
			if err != nil || len(cards) == 0 {
				appLog.Printf("没有可用于 FIDO 的卡片: %v", err)
				return []byte{ctapPINRequired}
			}
			appLog.Printf("需要 PIN 认证，可用卡片 %d 张", len(cards))
			result, err := PromptPIN(cards, proxy.strings, wrongPIN)
			if err != nil {
				appLog.Printf("用户取消 PIN 输入: %v", err)
				return []byte{ctapPINRequired}
			}
			rv, err := proxy.login(result)
			if err != nil {
				appLog.Printf("登录调用失败: %v", err)
				return []byte{ctapOther}
			}
			switch rv {
			case 0:
				appLog.Printf("PIN 认证成功，重启虚拟设备以让 Windows 重试")
				if proxy.onPINSuccess != nil {
					go proxy.onPINSuccess()
				}
				return []byte{ctapOperationDenied}
			case loginPINIncorrect:
				wrongPIN = proxy.strings.Wrong
				continue
			case loginPINLocked:
				wrongPIN = "PIN 已锁定，请先用 PUK 解锁"
				continue
			case loginNoSuchCard:
				wrongPIN = "卡片已不存在，请重新选择"
				continue
			default:
				wrongPIN = fmt.Sprintf("认证失败（%d）", rv)
				continue
			}
		}

		if wrapper.RV != 0 {
			// 后端直接返回 CTAP 状态码
			code := byte(wrapper.RV)
			appLog.Printf("CTAP 命令 0x%02X 返回错误 0x%02X", cmd, code)
			return []byte{code}
		}

		var data struct {
			CBOR []byte `json:"cbor_resp"`
		}
		if len(wrapper.Data) > 0 {
			if err := json.Unmarshal(wrapper.Data, &data); err != nil {
				appLog.Printf("解析 cbor_resp 失败: %v", err)
				return []byte{ctapOther}
			}
		}
		appLog.Printf("CTAP 命令 0x%02X 成功，响应 %d 字节", cmd, len(data.CBOR))
		return append([]byte{ctapOK}, data.CBOR...)
	}

	appLog.Printf("PIN 连续失败，放弃本次请求")
	return []byte{ctapPINRequired}
}

// getInfo 走单独的命令码：后端返回 {"rv":0,"data":{"cbor_info":"..."}}。
func (proxy *CTAPProxy) getInfo() []byte {
	respJSON, err := ipcCall(proxy.pipe, cmdGetInfo, []byte(`{}`))
	if err != nil {
		appLog.Printf("GetInfo IPC 失败: %v", err)
		return []byte{ctapOther}
	}
	var wrapper struct {
		RV   uint32 `json:"rv"`
		Data struct {
			CBOR []byte `json:"cbor_info"`
		} `json:"data"`
	}
	if err := json.Unmarshal(respJSON, &wrapper); err != nil {
		appLog.Printf("解析 GetInfo 响应失败: %v", err)
		return []byte{ctapOther}
	}
	if wrapper.RV != 0 {
		return []byte{byte(wrapper.RV)}
	}
	return append([]byte{ctapOK}, wrapper.Data.CBOR...)
}

// login 用所选卡片 + PIN 向后端建立会话（后端据此校验卡片 PIN 并解出主密钥）。
func (proxy *CTAPProxy) login(result *PINResult) (uint32, error) {
	reqJSON, _ := json.Marshal(map[string]string{
		"card_uuid": result.CardUUID,
		"pin":       result.PIN,
	})
	respJSON, err := ipcCall(proxy.pipe, cmdLogin, reqJSON)
	if err != nil {
		return 0, err
	}
	var wrapper struct {
		RV uint32 `json:"rv"`
	}
	if len(respJSON) == 0 {
		return 0, fmt.Errorf("空响应")
	}
	if err := json.Unmarshal(respJSON, &wrapper); err != nil {
		return 0, err
	}
	return wrapper.RV, nil
}

// ipcResponse 是后端响应的通用包装。
type ipcResponse struct {
	RV   uint32          `json:"rv"`
	Data json.RawMessage `json:"data"`
}

// platformPin 判断后端是否要求「PIN 由平台收集」（clientPIN 模式）。
// 为真时本程序不弹自带对话框，直接把 0x36 交回平台。
func platformPin(data json.RawMessage) bool {
	if len(data) == 0 {
		return false
	}
	var payload struct {
		PlatformPIN bool `json:"platform_pin"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		return false
	}
	return payload.PlatformPIN
}

// parseCards 解析 PIN 对话框需要的卡片列表：{"cards":[{"card_uuid","card_name"}]}
func parseCards(data json.RawMessage) ([]CardInfo, error) {
	if len(data) == 0 {
		return nil, fmt.Errorf("响应里没有卡片列表")
	}
	var payload struct {
		Cards []CardInfo `json:"cards"`
	}
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, err
	}
	return payload.Cards, nil
}
