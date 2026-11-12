import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useAppStore } from "@/lib/store";
import { cn } from "@/lib/cn";

const icons = {
  ok: CheckCircle2,
  err: XCircle,
  info: Info,
};

const tones = {
  ok: "border-teal/40",
  err: "border-danger/40",
  info: "border-steel/40",
};

export function Toasts() {
  const toasts = useAppStore((state) => state.toasts);
  const dismiss = useAppStore((state) => state.dismissToast);

  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed bottom-10 right-5 z-50 flex w-[min(360px,calc(100vw-40px))] flex-col gap-2">
      {toasts.map((toast) => {
        const Icon = icons[toast.kind];
        return (
          <div
            key={toast.id}
            role="status"
            className={cn(
              "pointer-events-auto animate-fade-rise rounded-panel border bg-graphite-1/95 px-3.5 py-3 shadow-lift backdrop-blur",
              tones[toast.kind],
            )}
          >
            <div className="flex items-start gap-2.5">
              <Icon
                className={cn(
                  "mt-0.5 h-4 w-4 shrink-0",
                  toast.kind === "ok" && "text-teal",
                  toast.kind === "err" && "text-danger",
                  toast.kind === "info" && "text-steel",
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="text-[13px] text-ink-0">{toast.title}</p>
                {toast.detail ? <p className="mt-0.5 break-words text-[11.5px] text-ink-2">{toast.detail}</p> : null}
              </div>
              <button
                type="button"
                aria-label="关闭提示"
                onClick={() => dismiss(toast.id)}
                className="rounded p-1 text-ink-3 transition hover:text-ink-1"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
