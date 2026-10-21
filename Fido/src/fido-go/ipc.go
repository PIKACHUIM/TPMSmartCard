//go:build windows

package main

import (
	"encoding/binary"
	"fmt"
	"io"
	"time"

	"github.com/Microsoft/go-winio"
)

// IPC 帧协议（与 TPMSmartCard 的 Module/FidoIpc.py 完全一致）：
//
//	请求：[Magic(4B,BE)][Cmd(4B,BE)][Len(4B,BE)][JSON Payload]
//	响应：[Magic(4B,BE)][Cmd(4B,BE)][Len(4B,BE)][{"rv":N,"data":{...}}]
//
// 每次请求新建一条连接（与参考项目一致），后端是单线程顺序处理，
// 因此不存在并发写同一连接的问题。
const (
	ipcMagic      uint32 = 0x504B3131 // "PK11"
	ipcHeaderSize        = 12

	// FIDO 命令码
	cmdGetInfo        uint32 = 0x0300
	cmdMakeCredential uint32 = 0x0301
	cmdGetAssertion   uint32 = 0x0302
	cmdCancel         uint32 = 0x0303
	cmdLogin          uint32 = 0x0304
	// 平台自己收集 PIN 时（clientPIN 模式），CTAP 的 0x06 命令原样转发给后端
	cmdClientPin uint32 = 0x0305
)

// ipcCall 发送一次请求并返回响应 JSON（不含帧头）。
func ipcCall(pipe string, cmd uint32, reqJSON []byte) ([]byte, error) {
	timeout := 5 * time.Second
	conn, err := winio.DialPipe(pipe, &timeout)
	if err != nil {
		return nil, fmt.Errorf("连接后端管道失败（TPMSmartCard 的 FIDO 服务未启动？）: %w", err)
	}
	defer conn.Close()

	header := make([]byte, ipcHeaderSize)
	binary.BigEndian.PutUint32(header[0:4], ipcMagic)
	binary.BigEndian.PutUint32(header[4:8], cmd)
	binary.BigEndian.PutUint32(header[8:12], uint32(len(reqJSON)))

	if _, err := conn.Write(header); err != nil {
		return nil, fmt.Errorf("发送帧头失败: %w", err)
	}
	if len(reqJSON) > 0 {
		if _, err := conn.Write(reqJSON); err != nil {
			return nil, fmt.Errorf("发送请求体失败: %w", err)
		}
	}

	respHeader := make([]byte, ipcHeaderSize)
	if _, err := io.ReadFull(conn, respHeader); err != nil {
		return nil, fmt.Errorf("读取响应帧头失败: %w", err)
	}
	if magic := binary.BigEndian.Uint32(respHeader[0:4]); magic != ipcMagic {
		return nil, fmt.Errorf("响应魔数不匹配: 0x%08X", magic)
	}
	respLen := binary.BigEndian.Uint32(respHeader[8:12])
	if respLen == 0 {
		return nil, nil
	}
	respJSON := make([]byte, respLen)
	if _, err := io.ReadFull(conn, respJSON); err != nil {
		return nil, fmt.Errorf("读取响应体失败: %w", err)
	}
	return respJSON, nil
}
