import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Search } from "lucide-react";
import { api } from "@/lib/api";
import type { AuditRow } from "@tpmsc/protocol";
import { Badge, Button, Panel } from "@/components/ui/primitives";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { cn } from "@/lib/cn";

const RESULT: Record<AuditRow["result"], { text: string; tone: "ok" | "warn" | "danger" }> = {
  ok: { text: "成功", tone: "ok" },
  deny: { text: "拒绝", tone: "warn" },
  error: { text: "异常", tone: "danger" },
};

export function AuditPage() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    api
      .audit({ actor, action, limit: 100 })
      .then((result) => {
        setRows(result.rows);
        setTotal(result.total);
      })
      .catch((err) => console.error("audit load failed", err))
      .finally(() => setLoading(false));
  }, [actor, action]);

  useEffect(() => {
    const timer = window.setTimeout(load, 220);
    return () => window.clearTimeout(timer);
  }, [load]);

  const columns: Column<AuditRow>[] = [
    {
      key: "time",
      header: "时间",
      width: "160px",
      render: (row) => (
        <span className="mono-num text-[11px] text-ink-3">{new Date(row.created_at).toLocaleString()}</span>
      ),
    },
    {
      key: "actor",
      header: "操作者",
      width: "180px",
      render: (row) => <span className="font-mono text-[11.5px] text-ink-1">{row.actor}</span>,
    },
    {
      key: "action",
      header: "动作",
      width: "190px",
      render: (row) => <span className="font-mono text-[11.5px] text-ink-1">{row.action}</span>,
    },
    {
      key: "target",
      header: "对象",
      render: (row) => <span className="truncate font-mono text-[10.5px] text-ink-3">{row.target ?? "—"}</span>,
    },
    {
      key: "result",
      header: "结果",
      width: "90px",
      render: (row) => <Badge tone={RESULT[row.result].tone}>{RESULT[row.result].text}</Badge>,
    },
    {
      key: "ip",
      header: "来源",
      width: "150px",
      render: (row) => (
        <div className="min-w-0">
          <p className="mono-num truncate text-[10.5px] text-ink-3">{row.ip ?? "—"}</p>
          <p className="truncate text-[10px] text-ink-3/80">{row.user_agent ?? ""}</p>
        </div>
      ),
    },
    {
      key: "detail",
      header: "详情",
      width: "220px",
      render: (row) => <span className="truncate text-[11px] text-ink-2">{row.detail ?? "—"}</span>,
    },
  ];

  return (
    <Panel className="p-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-line/70 px-4 py-3">
        <div className="mr-auto">
          <p className="label-caps">审计日志</p>
          <p className="mono-num text-[13px] text-ink-1">{total} 条</p>
        </div>

        <div className="flex h-8 items-center gap-2 rounded-control border border-line bg-graphite-0 px-2">
          <Search className="h-3.5 w-3.5 text-ink-3" />
          <input
            value={actor}
            onChange={(event) => setActor(event.target.value)}
            placeholder="按操作者过滤"
            aria-label="按操作者过滤"
            className="w-36 border-none bg-transparent text-[12px] text-ink-0 placeholder:text-ink-3 focus:outline-none"
          />
        </div>

        <div className="flex h-8 items-center gap-2 rounded-control border border-line bg-graphite-0 px-2">
          <Search className="h-3.5 w-3.5 text-ink-3" />
          <input
            value={action}
            onChange={(event) => setAction(event.target.value)}
            placeholder="按动作过滤，如 delivery"
            aria-label="按动作过滤"
            className="w-44 border-none bg-transparent text-[12px] text-ink-0 placeholder:text-ink-3 focus:outline-none"
          />
        </div>

        <Button
          variant="ghost"
          size="sm"
          aria-label="刷新"
          onClick={load}
          icon={<RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />}
        />
      </div>

      <div className="p-2">
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(row) => String(row.id)}
          loading={loading && rows.length === 0}
          dense
          caption="审计日志"
          emptyTitle="没有匹配的审计记录"
          emptyHint="登录、上传、下发、删除与拒绝操作都会记录在这里。"
        />
      </div>
    </Panel>
  );
}
