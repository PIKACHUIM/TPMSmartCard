# 文档站部署（GitHub Pages + 自定义域名）

本站用 **VitePress** 构建、用 **GitHub Actions** 发布到 **GitHub Pages**，
并且**同时支持两种访问地址**：

| 地址 | 站点 base | 说明 |
|---|---|---|
| `https://<owner>.github.io/<repo>/` | `/<repo>/` | GitHub Pages 默认地址（项目站点） |
| `https://<你的域名>/` | `/` | 自定义域名（可选，跑在根路径） |

难点在于 **base 不能写死**：静态站点的资源路径在构建时就固定了，base 写错就会"页面能打开但没样式"。
本项目的做法是：

1. **base 做成构建期参数**（环境变量 `DOCS_BASE`），由工作流按"有没有自定义域名"自动推导；
2. 当站点跑在自定义域名根路径（base = `/`）时，**再构建一份 `base = /<repo>/` 的副本**放进
   产物的 `<repo>/` 子目录 —— 这样一个产物里有两套各自自洽的页面，
   两个地址都能**独立完整地渲染**，不依赖 GitHub 的任何重定向行为。

## 1. 目录结构

```
docs/
├─ .vitepress/
│  ├─ config.mts          站点配置（导航、侧边栏、搜索、base/site url 注入）
│  └─ theme/
│     ├─ index.ts         主题入口
│     └─ custom.css       自定义样式
├─ public/                静态资源（原样拷贝到产物根目录）
│  ├─ images/             favicon、界面截图；CNAME 由 CI 在需要时生成
├─ index.md               首页（hero + 功能卡片）
├─ guide/                 面向使用者的指南（介绍、原理、要求、安装、使用、备份、开发…）
├─ architecture.md        工程文档（原有）… 
└─ README.md              工程文档索引
```

产物：`docs/.vitepress/dist/`。使用自定义域名时，产物结构会是这样（两套页面并存）：

```
docs/.vitepress/dist/
├─ index.html assets/ …   ← base = /        自定义域名根路径用
├─ CNAME                 ← 自定义域名（CI 生成）
├─ guide/… .html         ← 上述站点的内页
└─ TPMSmartCard/         ← base = /TPMSmartCard/ 的副本（github.io 项目路径用）
   ├─ index.html assets/ …
   └─ guide/… .html
```

## 2. 本地开发与预览

```bash
cd docs
npm install          # 首次
npm run docs:dev     # 本地开发服务器（默认 http://localhost:5173）
npm run docs:build   # 构建到 .vitepress/dist
npm run docs:preview # 本地预览构建产物
```

想验证"部署在子路径"的效果，构建前设置 base：

```bash
# Windows PowerShell
$env:DOCS_BASE = '/TPMSmartCard/'
$env:DOCS_SITE_URL = 'https://pikachuim.github.io/TPMSmartCard'
npm run docs:build
```

| 环境变量 | 作用 | 默认 |
|---|---|---|
| `DOCS_BASE` | 站点 base，必须以 `/` 开头、以 `/` 结尾 | `/` |
| `DOCS_SITE_URL` | 站点绝对地址，用于 `canonical`、`sitemap.xml`、`og:image` | `https://pikachuim.github.io/TPMSmartCard` |
| `DOCS_OUT_DIR` | 产物目录（相对 `docs/`），CI 用它把副本构建到临时目录 | `.vitepress/dist` |

## 3. 怎么写新页面

1. 在 `docs/guide/` 下新建 `xxx.md`，用标准 Markdown / VitePress 语法
   （`::: tip / warning / danger` 容器、代码块、表格都可以直接用）；
2. 到 `docs/.vitepress/config.mts` 的 `sidebar` 与 `nav` 里登记链接
   （文件名 `usage-cards.md` 对应链接 `/guide/usage-cards`，**不要写 `.md` 后缀**，
   工作流与本地构建都会做死链检查）；
3. 图片放到 `docs/public/images/`，用绝对路径引用：`![说明](/images/xxx.png)`；
4. 提交到 `main` 分支，若改动落在 `docs/**` 或工作流文件上，CI 会自动重新构建并发布。

## 4. 工作流做了什么

文件：`.github/workflows/build-docs.yml`

