import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * 同一份构建产物服务两处：
 *   - Wails 桌面端：Go 后端 go:embed 后由本地 HTTP 服务托管
 *   - Cloudflare Worker：Static Assets 托管（`[assets] directory = "../web/dist"`）
 *
 * 因此不能使用相对路径资源前缀，路由用 HashRouter 避免服务端 rewrite 依赖。
 */
export default defineConfig({
  plugins: [react()],
  base: "./",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
      "@tpmsc/protocol": path.resolve(__dirname, "../packages/protocol/src/index.ts"),
    },
  },
  server: {
    host: "0.0.0.0",
    allowedHosts: true,
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8787", changeOrigin: true },
      "/card": { target: "http://127.0.0.1:8787", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    // 某些 Windows 环境（IDE 索引 / 杀毒扫描）会短暂锁住 dist 里的文件，
    // 清空目录会失败并中断构建。保留旧 hash 文件没有副作用，
    // index.html 只引用本次产物；CI 是干净检出，不受影响。
    emptyOutDir: false,
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
  },
});
