package sshagent

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/binary"
	"errors"
	"net"
	"testing"
)

// fakeSigner 用内存中的 Ed25519 私钥模拟卡片。
type fakeSigner struct {
	private ed25519.PrivateKey
	public  ed25519.PublicKey
	blob    []byte
}

func newFakeSigner(t *testing.T) *fakeSigner {
	t.Helper()
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	blob := &buffer{}
	blob.string([]byte("ssh-ed25519"))
	blob.string(public)
	return &fakeSigner{private: private, public: public, blob: blob.bytes()}
}

func (f *fakeSigner) Identities(context.Context) ([]Identity, error) {
	return []Identity{{KeyBlob: f.blob, Comment: "卡片测试密钥"}}, nil
}

func (f *fakeSigner) Sign(_ context.Context, keyBlob, data []byte) ([]byte, error) {
	if !bytes.Equal(keyBlob, f.blob) {
		return nil, errUnknownKey
	}
	signature := ed25519.Sign(f.private, data)
	out := &buffer{}
	out.string([]byte("ssh-ed25519"))
	out.string(signature)
	return out.bytes(), nil
}

var errUnknownKey = errors.New("unknown key")

func TestRequestIdentitiesAndSign(t *testing.T) {
	signer := newFakeSigner(t)
	agent := &Agent{Signer: signer, Logf: t.Logf}

	client, server := net.Pipe()
	defer client.Close()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { _ = agent.Serve(ctx, server) }()

	// 1) 请求身份列表
	if err := writePacket(client, []byte{msgRequestIdentities}); err != nil {
		t.Fatal(err)
	}
	response, err := readPacket(client)
	if err != nil {
		t.Fatal(err)
	}
	if response[0] != msgIdentitiesAnswer {
		t.Fatalf("message type = %d", response[0])
	}
	r := &reader{data: response, pos: 1}
	count, _ := r.uint32()
	if count != 1 {
		t.Fatalf("identities = %d", count)
	}
	keyBlob, _ := r.string()
	comment, _ := r.string()
	if !bytes.Equal(keyBlob, signer.blob) || string(comment) != "卡片测试密钥" {
		t.Fatalf("unexpected identity: %q %q", keyBlob, comment)
	}

	// 2) 签名请求
	data := []byte("session-data")
	request := &buffer{}
	request.byte(msgSignRequest)
	request.string(signer.blob)
	request.string(data)
	request.uint32(0)
	if err := writePacket(client, request.bytes()); err != nil {
		t.Fatal(err)
	}
	signResponse, err := readPacket(client)
	if err != nil {
		t.Fatal(err)
	}
	if signResponse[0] != msgSignResponse {
		t.Fatalf("message type = %d", signResponse[0])
	}
	sr := &reader{data: signResponse, pos: 1}
	signatureBlob, _ := sr.string()
	sb := &reader{data: signatureBlob}
	algorithm, _ := sb.string()
	signature, _ := sb.string()
	if string(algorithm) != "ssh-ed25519" {
		t.Fatalf("algorithm = %q", algorithm)
	}
	if !ed25519.Verify(signer.public, data, signature) {
		t.Fatal("signature verification failed")
	}
}

func TestUnknownMessageReturnsFailure(t *testing.T) {
	agent := &Agent{Signer: newFakeSigner(t), Logf: t.Logf}
	response, err := agent.handle(context.Background(), []byte{99})
	if err != nil {
		t.Fatal(err)
	}
	if len(response) != 1 || response[0] != msgFailure {
		t.Fatalf("response = %v", response)
	}
}

func TestPacketTooLarge(t *testing.T) {
	payload := make([]byte, MaxPacket+1)
	header := make([]byte, 4)
	binary.BigEndian.PutUint32(header, uint32(len(payload)))
	_, err := readPacket(bytes.NewReader(append(header, payload...)))
	if err == nil {
		t.Fatal("expected ErrPacketTooLarge")
	}
}

func TestTruncatedPacket(t *testing.T) {
	header := make([]byte, 4)
	binary.BigEndian.PutUint32(header, 10)
	_, err := readPacket(bytes.NewReader(append(header, []byte{1, 2}...)))
	if err == nil {
		t.Fatal("expected short packet error")
	}
}