| 步骤 | 说明 |
|---|---|
| Checkout（`fetch-depth: 0`） | 取完整 git 历史，让页脚"最后更新"时间可读 |
| `actions/configure-pages` | 读取仓库 Pages 配置，输出 `base_path` / `base_url` |
| **Resolve site config** | 推导 `base`、站点绝对地址、是否要出子路径副本，必要时写入 `docs/public/CNAME`；结果写入 Job Summary |
| `npm ci` + `npm run docs:build` | 主构建，注入 `DOCS_BASE` / `DOCS_SITE_URL` |
| **Build nested copy** | 仅当主构建 base 为 `/`：用 `DOCS_OUT_DIR=.vitepress/dist-nested` 再构建一份 `base=/<repo>/` 的副本，去掉重复的 `sitemap.xml` 后拷进 `dist/<repo>/` |
| `actions/upload-pages-artifact` | 上传 `docs/.vitepress/dist`（含两套页面） |
| `actions/deploy-pages` | 发布到 GitHub Pages（`github-pages` environment） |

base 的推导优先级：

| 优先级 | 来源 | 得到的 base |
|---|---|---|
| 1 | `workflow_dispatch` 输入 `base` | 手动指定（调试用） |
| 2 | **站点是否跑在自定义域名下**：`configure-pages` 的 `base_url` 主机名不是 `*.github.io` | `/` |
| 3 | 有自定义域名（输入 `custom_domain` 或仓库变量 `DOCS_CUSTOM_DOMAIN`） | `/` |
| 4 | `configure-pages` 的 `base_path` | 通常是 `/TPMSmartCard` |
| 5 | 兜底 | `/<仓库名>/` |

::: danger 第 2 条不能省（曾经踩过的坑）
只要在 **Settings → Pages** 里填了 Custom domain，站点就发布在**自定义域名的根路径**，
但 `configure-pages` 仍然可能给出 `base_path=/TPMSmartCard`。如果照着 `base_path` 构建，
就会出现"首页能打开、但所有导航链接与 CSS/JS 资源 404"的症状
（`https://域名/TPMSmartCard/assets/style.*.css` 404、`https://域名/TPMSmartCard/` 404）。
因此必须先看 `base_url` 的主机名：**不是 `*.github.io` 就按根路径（`/`）构建**。
:::

副本（`nested_base`）只在「主构建 base = `/` 且仓库名不是 `<owner>.github.io`」时生成，
其余情况不需要 —— 那时主构建本身就在 github.io 项目路径上。

## 5. 一次性启用 Pages

1. 仓库 **Settings → Pages**；
2. **Source** 选 **GitHub Actions**（不要选 "Deploy from a branch"）；
3. 到 **Actions** 手动跑一次 **Build & Deploy Docs (VitePress)**（或往 `docs/` 推一次提交）；
4. 跑完后 `https://<owner>.github.io/<repo>/` 即可访问。

## 6. 配置自定义域名（两种方式）

### 方式 A：仓库变量（推荐，自动写入 CNAME）

1. **Settings → Secrets and variables → Actions → Variables → New repository variable**
2. 名称 `DOCS_CUSTOM_DOMAIN`，值填域名（不带协议，如 `tpm-docs.example.com`）；
3. 重新跑一次文档工作流：它会用 `base = /` 构建，并在产物里写入 `docs/public/CNAME`，
   站点地址也会用于 `sitemap` / `canonical`。

### 方式 B：Settings → Pages → Custom domain

在 **Settings → Pages → Custom domain** 里填域名并保存。平台会自行维护 `CNAME`。
此方式下工作流从 `configure-pages` 的输出里识别"站点在根路径"，因此仍然会按 `base = /` 构建
（`base_path` 为空时用 `base_url` 的路径部分兜底，见 §4）。

| 对比 | 方式 A（仓库变量） | 方式 B（Settings 填写） |
|---|---|---|
| CNAME 来源 | 构建产物里的 `CNAME` | 平台自动维护 |
| base 推导 | 明确按 `/` 构建 | 从 `configure-pages` 输出推导，同样得到 `/` |
| 适合 | 想用代码/配置固化域名、审计清晰 | 只想点几下 |

### DNS 设置

| 你的域名形式 | 记录类型 | 值 |
|---|---|---|
| 子域名（`docs.example.com`） | `CNAME` | `<owner>.github.io` |
| 顶级域名（`example.com`） | `A` | `185.199.108.153` / `185.199.109.153` / `185.199.110.153` / `185.199.111.153` |
| 顶级域名（IPv6） | `AAAA` | `2606:50c0:8000::153` / `2606:50c0:8001::153` / `2606:50c0:8002::153` / `2606:50c0:8003::153` |

