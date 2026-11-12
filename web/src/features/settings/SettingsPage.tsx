import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Cloud, Info, MonitorCog, Moon, Sun, TerminalSquare } from "lucide-react";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { LANGUAGES, setLanguage, type LanguageCode } from "@/lib/i18n";
import type { SystemHealth } from "@/lib/types";
import { Badge, Button, Field, Panel, SectionTitle, Spinner } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const theme = useAppStore((state) => state.theme);
  const toggleTheme = useAppStore((state) => state.toggleTheme);
  const pushToast = useAppStore((state) => state.pushToast);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [autostart, setAutostart] = useState(true);
  const [sshAgent, setSshAgent] = useState(true);
  const [endpoint, setEndpoint] = useState("https://card.example.com");

  useEffect(() => {
    void api
      .health()
      .then(setHealth)
      .catch((err) => console.error("settings health failed", err));
  }, []);

  if (!health) return <Spinner label="正在读取本机配置…" />;

  const capabilityRows = [
    ["建卡 / 删卡", health.capability.create_card && health.capability.delete_card],
    ["PIN / PUK 管理", health.capability.set_pin],
    ["TPM 保护", health.capability.tpm_backed],
    ["Secure Enclave", health.capability.secure_enclave],
    ["整卡备份", health.capability.backup],
    ["SSH Agent", health.capability.ssh],
    ["FIDO2", health.capability.fido],
    ["私钥可导出", health.capability.exportable_key],
  ] as const;

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Panel>
        <SectionTitle title="外观" hint="深色为默认展示，浅色保留纸面质感而非反色" />
        <div className="grid grid-cols-2 gap-2">
          {[
            { key: "dark", label: "深色 · 石墨", icon: Moon },
            { key: "light", label: "浅色 · 纸面", icon: Sun },
          ].map((option) => {
            const Icon = option.icon;
            const active = theme === option.key;
            return (
              <button
                key={option.key}
                type="button"
                onClick={() => {
                  if (!active) toggleTheme();
                }}
                className={cn(
                  "flex items-center gap-2 rounded-control border px-3 py-3 text-left text-[12.5px] transition",
                  active ? "border-copper-400/60 bg-copper-400/10 text-ink-0" : "border-line text-ink-2 hover:border-line/80",
                )}
              >
                <Icon className="h-4 w-4" />
                {option.label}
              </button>
            );
          })}
        </div>

        <div className="mt-5 grid gap-4">
          <label className="grid gap-1.5">
            <span className="label-caps">{t("nav.settings")} · 语言</span>
            <select
              value={i18n.language}
              onChange={(event) => setLanguage(event.target.value as LanguageCode)}
              className="h-10 rounded-control border border-line bg-graphite-0 px-3 text-body text-ink-0 focus:border-copper-400 focus:outline-none"
            >
              {LANGUAGES.map((language) => (
                <option key={language.code} value={language.code}>
                  {language.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Panel>

      <Panel>
        <SectionTitle title="系统集成" hint="需要管理员权限的项会在保存时请求提权" />
        <div className="grid gap-2">
          <Toggle
            label="开机自启（常驻托盘）"
            hint="登录时以提权计划任务启动，失败回退到 HKCU\\...\\Run"
            checked={autostart}
            onChange={setAutostart}
            icon={<MonitorCog className="h-4 w-4" />}
          />
          <Toggle
            label="内置 SSH Agent"
            hint="用卡上私钥完成 SSH 登录，公钥可一键登记到 authorized_keys"
            checked={sshAgent}
            onChange={setSshAgent}
            icon={<TerminalSquare className="h-4 w-4" />}
          />
        </div>

        <div className="mt-4 grid gap-3">
          <Field
            label="云端下发地址"
            value={endpoint}
            onChange={(event) => setEndpoint(event.target.value)}
            hint="支持 /card/get/cert（传输密钥）与 /card/get/code（取件码）两种取回方式"
          />
          <Button
            variant="primary"
            size="sm"
            className="w-fit"
            icon={<Cloud className="h-3.5 w-3.5" />}
            onClick={() => pushToast({ kind: "ok", title: "已保存下发地址", detail: endpoint })}
          >
            保存
          </Button>
        </div>
      </Panel>

      <Panel>
        <SectionTitle title="平台能力" hint="由后端 Capability 接口上报，前端不硬编码平台判断" />
        <ul className="grid gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-2">
          {capabilityRows.map(([label, enabled]) => (
            <li key={label} className="flex items-center justify-between bg-graphite-1 px-3 py-2">
              <span className="text-[12px] text-ink-2">{label}</span>
              <Badge tone={enabled ? "ok" : "muted"}>{enabled ? "支持" : "不支持"}</Badge>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[11.5px] leading-relaxed text-ink-3">
          macOS 若检测不到 Secure Enclave（未签名构建或旧机型），会自动降级为钥匙串软件密钥，并在这里显示为不支持。
        </p>
      </Panel>

      <Panel>
        <SectionTitle title="关于" hint="版本与运行时信息" action={<Info className="h-4 w-4 text-ink-3" />} />
        <dl className="grid gap-2 text-[12.5px]">
          {[
            ["版本", health.backend.version],
            ["平台", health.platform],
            ["TPM", health.tpm.version ? `TPM ${health.tpm.version}` : "不可用"],
            ["Secure Enclave", health.secure_enclave.available ? "可用" : "不可用"],
            ["读卡器", health.reader.readers.join(" · ") || "未发现"],
          ].map(([label, value]) => (
            <div key={label} className="flex items-start justify-between gap-4 border-b border-line/40 pb-2 last:border-none">
              <dt className="text-ink-3">{label}</dt>
              <dd className="mono-num truncate text-right text-ink-1">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 border-t border-line/60 pt-3 font-mono text-[10.5px] leading-relaxed text-ink-3">
          Go 1.23 · Wails v2 · React 18 · Hono on Cloudflare Workers
          <br />
          协议：X25519 + AES-256-CBC（零 IV）· PBKDF2-SHA256 取件码
        </p>
      </Panel>
    </div>
  );
}

function Toggle({
  label,
  hint,
  checked,
  onChange,
  icon,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  icon: ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 rounded-control border border-line/70 px-3 py-3">
      <span className="mt-0.5 text-ink-3">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-[12.5px] text-ink-1">{label}</p>
        <p className="mt-0.5 text-[11px] leading-relaxed text-ink-3">{hint}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative mt-1 h-5 w-9 shrink-0 rounded-full border transition-colors",
          checked ? "border-copper-400/60 bg-copper-400/30" : "border-line bg-graphite-2",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-3.5 w-3.5 rounded-full transition-all duration-200 ease-precise",
            checked ? "left-[18px] bg-copper-300" : "left-0.5 bg-ink-3",
          )}
        />
      </button>
    </div>
  );
}
