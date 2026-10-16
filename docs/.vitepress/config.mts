import { defineConfig } from 'vitepress'

const REPO = 'https://github.com/PIKACHUIM/TPMSmartCard'

/**
 * 站点地址与 base 路径全部由环境变量注入，这样**同一份源码**既能部署在
 * GitHub Pages 的项目路径（https://<owner>.github.io/<repo>/），也能部署到自定义域名的根路径
 * （https://docs.example.com/）：
 *
 * | 变量 | 作用 | 默认 |
 * |---|---|---|
 * | `DOCS_BASE` | 站点 base（必须以 / 开头、以 / 结尾） | `/` |
 * | `DOCS_SITE_URL` | 站点绝对地址（sitemap / canonical / og） | `https://pikachuim.github.io/TPMSmartCard` |
 *
 * CI 中由 `.github/workflows/build-docs.yml` 自动推导并注入，本地 `npm run docs:dev` 无需设置。
 */
function normalizeBase(input: string | undefined): string {
  const value = (input || '').trim()
  if (!value || value === '/') return '/'
  return `/${value.replace(/^\/+|\/+$/g, '')}/`
}

const base = normalizeBase(process.env.DOCS_BASE)
const siteUrl = (
  process.env.DOCS_SITE_URL?.trim() || 'https://pikachuim.github.io/TPMSmartCard'
).replace(/\/+$/, '')

/**
 * 产物目录（相对 `docs/`）可用 `DOCS_OUT_DIR` 覆盖。
 * CI 里用它把"第二份站点"（base = /<repo>/ 的副本）先构建到临时目录，
 * 再拷进主产物的子目录，从而让 github.io 项目路径与自定义域名**各自独立可用**。
 */
const outDir = process.env.DOCS_OUT_DIR?.trim() || undefined

const docsNav = [
  { text: '项目介绍', link: '/guide/' },
  { text: '工作原理', link: '/guide/principles' },
  { text: '硬件与软件要求', link: '/guide/requirements' },
  { text: '安装方式', link: '/guide/install' }
]

const usageNav = [
  { text: '智能卡管理', link: '/guide/usage-cards' },
  { text: '证书与密钥管理', link: '/guide/usage-certs' },
  { text: 'SSH 登录', link: '/guide/ssh' },
  { text: '备份与还原', link: '/guide/backup' }
]

const engineeringNav = [
  { text: '架构说明', link: '/architecture' },
  { text: '开发与调试指南', link: '/dev-guide' },
  { text: '备份还原设计', link: '/design-backup-restore' },
  { text: '备份还原技术报告', link: '/report-backup-restore' },
  { text: '安全模型', link: '/security' },
  { text: '故障排查手册', link: '/troubleshooting' },
  { text: '开发过程记录', link: '/devlog-2026-10-14-backup-restore' }
]

