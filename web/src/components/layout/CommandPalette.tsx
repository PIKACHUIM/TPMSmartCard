import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CornerDownLeft, Search } from "lucide-react";
import { useAppStore } from "@/lib/store";
import { cn } from "@/lib/cn";
import { NAV_ITEMS } from "./nav";

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

/** Ctrl/Cmd+K 命令面板：跳页面、切主题、退出登录 */
export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const navigate = useNavigate();
  const can = useAppStore((state) => state.can);
  const toggleTheme = useAppStore((state) => state.toggleTheme);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const commands = useMemo(() => {
    const nav = NAV_ITEMS.filter((item) => !item.permission || can(item.permission)).map((item) => ({
      id: item.to,
      label: item.fallback,
      hint: "页面",
      run: () => navigate(item.to),
    }));
    return [
      ...nav,
      { id: "theme", label: "切换主题", hint: "外观", run: toggleTheme },
      { id: "login", label: "打开登录页", hint: "账号", run: () => navigate("/login") },
    ];
  }, [can, navigate, toggleTheme]);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return commands;
    return commands.filter((command) => `${command.label}${command.hint}`.toLowerCase().includes(keyword));
  }, [commands, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      window.setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setCursor((value) => Math.min(value + 1, filtered.length - 1));
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setCursor((value) => Math.max(value - 1, 0));
      }
      if (event.key === "Enter") {
        const command = filtered[cursor];
        if (command) {
          event.preventDefault();
          command.run();
          onClose();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, filtered, cursor, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[14vh]">
      <button type="button" aria-label="关闭命令面板" className="absolute inset-0 bg-graphite-0/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-[min(560px,100%)] animate-fade-rise overflow-hidden rounded-panel border border-line bg-graphite-1 shadow-lift">
        <div className="flex items-center gap-2 border-b border-line/70 px-4 py-3">
          <Search className="h-4 w-4 text-ink-3" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setCursor(0);
            }}
            placeholder="搜索页面或操作…"
            aria-label="命令搜索"
            className="w-full border-none bg-transparent text-body text-ink-0 placeholder:text-ink-3 focus:outline-none"
          />
        </div>
        <ul role="listbox" aria-label="命令列表" className="max-h-[320px] overflow-y-auto py-1">
          {filtered.length === 0 ? (
            <li className="px-4 py-6 text-center text-[12.5px] text-ink-2">没有匹配的命令</li>
          ) : (
            filtered.map((command, index) => (
              <li key={command.id} role="option" aria-selected={index === cursor}>
                <button
                  type="button"
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => {
                    command.run();
                    onClose();
                  }}
                  className={cn(
                    "flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left text-[13px] transition-colors",
                    index === cursor ? "bg-graphite-2 text-ink-0" : "text-ink-1 hover:bg-graphite-2/60",
                  )}
                >
                  <span>{command.label}</span>
                  <span className="flex items-center gap-2 text-[11px] text-ink-3">
                    {command.hint}
                    {index === cursor ? <CornerDownLeft className="h-3 w-3" /> : null}
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}
