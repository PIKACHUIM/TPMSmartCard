import { useEffect, useState } from "react";
import { ArchiveRestore, HardDriveDownload, ShieldAlert, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import type { BackupEntry, CardInfo } from "@/lib/types";
import { Badge, Button, EmptyState, Panel, SectionTitle, Spinner } from "@/components/ui/primitives";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { BackupCreateModal, BackupRestoreModal } from "./BackupDialogs";

const PROTECT_LABEL: Record<BackupEntry["protected_by"], string> = {
  certificates: "证书与元数据（私钥不可导出）",
  dpapi: "DPAPI（同一 TPM 才能还原）",
  tpm2: "TPM2 seal",
  keychain: "钥匙串（私钥不可导出）",
  passphrase: "口令加密",
};

export function BackupPage() {
  const [backups, setBackups] = useState<BackupEntry[] | null>(null);
  const [cards, setCards] = useState<CardInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [restoreOpen, setRestoreOpen] = useState(false);

  const load = () => {
    void Promise.all([api.backups(), api.cards()])
      .then(([backupResult, cardResult]) => {
        setBackups(backupResult.backups);
        setCards(cardResult.cards);
        setSelected((current) => current ?? backupResult.backups[0]?.id ?? null);
      })
      .catch((err: Error) => console.error("backups load failed", err));
  };

  useEffect(load, []);

  if (backups === null) return <Spinner label="正在读取备份历史…" />;

  const current = backups.find((item) => item.id === selected) ?? null;

  const columns: Column<BackupEntry>[] = [
    {
      key: "file",
      header: "备份包",
      render: (row) => (
        <div className="min-w-0">
          <p className="truncate font-mono text-[12px] text-ink-0">{row.file}</p>
          <p className="truncate text-[11px] text-ink-3">
            {row.card_name} · {row.certificates ?? 0} 张证书
          </p>
        </div>
      ),
    },
    {
      key: "size",
      header: "大小",
      width: "100px",
      align: "right",
      render: (row) => <span className="mono-num text-[11.5px]">{(row.size_bytes / 1024).toFixed(0)} KB</span>,
    },
    {
      key: "protect",
      header: "内容",
      width: "210px",
      render: (row) => <span className="text-[11.5px] text-ink-2">{PROTECT_LABEL[row.protected_by] ?? row.protected_by}</span>,
    },
    {
      key: "status",
      header: "状态",
      width: "100px",
      render: (row) => (
        <Badge tone={row.status === "verified" ? "ok" : row.status === "failed" ? "danger" : "warn"}>
          {row.status === "verified" ? "已校验" : row.status === "failed" ? "校验失败" : "未校验"}
        </Badge>
      ),
    },
  ];

  return (
    <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
      <div className="grid content-start gap-5">
        <Panel className="p-0">
          <div className="flex items-center justify-between border-b border-line/70 px-4 py-3">
            <div>
              <p className="label-caps">备份历史</p>
              <p className="mono-num text-[13px] text-ink-1">{backups.length} 个备份包</p>
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="primary"
                icon={<HardDriveDownload className="h-3.5 w-3.5" />}
                onClick={() => setCreateOpen(true)}
                disabled={cards.length === 0}
              >
                新建备份
              </Button>
              <Button
                size="sm"
                icon={<ArchiveRestore className="h-3.5 w-3.5" />}
                onClick={() => setRestoreOpen(true)}
                disabled={!current}
              >
                还原
              </Button>
            </div>
          </div>
          <div className="p-2">
            <DataTable
              columns={columns}
              rows={backups}
              rowKey={(row) => row.id}
              selectedKey={selected}
              onRowClick={(row) => setSelected(row.id)}
              caption="备份包列表"
              emptyTitle="还没有备份"
              emptyHint="选中一张卡片后点「新建备份」，会打包证书与元数据；私钥不会离开芯片。"
            />
          </div>
        </Panel>

        <Panel className="border-amber/30">
          <div className="flex items-start gap-3">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber" />
            <div className="text-[12.5px] leading-relaxed text-ink-2">
              <p className="mb-1 text-ink-1">备份不是「换机迁移」工具</p>
              <p>
                当前备份只包含公钥证书与元数据：TPM / Secure Enclave 的私钥不可导出，
                换机或重装系统后需要重新生成密钥并重新签发。删除卡片后，即使有备份也无法恢复私钥。
              </p>
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid content-start gap-5">
        {current ? (
          <Panel>
            <SectionTitle
              title="备份详情"
              hint={current.file}
              action={<Badge tone={current.status === "verified" ? "ok" : "warn"}>{current.status === "verified" ? "已校验" : "需重新校验"}</Badge>}
            />
            <dl className="grid gap-3 text-[12.5px]">
              <div>
                <dt className="label-caps">来源卡片</dt>
                <dd className="mt-1 text-ink-1">{current.card_name}</dd>
              </div>
              <div>
                <dt className="label-caps">创建时间</dt>
                <dd className="mono-num mt-1 text-[11.5px]">{new Date(current.created_at).toLocaleString()}</dd>
              </div>
              <div>
                <dt className="label-caps">内容</dt>
                <dd className="mt-1 text-ink-1">
                  {PROTECT_LABEL[current.protected_by] ?? current.protected_by} · {current.certificates ?? 0} 张证书
                </dd>
              </div>
              <div>
                <dt className="label-caps">私钥是否在包内</dt>
                <dd className="mt-1">
                  <Badge tone={current.key_exportable ? "warn" : "ok"}>
                    {current.key_exportable ? "包含私钥（高风险）" : "不包含（推荐）"}
                  </Badge>
                </dd>
              </div>
            </dl>

            {current.warnings && current.warnings.length > 0 ? (
              <ul className="mt-3 grid gap-1 rounded-control border border-amber/30 bg-amber/10 px-3 py-2 text-[11.5px] leading-relaxed text-ink-2">
                {current.warnings.map((warning) => (
                  <li key={warning}>· {warning}</li>
                ))}
              </ul>
            ) : null}

            <div className="mt-4 flex flex-wrap gap-2 border-t border-line/60 pt-3">
              <Button
                size="sm"
                icon={<ArchiveRestore className="h-3.5 w-3.5" />}
                onClick={() => setRestoreOpen(true)}
                disabled={cards.length === 0}
              >
                还原到卡片
              </Button>
            </div>
          </Panel>
        ) : (
          <Panel>
            <EmptyState title="选择一个备份包" hint="右侧会显示备份内容与风险提示；还原前请确认目标卡片与 PIN。" />
          </Panel>
        )}

        <Panel>
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
            <div className="text-[12px] leading-relaxed text-ink-2">
              <p className="text-ink-1">.tsb 等同密钥材料</p>
              <p className="mt-1">导出后请离线保管，工具不会自动上传任何备份；当前版本也不支持把备份导入到云端。</p>
            </div>
          </div>
        </Panel>
      </div>

      <BackupCreateModal
        open={createOpen}
        cards={cards}
        onClose={() => setCreateOpen(false)}
        onCreated={(entry) => {
          setBackups((currentList) => [entry, ...(currentList ?? [])]);
          setSelected(entry.id);
        }}
      />
      <BackupRestoreModal
        open={restoreOpen}
        backup={current}
        cards={cards}
        onClose={() => setRestoreOpen(false)}
        onRestored={load}
      />
    </div>
  );
}
