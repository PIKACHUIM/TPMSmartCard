package main

import (
	"html"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
)

// assetHandler 返回 Wails AssetServer 使用的处理器。
//
// 请求全部反向代理到内嵌后端：前端静态资源、/api/*、/card/* 走同一个源，
// 因此浏览器与桌面端的同源策略、Cookie、SSE 行为完全一致。
type proxyHandler struct {
	target atomic.Pointer[url.URL]

	mu    sync.RWMutex
	proxy *httputil.ReverseProxy
}

func newProxyHandler() *proxyHandler {
	return &proxyHandler{}
}

func (p *proxyHandler) setTarget(target *url.URL) {
	proxy := httputil.NewSingleHostReverseProxy(target)
	originalDirector := proxy.Director
	proxy.Director = func(request *http.Request) {
		originalDirector(request)
		// 去掉 WebView 自己的 Origin：后端只接受同源写入，
		// wails:// 与 http://wails.localhost 的 host 比较没有意义。
		request.Header.Del("Origin")
		request.Header.Del("Referer")
	}
	proxy.ErrorHandler = func(writer http.ResponseWriter, _ *http.Request, err error) {
		serveWaitingPage(writer, err)
	}

	p.target.Store(target)
	p.mu.Lock()
	p.proxy = proxy
	p.mu.Unlock()
}

func (p *proxyHandler) clearTarget() {
	p.mu.Lock()
	p.proxy = nil
	p.mu.Unlock()
}

func (p *proxyHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	p.mu.RLock()
	proxy := p.proxy
	p.mu.RUnlock()

	if proxy == nil {
		serveWaitingPage(w, nil)
		return
	}
	proxy.ServeHTTP(w, r)
}

const waitingPagePlaceholder = "{{DETAIL}}"

// serveWaitingPage 输出「本地服务启动中」的等待页。
func serveWaitingPage(w http.ResponseWriter, cause error) {
	detail := "正在启动本地服务，请稍候…"
	if cause != nil {
		detail = "连接本地服务失败：" + cause.Error()
	}

	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusOK)
	_, _ = io.WriteString(w, strings.Replace(waitingPageHTML, waitingPagePlaceholder, html.EscapeString(detail), 1))
}

const waitingPageHTML = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>TPMSmartCard · 启动中</title>
<style>
  html, body { height: 100%; margin: 0; background: #0E1116; color: #E6EAEF;
    font-family: "Source Sans Pro", "PingFang SC", "Microsoft YaHei", sans-serif; }
  .wrap { height: 100%; display: flex; flex-direction: column; align-items: center;
    justify-content: center; gap: 18px; }
  .mark { width: 44px; height: 44px; border-radius: 10px; border: 1px solid rgba(217,131,36,.5);
    background: rgba(217,131,36,.1); display: grid; place-items: center; }
  .mark::after { content: ""; width: 14px; height: 14px; border: 2px solid #D98324;
    border-top-color: transparent; border-radius: 50%; animation: spin 900ms linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  h1 { font-size: 15px; font-weight: 500; letter-spacing: .04em; margin: 0; }
  p { margin: 0; font-size: 12px; color: #8B98A6; font-family: ui-monospace, Consolas, monospace; }
  @media (prefers-reduced-motion: reduce) { .mark::after { animation: none; } }
</style>
</head>
<body>
  <div class="wrap">
    <div class="mark"></div>
    <h1>TPM 虚拟智能卡管理器</h1>
    <p>{{DETAIL}}</p>
  </div>
  <script>setTimeout(function(){ location.reload(); }, 1200);</script>
</body>
</html>`
