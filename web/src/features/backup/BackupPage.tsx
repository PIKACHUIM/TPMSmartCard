import { useEffect, useState } from "react";
import { ArchiveRestore, HardDriveDownload, ShieldAlert, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import type { BackupEntry } from "@/lib/types";
import { useAppStore } from "@/lib/store";
import { Badge, Button, EmptyState, Panel, SectionTitle, Spinner } from "@/components/ui/primitives";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { cn } from "@/lib/cn";

const PROTECT_LABEL: Record<BackupEntry["protected_by"], string> = {
  dpapi: "DPAPI（同一 TPM 才能还原）",
  tpm2: "TPM2 seal",
  keychain: "钥匙串（私钥不可导出）",
  passphrase: "口令加密",
};

/** 还原诊断三层：设备节点 → 读卡器 → 密钥容器（DPAPI / TPM2 / Keychain） */
const DIAGNOSIS = [
  { layer: "设备节点", status: "ok", detail: "ROOT\\SMARTCARDREADER\\0000 已存在，驱动 tpmvsc.dll 正常" },
  { layer: "读卡器发布", status: "ok", detail: "PC/SC 枚举到 2 个读卡器，与备份清单一致" },
  { layer: "密钥容器", status: "warn", detail: "DPAPI 需要借用 SYSTEM 令牌重新加密，预计 8~15 秒" },
] as const;

export function BackupPage() {
  const [backups, setBackups] = useState<BackupEntry[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const pushToast = useAppStore((state) => state.pushToast);

  useEffect(() => {
    let cancelled = false;
    void api
      .backups()
      .then((result) => {
        if (cancelled) return;
        setBackups(result.backups);
        setSelected(result.backups[0]?.id ?? null);
      })
      .catch((err) => console.error("backups load failed", err));
    return () => {
      cancelled = true;
    };
  }, []);

  if (!backups) return <Spinner label="正在读取备份历史…" />;

  const current = backups.find((item) => item.id === selected) ?? null;

  const columns: Column<BackupEntry>[] = [
    {
      key: "file",
      header: "备份包",
      render: (row) => (
        <div className="min-w-0">
          <p className="truncate font-mono text-[12px] text-ink-0">{row.file}</p>
          <p className="truncate text-[11px] text-ink-3">{row.card_name}</p>
        </div>
      ),
    },
    {
      key: "size",
      header: "大小",
      width: "110px",
      align: "right",
      render: (row) => <span className="mono-num text-[11.5px]">{(row.size_bytes / 1024 / 1024).toFixed(1)} MB</span>,
    },
    {
      key: "protect",
      header: "保护方式",
      width: "180px",
      render: (row) => <span className="text-[11.5px] text-ink-2">{PROTECT_LABEL[row.protected_by]}</span>,
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
                onClick={() =>
                  pushToast({
                    kind: "ok",
                    title: "备份已开始",
                    detail: "打包卡片数据、设备注册表、TPM 密钥索引与 DPAPI 明文；过程可在日志抽屉查看",
                  })
                }
              >
                新建备份
              </Button>
              <Button size="sm" icon={<ArchiveRestore className="h-3.5 w-3.5" />} onClick={() => setSelected(backups[0]?.id ?? null)}>
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
              emptyHint="备份文件等同密钥材料，请离线保管，不要放进云盘或版本库。"
            />
          </div>
        </Panel>

        <Panel className="border-amber/30">
          <div className="flex items-start gap-3">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber" />
            <div className="text-[12.5px] leading-relaxed text-ink-2">
              <p className="mb-1 text-ink-1">备份不是「换机迁移」工具</p>
              <p>
                Windows 备份绑定同一颗 TPM（重装系统可以，换机器不行）；Linux 使用 TPM2 seal；
                macOS 的 Secure Enclave 私钥不可导出，备份只含证书、证书链与元数据。
                删除卡片后，即使有备份也无法还原。
              </p>
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid content-start gap-5">
        {current ? (
          <Panel>
            <SectionTitle
              title="还原诊断"
              hint={current.file}
              action={<Badge tone={current.status === "verified" ? "ok" : "warn"}>{current.status === "verified" ? "可还原" : "需重新校验"}</Badge>}
            />
            <ol className="grid gap-2">
              {DIAGNOSIS.map((item, index) => (
                <li key={item.layer} className="rounded-control border border-line/70 bg-graphite-0/40 px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "flex h-5 w-5 items-center justify-center rounded-full border font-mono text-[10px]",
                        item.status === "ok" ? "border-teal/50 text-teal" : "border-amber/50 text-amber",
                      )}
                    >
                      {index + 1}
                    </span>
                    <span className="text-[12.5px] text-ink-1">{item.layer}</span>
                    <Badge tone={item.status === "ok" ? "ok" : "warn"} className="ml-auto">
                      {item.status === "ok" ? "通过" : "待处理"}
                    </Badge>
                  </div>
                  <p className="mt-1.5 pl-7 text-[11.5px] leading-relaxed text-ink-3">{item.detail}</p>
                </li>
              ))}
            </ol>

            <div className="mt-4 border-t border-line/60 pt-3">
              <p className="label-caps mb-1">完整日志</p>
              <pre className="max-h-40 overflow-auto rounded-control bg-graphite-0/70 p-3 font-mono text-[10.5px] leading-relaxed text-ink-3">
{`[restore] manifest = tsb/2, platform = windows, ek = 8F:3A:91...
[restore] device  ROOT\\SMARTCARDREADER\\0000      OK
[restore] reader  Microsoft Virtual Smart Card 0  OK
[restore] dpapi   borrow SYSTEM token             WARN (retry 1)
[restore] conclusion: 可以还原，预计 12s；还原后需重启设备`}
              </pre>
            </div>
          </Panel>
        ) : (
          <Panel>
            <EmptyState title="选择一个备份包" hint="还原前会先跑三层诊断，再决定是否写入系统目录。" />
          </Panel>
        )}

        <Panel>
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
            <div className="text-[12px] leading-relaxed text-ink-2">
              <p className="text-ink-1">.tsb 等同密钥材料</p>
              <p className="mt-1">默认使用口令或平台密钥保护；导出后请离线保管，工具不会自动上传任何备份。</p>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
