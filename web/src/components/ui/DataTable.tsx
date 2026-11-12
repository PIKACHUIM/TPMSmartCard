import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { EmptyState, Spinner } from "./primitives";

export interface Column<T> {
  key: string;
  header: string;
  width?: string;
  align?: "left" | "right" | "center";
  render: (row: T) => ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  emptyTitle?: string;
  emptyHint?: string;
  onRowClick?: (row: T) => void;
  selectedKey?: string | null;
  dense?: boolean;
  caption?: string;
}

/** 数据密集页共用的表格：细线分隔、固定表头、键盘可达 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  emptyTitle = "暂无数据",
  emptyHint,
  onRowClick,
  selectedKey,
  dense,
  caption,
}: DataTableProps<T>) {
  if (loading) return <Spinner />;
  if (rows.length === 0) return <EmptyState title={emptyTitle} hint={emptyHint} />;

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left" aria-label={caption}>
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr className="border-b border-line/80">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                style={{ width: column.width }}
                className={cn(
                  "label-caps whitespace-nowrap px-3 py-2 font-normal",
                  column.align === "right" && "text-right",
                  column.align === "center" && "text-center",
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = rowKey(row);
            const selected = selectedKey === key;
            return (
              <tr
                key={key}
                tabIndex={onRowClick ? 0 : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
                className={cn(
                  "border-b border-line/40 transition-colors duration-150",
                  onRowClick && "cursor-pointer hover:bg-graphite-2/60 focus:bg-graphite-2/70 focus:outline-none",
                  selected && "bg-copper-400/[0.07]",
                )}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      "px-3 align-middle text-[13px] text-ink-1",
                      dense ? "py-1.5" : "py-3",
                      column.align === "right" && "text-right",
                      column.align === "center" && "text-center",
                    )}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
