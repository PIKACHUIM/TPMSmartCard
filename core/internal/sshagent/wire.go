// Package sshagent 实现 SSH agent 协议（draft-miller-ssh-agent）的服务端。
//
// 目的：让 `ssh` 直接用卡片上的私钥登录，而不是把私钥落到磁盘。
// 本包只负责「协议帧 + 请求分发」，真正的签名由 Signer 实现调用平台卡槽完成。
package sshagent

import (
	"encoding/binary"
	"errors"
	"fmt"
	"io"
)

// SSH agent 消息号（与 RFC 草案一致）。
const (
	msgFailure             = 5
	msgRequestIdentities   = 11
	msgIdentitiesAnswer    = 12
	msgSignRequest         = 13
	msgSignResponse        = 14
	msgExtension           = 27
)

// MaxPacket 是单帧上限。SSH agent 的实际报文远小于此值，
// 限制上限可以避免恶意客户端用超长帧耗尽内存。
const MaxPacket = 256 * 1024

var (
	// ErrPacketTooLarge 表示帧长度超过 MaxPacket。
	ErrPacketTooLarge = errors.New("sshagent: 报文超出上限")
	// ErrShortPacket 表示帧被截断。
	ErrShortPacket = errors.New("sshagent: 报文不完整")
)

// buffer 是顺序写入 SSH wire 格式（uint32 长度前缀）的辅助类型。
type buffer struct {
	data []byte
}

func (b *buffer) byte(value byte) {
	b.data = append(b.data, value)
}

func (b *buffer) uint32(value uint32) {
	var tmp [4]byte
	binary.BigEndian.PutUint32(tmp[:], value)
	b.data = append(b.data, tmp[:]...)
}

func (b *buffer) string(value []byte) {
	b.uint32(uint32(len(value)))
	b.data = append(b.data, value...)
}

func (b *buffer) bytes() []byte { return b.data }

// reader 是顺序读取 SSH wire 格式的辅助类型。
type reader struct {
	data []byte
	pos  int
}

func (r *reader) remaining() int { return len(r.data) - r.pos }

func (r *reader) byte() (byte, error) {
	if r.remaining() < 1 {
		return 0, ErrShortPacket
	}
	value := r.data[r.pos]
	r.pos++
	return value, nil
}

func (r *reader) uint32() (uint32, error) {
	if r.remaining() < 4 {
		return 0, ErrShortPacket
	}
	value := binary.BigEndian.Uint32(r.data[r.pos : r.pos+4])
	r.pos += 4
	return value, nil
}

func (r *reader) string() ([]byte, error) {
	length, err := r.uint32()
	if err != nil {
		return nil, err
	}
	if int(length) > r.remaining() {
		return nil, ErrShortPacket
	}
	value := r.data[r.pos : r.pos+int(length)]
	r.pos += int(length)
	return value, nil
}

// readPacket 读取一个长度前缀帧。
func readPacket(r io.Reader) ([]byte, error) {
	var header [4]byte
	if _, err := io.ReadFull(r, header[:]); err != nil {
		return nil, err
	}
	length := binary.BigEndian.Uint32(header[:])
	if length == 0 {
		return nil, ErrShortPacket
	}
	if length > MaxPacket {
		return nil, fmt.Errorf("%w: %d 字节", ErrPacketTooLarge, length)
	}
	payload := make([]byte, length)
	if _, err := io.ReadFull(r, payload); err != nil {
		return nil, err
	}
	return payload, nil
}

// writePacket 写入一个长度前缀帧。
func writePacket(w io.Writer, payload []byte) error {
	var header [4]byte
	binary.BigEndian.PutUint32(header[:], uint32(len(payload)))
	if _, err := w.Write(header[:]); err != nil {
		return err
	}
	_, err := w.Write(payload)
	return err
}

func failure() []byte { return []byte{msgFailure} }

// genericFailure 用于不支持的消息类型；返回 success(6) 更符合部分客户端预期，
// 这里按草案返回 FAILURE，客户端会退化为「无身份」。
func extensionResponse() []byte { return failure() }
