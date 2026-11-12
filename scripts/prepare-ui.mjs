#!/usr/bin/env node
/**
 * 把 web/dist 同步到 core/ui/dist，供 Go 的 go:embed 使用。
 *
 * 之所以放在 scripts/ 而不是 rsync：
 *   - Windows CI（windows-latest）没有 rsync；
 *   - 需要排除 .map 与旧 hash 文件，避免把上一次构建的残留打进二进制。
 */
import { cp, mkdir, readdir, rm, stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const root = path.resolve(import.meta.dirname, "..");
const source = path.join(root, "web", "dist");
const target = path.join(root, "core", "ui", "dist");

if (!existsSync(source)) {
  console.error("web/dist 不存在，请先运行 `npm run build -w @tpmsc/web`");
  process.exit(1);
}

await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });

async function copyDir(from, to) {
  const entries = await readdir(from, { withFileTypes: true });
  for (const entry of entries) {
    const src = path.join(from, entry.name);
    const dest = path.join(to, entry.name);
    if (entry.isDirectory()) {
      await mkdir(dest, { recursive: true });
      await copyDir(src, dest);
      continue;
    }
    if (entry.name.endsWith(".map")) continue;
    await cp(src, dest);
  }
}

await copyDir(source, target);
const info = await stat(target);
console.log(`已同步前端产物到 ${path.relative(root, target)} (${info.isDirectory() ? "ok" : "?"})`);
