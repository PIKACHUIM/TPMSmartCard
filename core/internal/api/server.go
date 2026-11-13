// Package api 提供本地 HTTP API（Wails 外壳与浏览器共用）。
//
// 安全边界：
//   - 只监听 127.0.0.1；
//   - 写操作要求 `X-Requested-With: tpmsc`（跨站请求无法携带自定义头而不触发预检）；
//   - 可选 `TPMSC_LOCAL_TOKEN`，脚本可用 `Authorization: Bearer` 或 `?token=`。
package api

import (
	"context"
	"encoding/json"
	"io"
	"io/fs"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/PIKACHUIM/tpmsmartcard/internal/platform"
	"github.com/PIKACHUIM/tpmsmartcard/internal/protocol"
)

// Options 是服务配置。
type Options struct {
	Slots      []platform.Slot
	BackupsDir string
	UIFS       fs.FS
	Token      string
	Platform   string
	Version    string
	SlotsFunc  func() []platform.Slot
}

// Server 是本地 API 服务。
type Server struct {
	opts      Options
	broker    *broker
	mu        sync.Mutex
	startedAt time.Time
}

// New 构造服务。
func New(opts Options) *Server {
	if opts.Version == "" {
		opts.Version = protocol.Version
	}
	if opts.SlotsFunc == nil {
		opts.SlotsFunc = func() []platform.Slot { return opts.Slots }
	}
	return &Server{opts: opts, broker: newBroker(), startedAt: time.Now()}
}

// Handler 返回可挂载的 http.Handler。
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/health", s.handleHealth)
	mux.HandleFunc("GET /api/v1/health", s.handleHealth)
	mux.HandleFunc("GET /api/v1/desktop/stats", s.handleStats)
	mux.HandleFunc("GET /api/v1/desktop/cards", s.handleListCards)
	mux.HandleFunc("POST /api/v1/desktop/cards", s.handleCreateCard)
	mux.HandleFunc("DELETE /api/v1/desktop/cards/{id}", s.handleDeleteCard)
	mux.HandleFunc("POST /api/v1/desktop/cards/{id}/pin", s.handleSetPIN)
	mux.HandleFunc("GET /api/v1/desktop/certificates", s.handleListCertificates)
	mux.HandleFunc("POST /api/v1/desktop/certificates", s.handleImportCertificate)
	mux.HandleFunc("GET /api/v1/desktop/certificates/{certID}/pem", s.handleExportCertificate)
	mux.HandleFunc("GET /api/v1/desktop/backups", s.handleListBackups)
	mux.HandleFunc("POST /api/v1/desktop/backups", s.handleCreateBackup)
	mux.HandleFunc("POST /api/v1/desktop/backups/{file}/restore", s.handleRestoreBackup)
	mux.HandleFunc("GET /api/v1/desktop/diagnostics", s.handleDiagnostics)
	mux.HandleFunc("GET /api/v1/desktop/autostart", s.handleAutostart)
	mux.HandleFunc("POST /api/v1/desktop/autostart", s.handleSetAutostart)
	mux.HandleFunc("GET /api/v1/events", s.handleEvents)
	mux.Handle("/", s.uiHandler())

	return s.guard(mux)
}

func (s *Server) guard(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Cache-Control", "no-store")

		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			// 自定义头会触发 CORS 预检，跨站页面无法伪造；这是不依赖 Cookie 的 CSRF 防线
			if !s.tokenValid(r) && r.Header.Get("X-Requested-With") != "tpmsc" {
				writeError(w, http.StatusUnauthorized, protocol.ErrUnauth, "缺少 X-Requested-With 或本地令牌")
				return
			}
			if origin := r.Header.Get("Origin"); origin != "" && !sameHost(origin, r.Host) {
				writeError(w, http.StatusForbidden, protocol.ErrForbidden, "跨站请求被拒绝")
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) tokenValid(r *http.Request) bool {
	// 未配置令牌时不能把「空 == 空」当成通过，否则等于没有 CSRF 防线
	if s.opts.Token == "" {
		return false
	}
	if auth := r.Header.Get("Authorization"); strings.HasPrefix(auth, "Bearer ") {
		return strings.TrimSpace(strings.TrimPrefix(auth, "Bearer ")) == s.opts.Token
	}
	if header := r.Header.Get("X-Local-Token"); header != "" {
		return header == s.opts.Token
	}
	return r.URL.Query().Get("token") == s.opts.Token
}

func sameHost(origin, host string) bool {
	trimmed := strings.TrimPrefix(strings.TrimPrefix(origin, "http://"), "https://")
	return trimmed == host
}

func (s *Server) uiHandler() http.Handler {
	fsys := s.opts.UIFS
	if fsys == nil {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "text/plain; charset=utf-8")
			_, _ = w.Write([]byte("前端产物未构建。\n运行 `npm run build -w @tpmsc/web`，或在桌面构建中使用 -tags desktop。\n"))
		})
	}
	fileServer := http.FileServer(http.FS(fsys))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimPrefix(r.URL.Path, "/")
		if path == "" {
			path = "index.html"
		}
		if _, err := fs.Stat(fsys, path); err != nil {
			// SPA 兜底：未知路径交给 index.html（HashRouter 不会用到，但直接访问 /cards 时需要）
			r.URL.Path = "/"
		}
		fileServer.ServeHTTP(w, r)
	})
}