> 上述 A / AAAA 值是 GitHub Pages 的通用地址，**以
> [GitHub 官方文档](https://docs.github.com/pages/configuring-a-custom-domain-for-your-github-pages-site) 为准**；
> 若使用 Cloudflare 等 CDN，代理状态请先设为 DNS only，等证书签发完成再考虑开启代理。

最后在 **Settings → Pages** 勾选 **Enforce HTTPS**。
如果域名是通过方式 A 写入 CNAME 的，第一次访问可能需要等几分钟到几十分钟让平台签发证书。

## 7. "同时支持两个域名"到底怎么实现

因为静态站点的资源路径在构建期就写死了，**一个产物只能匹配一个 base**。所以本工作流的做法是
**一次部署、两套自洽页面**：

| 情况 | 产物 | 效果 |
|---|---|---|
| 配了自定义域名 | 主构建 `base = /`；另在 `dist/<repo>/` 放一份 `base = /<repo>/` 的副本 | `https://你的域名/` 与 `https://<owner>.github.io/<repo>/` **都能独立完整地渲染**，不依赖任何重定向 |
| 没配自定义域名 | 只有一个 `base = /<repo>/` 的构建 | github.io 项目路径可用 |
| 用户/组织站点（仓库名为 `<owner>.github.io`） | 跳过副本 | 该仓库本身就在 github.io 根路径 |

几点说明：

* 副本里的 `sitemap.xml` 会在拷贝前删除，且副本的 `canonical` 指向**主域名** ——
  搜索引擎只会把主域名当正式地址，避免重复内容；
* 代价是构建时间与产物体积大约翻倍（本项目约 1 分钟 / 十几 MB），对文档站可以接受；
* 想只留一套：把仓库变量 `DOCS_CUSTOM_DOMAIN` 清掉、并确保 Settings → Pages 里没有自定义域名，
  工作流就会只出 `base = /<repo>/` 的一份；
* 想本地复现完整产物，按上面的顺序跑两次构建，并把副本拷进 `dist/<repo>/`
  （CI 里的命令见 `.github/workflows/build-docs.yml` 的 "Build nested copy" 步骤）。

## 8. 发布后自检清单

| 检查 | 期望 |
|---|---|
| 首页 | 标题、hero 截图、功能卡片正常，**样式与字体加载**（没有裸 HTML 的样子） |
| 任意内页刷新 | 直接访问 `.../guide/usage-cards.html` 能正常打开（不是 404） |
| 导航与侧边栏 | 每个链接都能打开，浏览器控制台没有 404 资源 |
| 搜索 | 右上角搜索能搜到中文关键词（如"备份"） |
| 页脚 | "最后更新"有日期；"在 GitHub 上编辑此页"能打开对应源码 |
| `sitemap.xml` | 只在根路径存在一份（副本里的会被删掉），里面是**自定义域名**（若配置了） |
| 自定义域名 | 首页可访问且浏览器显示 HTTPS 锁；`http://` 自动跳 `https://` |
| **github.io 子路径副本** | 配了自定义域名时，`https://<owner>.github.io/<repo>/` 也要**样式正常**（说明 `<repo>/` 副本已生成） |

## 9. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 工作流报 `Get Pages site failed` / `Pages site not found` | 仓库还没启用 Pages（或 Source 不是 GitHub Actions） | 按本文 §5 启用后再跑 |
| 全站 404，但工作流成功 | Pages 的 Source 选成了 "Deploy from a branch"，与产物式部署冲突 | 改成 **GitHub Actions** |
| 页面能打开但**没有任何样式**（裸 HTML） | base 与实际访问路径不匹配 | 修正 base（自定义域名 → `/`；只走 github.io → `/<repo>/`），或用 `base` 输入覆盖；若只是 github.io 子路径没样式，检查产物里有没有 `<repo>/` 副本（§4 的 "Build nested copy" 步骤是否跳过/失败） |
| 内页链接 404 | Markdown 里写了死链；VitePress 默认会让构建**失败** | 按构建日志修正链接（页面链接不带 `.md` 后缀也可以，但推荐统一风格） |
| 自定义域名访问证书报错 | DNS 未生效 / 证书还在签发 / CDN 代理模式干扰 | 确认 DNS 记录、等证书签发、CDN 先关闭代理 |
| 页脚没有"最后更新" | Checkout 没有取完整历史 | 确认 `fetch-depth: 0` 未被改动 |
| 搜索没有结果 | 构建产物缺本地搜索索引 | 确认构建无警告、`search.provider` 仍为 `local` |

回到 [开发方式](/guide/development) 了解如何改代码，或看 [工程文档索引](/README)。
