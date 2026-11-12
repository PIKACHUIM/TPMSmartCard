import { useEffect, useMemo, useState } from "react";
import { Download, FileBadge, FileKey2, Upload } from "lucide-react";
import { api } from "@/lib/api";
import type { CardInfo, CertificateInfo } from "@/lib/types";
import { useAppStore } from "@/lib/store";
import { Badge, Button, EmptyState, Panel, SectionTitle, Spinner } from "@/components/ui/primitives";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { CertImportModal } from "./CertImportModal";

function downloadPEM(name: string, pem: string) {
  const blob = new Blob([pem], { type: "application/x-pem-file" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

function expiryTone(notAfter: string): { tone: "ok" | "warn" | "danger"; text: string } {
  const days = Math.ceil((Date.parse(notAfter) - Date.now()) / 86_400_000);
  if (days < 0) return { tone: "danger", text: `已过期 ${Math.abs(days)} 天` };
  if (days < 90) return { tone: "warn", text: `${days} 天后到期` };
  return { tone: "ok", text: `${Math.floor(days / 365)} 年后到期` };
}

export function CertsPage() {
  const [certs, setCerts] = useState<CertificateInfo[] | null>(null);
  const [cards, setCards] = useState<CardInfo[]>([]);
  const [cardFilter, setCardFilter] = useState<string>("");
  const [selected, setSelected] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const pushToast = useAppStore((state) => state.pushToast);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([api.certificates(), api.cards()])
      .then(([result, cardResult]) => {
        if (cancelled) return;
        setCerts(result.certificates);
        setCards(cardResult.cards);
        setSelected((current) => current ?? result.certificates[0]?.id ?? null);
      })
      .catch((err) => console.error("certificates load failed", err));
    return () => {
      cancelled = true;
    };
  }, []);

  const reload = () => {
    api
      .certificates()
      .then((result) => {
        setCerts(result.certificates);
        setSelected((current) => current ?? result.certificates[0]?.id ?? null);
      })
      .catch((err: Error) => {
        console.error("certificates reload failed", err);
        pushToast({ kind: "err", title: "刷新证书列表失败", detail: err.message });
      });
  };

  const exportCurrent = () => {
    if (!current) return;
    api
      .exportCertificate(current.card_id, current.id)
      .then((pem) => {
        downloadPEM(`${current.serial || current.id}.pem`, pem);
        pushToast({ kind: "ok", title: "已导出证书", detail: "只包含公钥证书，私钥始终留在卡片内" });
      })
      .catch((err: Error) => pushToast({ kind: "err", title: "导出失败", detail: err.message }));
  };

  const rows = useMemo(
    () => (certs ?? []).filter((cert) => !cardFilter || cert.card_id === cardFilter),
    [certs, cardFilter],
  );

  if (!certs) return <Spinner label="正在读取证书链与密钥用法…" />;

  const current = rows.find((cert) => cert.id === selected) ?? rows[0] ?? null;

  const columns: Column<CertificateInfo>[] = [
    {
      key: "subject",
      header: "主体",
      render: (row) => (
        <div className="min-w-0">
          <p className="truncate text-[13px] text-ink-0">{row.subject}</p>
          <p className="truncate font-mono text-[10.5px] text-ink-3">{row.issuer}</p>
        </div>
      ),
    },
    {
      key: "serial",
      header: "序列号",
      width: "150px",
      render: (row) => <span className="mono-num text-[11.5px] text-ink-2">{row.serial}</span>,
    },
    { key: "algo", header: "算法", width: "150px", render: (row) => <span className="text-[12px]">{row.key_algorithm}</span> },
    {
      key: "expiry",
      header: "有效期",
      width: "130px",
      render: (row) => {
        const info = expiryTone(row.not_after);
        return <Badge tone={info.tone}>{info.text}</Badge>;
      },
    },
    {
      key: "key",
      header: "私钥",
      width: "90px",
      align: "center",
      render: (row) => (row.has_private_key ? <Badge tone="ok">在卡上</Badge> : <Badge tone="muted">仅证书</Badge>),
    },
  ];

  return (
    <div className="grid gap-5 xl:grid-cols-[1.25fr_0.75fr]">
      <Panel className="p-0">
        <div className="flex flex-wrap items-center gap-3 border-b border-line/70 px-4 py-3">
          <div className="mr-auto">
            <p className="label-caps">证书</p>
            <p className="mono-num text-[13px] text-ink-1">{rows.length} 张</p>
          </div>
          <label className="sr-only" htmlFor="card-filter">
            按卡片过滤
          </label>
          <select
            id="card-filter"
            value={cardFilter}
            onChange={(event) => setCardFilter(event.target.value)}
            className="h-8 rounded-control border border-line bg-graphite-0 px-2 text-[12px] text-ink-1 focus:border-copper-400 focus:outline-none"
          >
            <option value="">全部卡片</option>
            {cards.map((card) => (
              <option key={card.id} value={card.id}>
                {card.name}
              </option>
            ))}
          </select>
          <Button size="sm" icon={<Upload className="h-3.5 w-3.5" />} onClick={() => setImportOpen(true)}>
            导入
          </Button>
        </div>

        <div className="p-2">
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(row) => row.id}
            selectedKey={current?.id ?? null}
            onRowClick={(row) => setSelected(row.id)}
            caption="证书列表"
            emptyTitle="该卡片还没有证书"
            emptyHint="可以导入现有 PFX，或在本地生成密钥后提交 CSR 由 CA 签发。"
          />
        </div>
      </Panel>

      {current ? (
        <div className="grid content-start gap-5">
          <Panel>
            <SectionTitle
              title="证书详情"
              hint={current.key_algorithm}
              action={<FileBadge className="h-4 w-4 text-copper-300" />}
            />

            <dl className="grid gap-3 text-[12.5px]">
              <div>
                <dt className="label-caps">主体</dt>
                <dd className="mt-1 break-words text-ink-1">{current.subject}</dd>
              </div>
              <div>
                <dt className="label-caps">签发者</dt>
                <dd className="mt-1 break-words text-ink-1">{current.issuer}</dd>
              </div>
              <div>
                <dt className="label-caps">SHA-1 指纹</dt>
                <dd className="mono-num mt-1 break-all text-[11px] text-ink-2">{current.fingerprint}</dd>
              </div>
              <div>
                <dt className="label-caps">密钥用法</dt>
                <dd className="mt-1 flex flex-wrap gap-1.5">
                  {current.key_usage.map((usage) => (
                    <span key={usage} className="rounded border border-line px-2 py-0.5 font-mono text-[10.5px] text-ink-2">
                      {usage}
                    </span>
                  ))}
                </dd>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <dt className="label-caps">生效</dt>
                  <dd className="mono-num mt-1 text-[11.5px]">{new Date(current.not_before).toLocaleDateString()}</dd>
                </div>
                <div>
                  <dt className="label-caps">到期</dt>
                  <dd className="mono-num mt-1 text-[11.5px]">{new Date(current.not_after).toLocaleDateString()}</dd>
                </div>
              </div>
            </dl>

            <div className="mt-5 flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled
                title="需要 PKCS#11 引擎在卡内生成密钥，当前平台尚未接入"
                icon={<FileKey2 className="h-3.5 w-3.5" />}
              >
                生成 CSR
              </Button>
              <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={exportCurrent}>
                导出
              </Button>
            </div>
            <p className="mt-2 text-[11px] leading-relaxed text-ink-3">
              CSR 需要在卡内生成密钥（PKCS#11 / Secure Enclave），当前构建只读；导出仅包含公钥证书与链。
            </p>
          </Panel>

          <Panel>
            <SectionTitle title="证书链" hint="按签发关系自上而下" />
            <ol className="grid gap-0">
              {[
                { label: "根 CA", value: "Example Root CA 2026", tone: "muted" as const },
                { label: "中级 CA", value: "Example Issuing CA", tone: "info" as const },
                { label: "终端实体", value: current.subject, tone: "ok" as const },
              ].map((item) => (
                <li key={item.label} className="flex items-start gap-3 border-b border-line/40 py-2.5 last:border-none">
                  <Badge tone={item.tone}>{item.label}</Badge>
                  <span className="min-w-0 flex-1 break-words font-mono text-[11.5px] text-ink-2">{item.value}</span>
                </li>
              ))}
            </ol>
          </Panel>
        </div>
      ) : (
        <Panel>
          <EmptyState title="选择一张证书" hint="证书与私钥始终留在卡片上；云端只传输加密后的证书材料。" />
        </Panel>
      )}

      <CertImportModal
        open={importOpen}
        cards={cards}
        defaultCardId={cardFilter || current?.card_id}
        onClose={() => setImportOpen(false)}
        onImported={reload}
      />
    </div>
  );
}
