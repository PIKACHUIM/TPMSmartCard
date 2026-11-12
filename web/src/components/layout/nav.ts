import {
  Activity,
  ArchiveRestore,
  CreditCard,
  FileKey2,
  KeySquare,
  ScrollText,
  ShieldCheck,
  Settings2,
  Users2,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  labelKey: string;
  fallback: string;
  icon: LucideIcon;
  permission?: string;
  group: "device" | "console";
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", labelKey: "nav.overview", fallback: "总览", icon: Activity, group: "device" },
  { to: "/cards", labelKey: "nav.cards", fallback: "卡片", icon: CreditCard, group: "device" },
  { to: "/certs", labelKey: "nav.certs", fallback: "证书与密钥", icon: FileKey2, group: "device" },
  { to: "/backup", labelKey: "nav.backup", fallback: "备份还原", icon: ArchiveRestore, group: "device" },
  { to: "/settings", labelKey: "nav.settings", fallback: "设置", icon: Settings2, group: "device" },
  {
    to: "/admin/records",
    labelKey: "admin.records",
    fallback: "下发记录",
    icon: ShieldCheck,
    permission: "record:read",
    group: "console",
  },
  {
    to: "/admin/users",
    labelKey: "admin.users",
    fallback: "用户",
    icon: Users2,
    permission: "user:read",
    group: "console",
  },
  {
    to: "/admin/roles",
    labelKey: "admin.roles",
    fallback: "角色",
    icon: KeySquare,
    permission: "user:read",
    group: "console",
  },
  {
    to: "/admin/audit",
    labelKey: "admin.audit",
    fallback: "审计日志",
    icon: ScrollText,
    permission: "audit:read",
    group: "console",
  },
];

export const PAGE_TITLES: Record<string, { title: string; hint: string }> = {
  "/": { title: "总览", hint: "卡片、证书与平台健康状态" },
  "/cards": { title: "卡片", hint: "创建、删除与 PIN 管理" },
  "/certs": { title: "证书与密钥", hint: "证书链、密钥用法与 CSR" },
  "/backup": { title: "备份还原", hint: "整卡打包、还原诊断与风险提示" },
  "/settings": { title: "设置", hint: "外观、语言、自启与代理" },
  "/admin/records": { title: "下发记录", hint: "取件码与传输密钥的存续状态" },
  "/admin/users": { title: "用户", hint: "账号、状态与角色分配" },
  "/admin/roles": { title: "角色与权限", hint: "细粒度权限码与自定义角色" },
  "/admin/audit": { title: "审计日志", hint: "谁在何时对什么做了什么" },
};