export default defineConfig({
  lang: 'zh-CN',
  title: 'TPM 虚拟智能卡管理器',
  description:
    '在 Windows 上创建与管理 TPM 虚拟智能卡的图形化工具：建卡 / 证书 / 密钥 / 备份还原 / SSH 登录，私钥由 TPM 保护、始终不以明文导出。',
  base,
  outDir,
  head: [
    ['link', { rel: 'icon', type: 'image/png', href: `${base}images/favicon.png` }],
    ['link', { rel: 'canonical', href: `${siteUrl}/` }],
    ['meta', { name: 'theme-color', content: '#0078d6' }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:title', content: 'TPM 虚拟智能卡管理器' }],
    [
      'meta',
      {
        property: 'og:description',
        content: '在 Windows 上用 TPM 打造一张私钥不可导出的智能卡：建卡、证书、备份还原全流程图形化工具。'
      }
    ],
    ['meta', { property: 'og:image', content: `${siteUrl}/images/tpm-smartcard-manager.png` }],
    ['meta', { name: 'referrer', content: 'no-referrer-when-downgrade' }]
  ],
  sitemap: { hostname: siteUrl },
  lastUpdated: true,
  cleanUrls: false,
  markdown: {
    lineNumbers: false,
    theme: { light: 'github-light', dark: 'github-dark' }
  },
  themeConfig: {
    siteTitle: 'TPM 虚拟智能卡管理器',
    nav: [
      { text: '首页', link: '/' },
      {
        text: '使用指南',
        items: [...docsNav, ...usageNav]
      },
      {
        text: '工程文档',
        items: engineeringNav
      },
      { text: '常见问题', link: '/guide/faq' },
      { text: '文档站部署', link: '/guide/deploy-docs' },
      { text: 'GitHub', link: REPO }
    ],
    sidebar: {
      '/guide/': [
        {
          text: '开始使用',
          items: [
            { text: '项目介绍', link: '/guide/' },
            { text: '工作原理', link: '/guide/principles' },
            { text: '硬件与软件要求', link: '/guide/requirements' },
            { text: '安装方式', link: '/guide/install' }
          ]
        },
        {
          text: '使用手册',
          items: [
            { text: '智能卡管理', link: '/guide/usage-cards' },
            { text: '证书与密钥管理', link: '/guide/usage-certs' },
            { text: 'SSH2 登录', link: '/guide/ssh' },
            { text: '备份与还原', link: '/guide/backup' }
          ]
        },
        {
          text: '进阶与工程',
          items: [
            { text: '常见问题（FAQ）', link: '/guide/faq' },
            { text: '开发方式', link: '/guide/development' },
            { text: '文档站部署', link: '/guide/deploy-docs' },
            { text: '工程文档索引', link: '/README' }
          ]
        },
        {
          text: '深入阅读',
          items: engineeringNav
        }
      ],
      '/': [
        {
          text: '工程文档',
          items: [
            { text: '工程文档索引', link: '/README' },
            ...engineeringNav
          ]
        },
        {
          text: '面向使用者的指南',
          items: [
            { text: '项目介绍', link: '/guide/' },
            { text: '工作原理', link: '/guide/principles' },
            { text: '硬件与软件要求', link: '/guide/requirements' },
            { text: '安装方式', link: '/guide/install' },
            { text: '智能卡管理', link: '/guide/usage-cards' },
            { text: '证书与密钥管理', link: '/guide/usage-certs' },
            { text: '备份与还原', link: '/guide/backup' },
            { text: '常见问题（FAQ）', link: '/guide/faq' },
            { text: '开发方式', link: '/guide/development' },
            { text: '文档站部署', link: '/guide/deploy-docs' }
          ]
        }
      ]
    },
    outline: { level: [2, 3], label: '本页目录' },
    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
          modal: {
            displayDetails: '显示详情',
            resetButtonTitle: '清除查询',
            backButtonTitle: '返回',
            noResultsText: '没有找到相关结果',
            footer: {
              selectText: '选择',
              selectKeyAriaLabel: '回车',
              navigateText: '切换',
              navigateUpKeyAriaLabel: '上箭头',
              navigateDownKeyAriaLabel: '下箭头',
              closeText: '关闭',
              closeKeyAriaLabel: 'Esc'
            }
          }
        }
      }
    },
    editLink: {
      pattern: 'https://github.com/PIKACHUIM/TPMSmartCard/edit/main/docs/:path',
      text: '在 GitHub 上编辑此页'
    },
    lastUpdated: {
      text: '最后更新',
      formatOptions: { dateStyle: 'medium', timeStyle: 'short' }
    },
    docFooter: { prev: '上一篇', next: '下一篇' },
    returnToTopLabel: '回到顶部',
    sidebarMenuLabel: '目录',
    darkModeSwitchLabel: '外观',
    lightModeSwitchTitle: '切换到浅色模式',
    darkModeSwitchTitle: '切换到深色模式',
    externalLinkIcon: true,
    footer: {
      message:
        '本项目基于 <a href="https://github.com/PIKACHUIM/TPMSmartCard/blob/main/LICENSE">GPL-3.0</a> 许可证开源 · 文档遵循同一许可',
      copyright:
        'Copyright © PIKACHUIM · <a href="https://github.com/PIKACHUIM/TPMSmartCard">github.com/PIKACHUIM/TPMSmartCard</a>'
    },
    socialLinks: [{ icon: 'github', link: REPO }],
    notFound: {
      title: '页面不存在',
      quote: '你要找的文档可能已经改过名字，用搜索找一下？',
      linkText: '回到首页'
    }
  }
})
