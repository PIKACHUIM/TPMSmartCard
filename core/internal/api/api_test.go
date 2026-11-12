package api

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/PIKACHUIM/tpmsmartcard/internal/platform"
)

// fakeSlot 用内存数据验证 API 契约，不触碰真实硬件。
type fakeSlot struct {
	cards []platform.Card
}

func (f *fakeSlot) ID() string          { return "fake" }
func (f *fakeSlot) Kind() platform.Kind { return platform.KindLocal }

func (f *fakeSlot) Info(context.Context) (platform.SlotInfo, error) {
	return platform.SlotInfo{
		ID:       "fake",
		Name:     "测试卡槽",
		Kind:     platform.KindLocal,
		Platform: "test",
		Detail:   "内存实现",
		Capability: platform.Capability{
			CreateCard: true,
			DeleteCard: true,
			Backup:     true,
			SSH:        true,
		},
	}, nil
}

func (f *fakeSlot) List(context.Context) ([]platform.Card, error) { return f.cards, nil }

func (f *fakeSlot) Create(_ context.Context, opt platform.CreateOptions) (platform.Card, error) {
	card := platform.Card{
		ID:        "fake-" + opt.Name,
		Name:      opt.Name,
		Kind:      platform.KindLocal,
		Platform:  "test",
		Security:  platform.SecurityMedium,
		CreatedAt: platform.Now(),
	}
	f.cards = append(f.cards, card)
	return card, nil
}

func (f *fakeSlot) Delete(_ context.Context, id string) error {
	kept := f.cards[:0]
	for _, card := range f.cards {
		if card.ID != id {
			kept = append(kept, card)
		}
	}
	f.cards = kept
	return nil
}

func (f *fakeSlot) SetPIN(context.Context, string, string, string) error { return nil }

func (f *fakeSlot) ListCertificates(_ context.Context, cardID string) ([]platform.Certificate, error) {
	return []platform.Certificate{{
		ID:           "cert-1",
		CardID:       cardID,
		Subject:      "CN=测试",
		Issuer:       "CN=测试 CA",
		Serial:       "01",
		KeyAlgorithm: "ECDSA",
		KeyUsage:     []string{"digitalSignature"},
		NotBefore:    "2026-01-01T00:00:00Z",
		NotAfter:     "2027-01-01T00:00:00Z",
		Fingerprint:  "AA:BB",
	}}, nil
}

func (f *fakeSlot) ImportCertificate(context.Context, string, platform.ImportOptions) error {
	return nil
}

func (f *fakeSlot) GenerateKey(context.Context, string, platform.KeyOptions) (platform.PublicKey, error) {
	return platform.PublicKey{}, platform.Unsupported("测试实现")
}

func (f *fakeSlot) Sign(context.Context, string, string, []byte, string) ([]byte, error) {
	return nil, platform.Unsupported("测试实现")
}

func (f *fakeSlot) Backup(context.Context, string, io.Writer) error {
	return platform.Unsupported("测试实现")
}

func newTestServer(t *testing.T) (*httptest.Server, *fakeSlot) {
	t.Helper()
	slot := &fakeSlot{}
	server := New(Options{
		Slots:    []platform.Slot{slot},
		Platform: "test",
		Version:  "test",
	})
	ts := httptest.NewServer(server.Handler())
	t.Cleanup(ts.Close)
	return ts, slot
}

func getJSON(t *testing.T, url string, target any) int {
	t.Helper()
	resp, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if target != nil && len(body) > 0 {
		if err := json.Unmarshal(body, target); err != nil {
			t.Fatalf("unmarshal %s: %v", body, err)
		}
	}
	return resp.StatusCode
}

type envelope[T any] struct {
	Done bool `json:"done"`
	Data T    `json:"data"`
}

func TestHealthReportsCapability(t *testing.T) {
	ts, _ := newTestServer(t)
	var payload envelope[healthPayload]
	if status := getJSON(t, ts.URL+"/api/health", &payload); status != http.StatusOK {
		t.Fatalf("status = %d", status)
	}
	if !payload.Done || payload.Data.Platform != "test" {
		t.Fatalf("unexpected health: %+v", payload.Data)
	}
	if !payload.Data.Capability.CreateCard {
		t.Fatal("expected create_card capability")
	}
}

func TestCardsListAndCreate(t *testing.T) {
	ts, _ := newTestServer(t)

	var list envelope[struct {
		Cards []platform.Card `json:"cards"`
	}]
	getJSON(t, ts.URL+"/api/v1/desktop/cards", &list)
	if len(list.Data.Cards) != 0 {
		t.Fatalf("expected empty cards, got %d", len(list.Data.Cards))
	}

	// 缺少 X-Requested-With：写操作必须被拒绝（CSRF 防线）
	resp, err := http.Post(ts.URL+"/api/v1/desktop/cards", "application/json",
		strings.NewReader(`{"name":"财务卡","pin":"123456"}`))
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401 without header, got %d", resp.StatusCode)
	}

	req, _ := http.NewRequest(http.MethodPost, ts.URL+"/api/v1/desktop/cards",
		strings.NewReader(`{"name":"财务卡","pin":"123456"}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Requested-With", "tpmsc")
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusCreated {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("status = %d, body = %s", resp.StatusCode, body)
	}

	getJSON(t, ts.URL+"/api/v1/desktop/cards", &list)
	if len(list.Data.Cards) != 1 || list.Data.Cards[0].Name != "财务卡" {
		t.Fatalf("unexpected cards: %+v", list.Data.Cards)
	}

	var certs envelope[struct {
		Certificates []platform.Certificate `json:"certificates"`
	}]
	getJSON(t, ts.URL+"/api/v1/desktop/certificates?card_id=fake-财务卡", &certs)
	if len(certs.Data.Certificates) != 1 || certs.Data.Certificates[0].Subject != "CN=测试" {
		t.Fatalf("unexpected certificates: %+v", certs.Data.Certificates)
	}
}

func TestDeleteCard(t *testing.T) {
	ts, slot := newTestServer(t)
	_, _ = slot.Create(context.Background(), platform.CreateOptions{Name: "临时卡", PIN: "123456"})

	req, _ := http.NewRequest(http.MethodDelete, ts.URL+"/api/v1/desktop/cards/fake-临时卡", nil)
	req.Header.Set("X-Requested-With", "tpmsc")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d", resp.StatusCode)
	}
	if len(slot.cards) != 0 {
		t.Fatalf("card should be deleted, got %+v", slot.cards)
	}
}

func TestStatsShape(t *testing.T) {
	ts, _ := newTestServer(t)
	var stats envelope[[]map[string]any]
	if status := getJSON(t, ts.URL+"/api/v1/desktop/stats", &stats); status != http.StatusOK {
		t.Fatalf("status = %d", status)
	}
	if len(stats.Data) != 4 {
		t.Fatalf("expected 4 stats, got %d", len(stats.Data))
	}
	for _, item := range stats.Data {
		for _, key := range []string{"label", "value", "hint"} {
			if _, ok := item[key]; !ok {
				t.Fatalf("stat missing %s: %+v", key, item)
			}
		}
	}
}
