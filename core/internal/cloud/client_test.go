package cloud

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/PIKACHUIM/tpmsmartcard/internal/crypto"
)

func TestFetchByCode(t *testing.T) {
	salt := crypto.NewSalt()
	const iterations = 1000
	const code = "ABCD-EFGH-JKMN-PQRS"
	plaintext := []byte(`{"v":1,"pfx":"Zm9v","pfxkey":"pw","label":"demo"}`)
	vaults, err := crypto.SealWithCode(code, salt, iterations, plaintext)
	if err != nil {
		t.Fatal(err)
	}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/card/get/cert" && r.URL.Path != "/card/get/code" {
			http.NotFound(w, r)
			return
		}
		if crypto.NormalizeCode(r.URL.Query().Get("code")) != "ABCDEFGHJKMNPQRS" {
			_, _ = w.Write([]byte(`{"flag":false,"data":null}`))
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"flag": true,
			"data": map[string]any{
				"vaults":     vaults,
				"salt":       base64.StdEncoding.EncodeToString(salt),
				"iterations": iterations,
				"kdf":        "PBKDF2-SHA256",
				"label":      "demo",
			},
		})
	}))
	defer server.Close()

	client := New(server.URL)
	delivered, err := client.FetchByCode(context.Background(), code)
	if err != nil {
		t.Fatal(err)
	}
	if string(delivered.Payload) != string(plaintext) {
		t.Fatalf("payload = %s", delivered.Payload)
	}

	decoded, err := Decode(delivered.Payload)
	if err != nil {
		t.Fatal(err)
	}
	if decoded.PFX != "Zm9v" {
		t.Fatalf("pfx = %q", decoded.PFX)
	}
}

func TestFetchByCodeWrongCode(t *testing.T) {
	salt := crypto.NewSalt()
	vaults, _ := crypto.SealWithCode("ABCD-EFGH-JKMN-PQRS", salt, 1000, []byte("x"))
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"flag": true,
			"data": map[string]any{
				"vaults":     vaults,
				"salt":       base64.StdEncoding.EncodeToString(salt),
				"iterations": 1000,
			},
		})
	}))
	defer server.Close()

	if _, err := New(server.URL).FetchByCode(context.Background(), "ZZZZ-ZZZZ-ZZZZ-ZZZZ"); err == nil {
		t.Fatal("expected decryption error")
	}
}

func TestFetchByPublicKey(t *testing.T) {
	plaintext := []byte(`{"v":1,"pfx":"YmFy"}`)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = r.ParseForm()
		clientPub := r.FormValue("pubkey")
		sealed, err := crypto.SealForPublicKey(clientPub, plaintext)
		if err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"flag": true,
			"data": map[string]any{
				"vaults": sealed.Vaults,
				"pubkey": sealed.PublicKey,
				"pfxkey": "pw",
			},
		})
	}))
	defer server.Close()

	delivered, err := New(server.URL).FetchByPublicKey(context.Background(), server.URL)
	if err != nil {
		t.Fatal(err)
	}
	if string(delivered.Payload) != string(plaintext) {
		t.Fatalf("payload = %s", delivered.Payload)
	}
	if delivered.PFXKey != "pw" {
		t.Fatalf("pfxkey = %q", delivered.PFXKey)
	}
}

func TestParseVaultMissingRecord(t *testing.T) {
	if _, err := parseVault([]byte(`{"flag":false,"data":null}`)); err == nil {
		t.Fatal("expected error")
	}
}
