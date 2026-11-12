import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Search, Trash2, UploadCloud } from "lucide-react";
import { api } from "@/lib/api";
import type { RecordRow } from "@tpmsc/protocol";
import { useAppStore } from "@/lib/store";
import { Badge, Button, Panel } from "@/components/ui/primitives";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Modal } from "@/components/ui/Modal";
import { DeliveryUploadModal } from "./DeliveryUploadModal";
import { cn } from "@/lib/cn";

const STATE: Record<RecordRow["state"], { text: string; tone: "ok" | "warn" | "danger" | "muted" }> = {
  active: { text: "可下发", tone: "ok" },
  exhausted: { text: "已用尽", tone: "muted" },
  expired: { text: "已过期", tone: "warn" },
  revoked: { text: "已删除", tone: "danger" },
};

export function RecordsPage() {
  const [rows, setRows] = useState<RecordRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("");
  const [state, setState] = useState("");
  const [pending, setPending] = useState<RecordRow | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const can = useAppStore((store) => store.can);
  const pushToast = useAppStore((store) => store.pushToast);

  const load = useCallback(() => {
    setLoading(true);
    api
      .records({ q: query, mode, state, limit: 50 })
      .then((result) => {
        setRows(result.rows);
        setTotal(result.total);
      })
      .catch((err) => console.error("records load failed", err))
      .finally(() => setLoading(false));
  }, [query, mode, state]);

  useEffect(() => {
    const timer = window.setTimeout(load, 220);
    return () => window.clearTimeout(timer);
  }, [load]);

  const remove = () => {
    if (!pending) return;
    const target = pending;
    setPending(null);
    api
      .deleteRecord(target.id)
      .then(() => {
        setRows((current) => current.filter((row) => row.id !== target.id));
        pushToast({ kind: "ok", title: "记录已删除", detail: "KV 密文同步清除，取件码立即失效" });
      })
      .catch((err: Error) => {
        console.error("delete failed", err);
        pushToast({ kind: "err", title: "删除失败", detail: err.message });
      });
  };

  const columns: Column<RecordRow>[] = [
    {
      key: "label",
      header: "备注 / 指纹",
      render: (row) => (
        <div className="min-w-0">
          <p className="truncate text-[13px] text-ink-0">{row.label ?? "未命名"}</p>
          <p className="truncate font-mono text-[10.5px] text-ink-3">{row.fingerprint}</p>
        </div>
      ),
    },
    {
      key: "mode",
      header: "模式",
      width: "90px",
      render: (row) => (
        <Badge tone={row.mode === "code" ? "info" : "muted"}>{row.mode === "code" ? "取件码" : "传输密钥"}</Badge>
      ),
    },
    {
      key: "subject",
      header: "主体",
      width: "180px",
      render: (row) => (
        <div className="min-w-0">
          <p className="truncate text-[12px] text-ink-1">{row.common_name ?? "—"}</p>
          <p className="truncate font-mono text-[10.5px] text-ink-3">{row.serial_number ?? ""}</p>
        </div>
      ),
    },
    {
      key: "uses",
      header: "用量",
      width: "90px",
      align: "right",
      render: (row) => (
        <span className="mono-num text-[11.5px] text-ink-2">
          {row.used}/{row.max_uses}
        </span>
      ),
    },
    {
      key: "state",
      header: "状态",
      width: "100px",
      render: (row) => <Badge tone={STATE[row.state].tone}>{STATE[row.state].text}</Badge>,
    },
    {
      key: "expires",
      header: "到期",
      width: "150px",
      render: (row) => (
        <span className="mono-num text-[11px] text-ink-3">
          {row.expires_at ? new Date(row.expires_at).toLocaleString() : "永久"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      width: "60px",
      align: "right",
      render: (row) => (
        <Button
          variant="ghost"
          size="sm"
          aria-label="删除记录"
          disabled={!can("record:delete") || row.state === "revoked"}
          onClick={(event) => {
            event.stopPropagation();
            setPending(row);
          }}
          icon={<Trash2 className="h-3.5 w-3.5" />}
        />
      ),
    },
  ];

  return (
    <Panel className="p-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-line/70 px-4 py-3">
        <div className="mr-auto">
          <p className="label-caps">下发记录</p>
          <p className="mono-num text-[13px] text-ink-1">{total} 条</p>
        </div>

        <div className="flex h-8 items-center gap-2 rounded-control border border-line bg-graphite-0 px-2">
          <Search className="h-3.5 w-3.5 text-ink-3" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索备注、主体或序列号"
            aria-label="搜索下发记录"
            className="w-48 border-none bg-transparent text-[12px] text-ink-0 placeholder:text-ink-3 focus:outline-none"
          />
        </div>

        <select
          value={mode}
          onChange={(event) => setMode(event.target.value)}
          aria-label="按模式过滤"
          className="h-8 rounded-control border border-line bg-graphite-0 px-2 text-[12px] text-ink-1 focus:border-copper-400 focus:outline-none"
        >
          <option value="">全部模式</option>
          <option value="code">取件码</option>
          <option value="key">传输密钥</option>
        </select>

        <select
          value={state}
          onChange={(event) => setState(event.target.value)}
          aria-label="按状态过滤"
          className="h-8 rounded-control border border-line bg-graphite-0 px-2 text-[12px] text-ink-1 focus:border-copper-400 focus:outline-none"
        >
          <option value="">全部状态</option>
          <option value="active">可下发</option>
          <option value="exhausted">已用尽</option>
          <option value="expired">已过期</option>
          <option value="revoked">已删除</option>
        </select>

        <Button
          variant="primary"
          size="sm"
          disabled={!can("cert:deliver")}
          onClick={() => setUploadOpen(true)}
          icon={<UploadCloud className="h-3.5 w-3.5" />}
        >
          投递证书
        </Button>

        <Button variant="ghost" size="sm" aria-label="刷新" onClick={load} icon={<RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />} />
      </div>

      <div className="p-2">
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(row) => row.id}
          loading={loading && rows.length === 0}
          dense
          caption="证书下发记录"
          emptyTitle="没有匹配的记录"
          emptyHint="上传 PFX 或由 OpenCertRepo 推送后会出现在这里。"
        />
      </div>

      <Modal
        open={Boolean(pending)}
        title="删除下发记录"
        description="删除会立即清除 KV 中的密文，已发出的取件码将无法取回。"
        onClose={() => setPending(null)}
        footer={
          <>
            <Button size="sm" onClick={() => setPending(null)}>
              取消
            </Button>
            <Button size="sm" variant="danger" onClick={remove}>
              删除
            </Button>
          </>
        }
      >
        <p className="text-[12.5px] text-ink-2">
          目标：<span className="font-mono text-ink-0">{pending?.label ?? pending?.id}</span>
        </p>
      </Modal>

      <DeliveryUploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} onUploaded={load} />
    </Panel>
  );
}
