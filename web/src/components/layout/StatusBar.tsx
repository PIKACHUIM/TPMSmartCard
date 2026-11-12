import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Cpu, Usb } from "lucide-react";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import type { SystemHealth } from "@/lib/types";
import { StatusDot } from "@/components/ui/primitives";

/** 底部常驻状态栏：TPM / SE、读卡器、后端连接与版本 */
export function StatusBar() {
  const { t } = useTranslation();
  const online = useAppStore((state) => state.online);
  const demo = useAppStore((state) => state.demo);
  const [health, setHealth] = useState<SystemHealth | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api
      .health()
      .then((value) => {
        if (!cancelled) setHealth(value);
      })
      .catch((err) => console.error("health probe failed", err));
    return () => {
      cancelled = true;
    };
  }, []);

  const tpmLabel = health?.secure_enclave.available
    ? "Secure Enclave"
    : health?.tpm.present
      ? `TPM ${health.tpm.version ?? ""}`.trim()
      : "TPM 不可用";

  const readerLabel = health?.reader.readers.length
    ? `${health.reader.readers.length} 个读卡器`
    : "无读卡器";

  return (
    <footer className="fixed bottom-0 left-[72px] right-0 z-20 flex h-7 items-center gap-4 border-t border-line/70 bg-graphite-0/92 px-4 font-mono text-[11px] text-ink-3 backdrop-blur">
      <span className="flex items-center gap-1.5">
        <Cpu className="h-3 w-3" />
        {tpmLabel}
      </span>
      <span className="flex items-center gap-1.5">
        <Usb className="h-3 w-3" />
        {readerLabel}
      </span>
      <span className="hidden md:inline">{health?.platform ?? "—"}</span>
      <span className="ml-auto flex items-center gap-1.5">
        <StatusDot tone={online ? "ok" : demo ? "warn" : "danger"} pulse={online} />
        {online ? t("status.online") : demo ? t("status.demo") : t("status.offline")}
      </span>
      <span>v{health?.backend.version ?? "2.0.0"}</span>
    </footer>
  );
}