func (s *Server) catalog(ctx context.Context) ([]platform.Card, []string) {
	var cards []platform.Card
	var warnings []string
	for _, slot := range s.opts.SlotsFunc() {
		items, err := slot.List(ctx)
		if err != nil {
			warnings = append(warnings, slot.ID()+": "+err.Error())
			continue
		}
		cards = append(cards, items...)
	}
	return cards, warnings
}

func (s *Server) resolve(ctx context.Context, cardID string) (platform.Slot, platform.Card, error) {
	for _, slot := range s.opts.SlotsFunc() {
		items, err := slot.List(ctx)
		if err != nil {
			continue
		}
		for _, card := range items {
			if card.ID == cardID {
				return slot, card, nil
			}
		}
	}
	return nil, platform.Card{}, platform.ErrNotFound
}

// ---- 响应助手 ----

type okEnvelope struct {
	Done bool `json:"done"`
	Data any  `json:"data"`
}

type errEnvelope struct {
	Done   bool   `json:"done"`
	Error  string `json:"error"`
	Code   string `json:"code"`
	Detail string `json:"detail,omitempty"`
}

func writeJSON(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(okEnvelope{Done: true, Data: data})
}

func writeError(w http.ResponseWriter, status int, code, message string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(errEnvelope{Done: false, Error: message, Code: code})
}

func writePlatformError(w http.ResponseWriter, err error) {
	status := http.StatusInternalServerError
	code := protocol.ErrInternal
	message := err.Error()
	switch {
	case strings.Contains(message, platform.ErrUnsupported.Error()):
		status, code = http.StatusNotImplemented, protocol.ErrBadRequest
	case strings.Contains(message, platform.ErrNotElevated.Error()):
		status, code = http.StatusForbidden, protocol.ErrForbidden
	case strings.Contains(message, platform.ErrRemoteSession.Error()):
		status, code = http.StatusConflict, protocol.ErrConflict
	case strings.Contains(message, platform.ErrNotFound.Error()):
		status, code = http.StatusNotFound, protocol.ErrNotFound
	case strings.Contains(message, platform.ErrPinRequired.Error()):
		status, code = http.StatusBadRequest, protocol.ErrBadRequest
	}
	writeError(w, status, code, message)
}

func decodeJSON(r *http.Request, target any) error {
	defer r.Body.Close()
	decoder := json.NewDecoder(io.LimitReader(r.Body, 1<<20))
	return decoder.Decode(target)
}

// ---- SSE ----

type broker struct {
	mu      sync.Mutex
	clients map[chan []byte]struct{}
}

func newBroker() *broker {
	return &broker{clients: make(map[chan []byte]struct{})}
}

func (b *broker) subscribe() chan []byte {
	ch := make(chan []byte, 8)
	b.mu.Lock()
	b.clients[ch] = struct{}{}
	b.mu.Unlock()
	return ch
}

func (b *broker) unsubscribe(ch chan []byte) {
	b.mu.Lock()
	delete(b.clients, ch)
	close(ch)
	b.mu.Unlock()
}

func (b *broker) publish(event any) {
	payload, err := json.Marshal(event)
	if err != nil {
		return
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	for ch := range b.clients {
		select {
		case ch <- payload:
		default:
		}
	}
}

func (s *Server) handleEvents(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeError(w, http.StatusInternalServerError, protocol.ErrInternal, "当前服务器不支持流式响应")
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Connection", "keep-alive")
	w.WriteHeader(http.StatusOK)

	ch := s.broker.subscribe()
	defer s.broker.unsubscribe(ch)

	heartbeat := time.NewTicker(20 * time.Second)
	defer heartbeat.Stop()

	_, _ = w.Write([]byte("event: ready\ndata: {}\n\n"))
	flusher.Flush()

	for {
		select {
		case <-r.Context().Done():
			return
		case <-heartbeat.C:
			_, _ = w.Write([]byte(": ping\n\n"))
			flusher.Flush()
		case payload := <-ch:
			_, _ = w.Write([]byte("event: progress\ndata: " + string(payload) + "\n\n"))
			flusher.Flush()
		}
	}
}
