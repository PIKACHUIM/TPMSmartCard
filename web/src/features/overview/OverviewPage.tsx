import { useEffect, useState, type ReactNode } from "react";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import { Cpu, Fingerprint, KeyRound, Usb } from "lucide-react";
import { api } from "@/lib/api";
import type { OverviewStat, SystemHealth } from "@/lib/types";
import type { AuditRow } from "@tpmsc/protocol";
import { Badge, Panel, SectionTitle, Spinner, StatusDot } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";

export function OverviewPage() {
  const [stats, setStats] = useState<OverviewStat[] | null>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [activity, setActivity] = useState<AuditRow[]>([]);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([api.stats(), api.health()])
      .then(([nextStats, nextHealth]) => {
        if (cancelled) return;
        setStats(nextStats);
        setHealth(nextHealth);
      })
      .catch((err) => console.error("overview load failed", err));

    void api
      .audit({ limit: 6 })
      .then((result) => {
        if (!cancelled) setActivity(result.rows.slice(0, 6));
      })
      .catch((err) => console.error("activity load failed", err));

    return () => {
      cancelled = true;
    };
  }, []);

  if (!stats || !health) return <Spinner label="正在汇总卡片与平台状态…" />;

  const capabilities = [
    { label: "创建卡片", enabled: health.capability.create_card },
    { label: "删除卡片", enabled: health.capability.delete_card },
    { label: "PIN 管理", enabled: health.capability.set_pin },
    { label: "TPM 保护", enabled: health.capability.tpm_backed },
    { label: "Secure Enclave", enabled: health.capability.secure_enclave },
    { label: "整卡备份", enabled: health.capability.backup },
    { label: "SSH Agent", enabled: health.capability.ssh },
    { label: "FIDO2", enabled: health.capability.fido },
  ];

  return (
    <div className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((stat, index) => (
          <Panel key={stat.label} className="animate-fade-rise p-4" >
            <div style={{ animationDelay: `${index * 70}ms` }}>
              <p className="label-caps">{stat.label}</p>
              <p className="mono-num mt-2 text-[30px] leading-none text-ink-0">{stat.value}</p>
              <p className="mt-2 text-[11.5px] text-ink-2">{stat.hint}</p>
              {stat.trend ? (
                <div className="mt-3 h-9">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={stat.trend.map((value, i) => ({ i, value }))}>
                      <defs>
                        <linearGradient id={`spark-${index}`} x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#D98324" stopOpacity={0.35} />
                          <stop offset="100%" stopColor="#D98324" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <Area
                        type="monotone"
                        dataKey="value"
                        stroke="#D98324"
                        strokeWidth={1.4}
                        fill={`url(#spark-${index})`}
                        isAnimationActive={false}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              ) : null}
            </div>
          </Panel>
        ))}
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
        <Panel>
          <SectionTitle title="平台健康" hint="唯一可信来源是设备侧的实测探针，不是型号推断" />
          <div className="grid gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-3">
            <HealthCell
              icon={<Cpu className="h-4 w-4" />}
              label="TPM / 安全隔区"
              value={health.secure_enclave.available ? "Secure Enclave" : health.tpm.version ? `TPM ${health.tpm.version}` : "不可用"}
              detail={health.secure_enclave.available ? health.secure_enclave.detail : health.tpm.detail}
              ok={health.tpm.present || health.secure_enclave.available}
            />
            <HealthCell
              icon={<Usb className="h-4 w-4" />}
              label="读卡器"
              value={health.reader.readers.length ? `${health.reader.readers.length} 个` : "未发现"}
              detail={health.reader.readers.join(" · ") || "请在本地控制台会话重试"}
              ok={health.reader.present}
            />
            <HealthCell
              icon={<Fingerprint className="h-4 w-4" />}
              label="本地后端"
              value={health.backend.version}
              detail={`运行 ${Math.floor(health.backend.uptime_seconds / 60)} 分钟 · ${health.platform}`}
              ok
            />
          </div>

          <div className="mt-5">
            <p className="label-caps mb-2">能力矩阵</p>
            <div className="flex flex-wrap gap-1.5">
              {capabilities.map((item) => (
                <span
                  key={item.label}
                  title={item.enabled ? "当前平台支持" : "当前平台不支持，界面已置灰"}
                  className={cn(
                    "rounded-full border px-2.5 py-1 font-mono text-[11px]",
                    item.enabled
                      ? "border-line text-ink-1"
                      : "border-line/50 text-ink-3 line-through decoration-ink-3/50",
                  )}
                >
                  {item.label}
                </span>
              ))}
            </div>
            <p className="mt-3 text-[11.5px] leading-relaxed text-ink-3">
              macOS 的 Secure Enclave 只支持 P-256 ECDSA，且私钥不可导出；RSA 请求会降级为钥匙串软件密钥并明确标注，
              备份也只包含证书与证书链。
            </p>
          </div>
        </Panel>

        <Panel>
          <SectionTitle title="最近操作" hint="审计只记录行为，不记录密钥与取件码" />
          <ol className="grid gap-0">
            {activity.length === 0 ? (
              <li className="py-6 text-center text-[12.5px] text-ink-2">暂无审计记录</li>
            ) : (
              activity.map((row) => (
                <li key={row.id} className="flex items-start gap-3 border-b border-line/40 py-2.5 last:border-none">
                  <StatusDot tone={row.result === "ok" ? "ok" : row.result === "deny" ? "warn" : "danger"} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-[12px] text-ink-1">
                      {row.actor} · {row.action}
                    </p>
                    <p className="truncate text-[11px] text-ink-3">
                      {new Date(row.created_at).toLocaleString()} {row.target ? `· ${row.target}` : ""}
                    </p>
                  </div>
                </li>
              ))
            )}
          </ol>
          <div className="mt-4 flex items-center gap-2 border-t border-line/60 pt-3">
            <Badge tone="info">
              <KeyRound className="h-3 w-3" /> 取件码默认 1 次
            </Badge>
            <Badge tone="ok">KV 仅存密文</Badge>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function HealthCell({
  icon,
  label,
  value,
  detail,
  ok,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
  ok: boolean;
}) {
  return (
    <div className="bg-graphite-1 px-4 py-3">
      <div className="flex items-center gap-2 text-ink-3">
        {icon}
        <span className="label-caps">{label}</span>
      </div>
      <p className={cn("mono-num mt-2 text-[15px]", ok ? "text-ink-0" : "text-danger")}>{value}</p>
      <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-ink-3">{detail}</p>
    </div>
  );
}
