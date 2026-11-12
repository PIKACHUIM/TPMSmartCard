package sshagent

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"sync"
)

// Identity 是一张卡上可用的公钥身份。
type Identity struct {
	// KeyBlob 是 SSH wire 格式的公钥（例如 ssh-ed25519 的 "ssh-ed25519" + 32 字节）
	KeyBlob []byte
	Comment string
}

// Signer 由平台卡槽实现：列出身份并用卡片内私钥签名。
//
// 返回值是 **SSH 签名 blob**（字符串 algorithm + 字符串 signature），
// 不是裸签名；ECDSA 需要把 r||s 转成 mpint 对，这是 Profile 的责任。
type Signer interface {
	Identities(ctx context.Context) ([]Identity, error)
	Sign(ctx context.Context, keyBlob []byte, data []byte) ([]byte, error)
}

// Agent 处理单个连接的请求循环。
type Agent struct {
	Signer  Signer
	Logf    func(format string, args ...any)
	mu      sync.Mutex
	closing bool
}

func (a *Agent) logf(format string, args ...any) {
	if a.Logf != nil {
		a.Logf(format, args...)
		return
	}
	log.Printf(format, args...)
}

// Serve 在连接上处理请求，直到客户端断开或出错。
func (a *Agent) Serve(ctx context.Context, conn io.ReadWriteCloser) error {
	defer conn.Close()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		payload, err := readPacket(conn)
		if err != nil {
			if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
				return nil
			}
			return err
		}

		response, err := a.handle(ctx, payload)
		if err != nil {
			a.logf("sshagent: 请求失败: %v", err)
			response = failure()
		}
		if err := writePacket(conn, response); err != nil {
			return err
		}
	}
}

func (a *Agent) handle(ctx context.Context, payload []byte) ([]byte, error) {
	if len(payload) == 0 {
		return nil, ErrShortPacket
	}
	msgType := payload[0]
	rest := &reader{data: payload, pos: 1}

	switch msgType {
	case msgRequestIdentities:
		return a.handleIdentities(ctx)
	case msgSignRequest:
		return a.handleSign(ctx, rest)
	case msgExtension:
		return extensionResponse(), nil
	default:
		return failure(), nil
	}
}

func (a *Agent) handleIdentities(ctx context.Context) ([]byte, error) {
	if a.Signer == nil {
		return failure(), nil
	}
	identities, err := a.Signer.Identities(ctx)
	if err != nil {
		return failure(), err
	}
	out := &buffer{}
	out.byte(msgIdentitiesAnswer)
	out.uint32(uint32(len(identities)))
	for _, identity := range identities {
		out.string(identity.KeyBlob)
		out.string([]byte(identity.Comment))
	}
	return out.bytes(), nil
}

func (a *Agent) handleSign(ctx context.Context, rest *reader) ([]byte, error) {
	if a.Signer == nil {
		return failure(), nil
	}
	keyBlob, err := rest.string()
	if err != nil {
		return nil, err
	}
	data, err := rest.string()
	if err != nil {
		return nil, err
	}
	// flags（RSA SHA-2 / 用户认证）暂时不参与决策，由 Signer 依据 keyBlob 选择算法
	if _, err := rest.uint32(); err != nil {
		// 部分客户端省略 flags，按 0 处理
		_ = err
	}

	signature, err := a.Signer.Sign(ctx, keyBlob, data)
	if err != nil {
		return failure(), fmt.Errorf("签名失败: %w", err)
	}
	out := &buffer{}
	out.byte(msgSignResponse)
	out.string(signature)
	return out.bytes(), nil
}
