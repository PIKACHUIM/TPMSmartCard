import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "outline" | "ghost" | "danger";
type Size = "sm" | "md";

const variants: Record<Variant, string> = {
  primary:
    "bg-copper-400 text-graphite-0 hover:bg-copper-300 active:bg-copper-500 shadow-[0_1px_0_rgba(255,255,255,0.18)_inset]",
  outline:
    "border border-line text-ink-0 hover:border-copper-400/60 hover:text-copper-300 bg-graphite-1/60",
  ghost: "text-ink-1 hover:text-ink-0 hover:bg-graphite-2/70",
  danger: "border border-danger/50 text-danger hover:bg-danger/10",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-[12.5px]",
  md: "h-10 px-4 text-body",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
}

export function Button({ variant = "outline", size = "md", icon, className, children, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      className={cn(
        "inline-flex select-none items-center justify-center gap-2 rounded-control font-medium transition-all duration-150 ease-precise",
        "disabled:cursor-not-allowed disabled:opacity-45",
        variants[variant],
        sizes[size],
        className,
      )}
    >
      {icon}
      {children}
    </button>
  );
}

export function Panel({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cn("surface p-5", className)}>{children}</section>;
}

export function SectionTitle({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <div>
        <h2 className="text-subhead text-ink-0">{title}</h2>
        {hint ? <p className="mt-1 text-[12.5px] text-ink-2">{hint}</p> : null}
      </div>
      {action}
    </div>
  );
}

type Tone = "ok" | "warn" | "danger" | "info" | "muted";

const tones: Record<Tone, string> = {
  ok: "border-teal/40 bg-teal/10 text-teal",
  warn: "border-amber/40 bg-amber/10 text-amber",
  danger: "border-danger/40 bg-danger/10 text-danger",
  info: "border-steel/40 bg-steel/10 text-steel",
  muted: "border-line bg-graphite-2/60 text-ink-2",
};

export function Badge({ tone = "muted", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px] tracking-wide",
        tones[tone],
        className,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      {children}
    </span>
  );
}

export function StatusDot({ tone = "ok", pulse }: { tone?: Tone; pulse?: boolean }) {
  const colors: Record<Tone, string> = {
    ok: "bg-teal",
    warn: "bg-amber",
    danger: "bg-danger",
    info: "bg-steel",
    muted: "bg-ink-3",
  };
  return (
    <span
      aria-hidden
      className={cn("inline-block h-1.5 w-1.5 rounded-full", colors[tone], pulse && "animate-pulse-line")}
    />
  );
}

export interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
}

export function Field({ label, hint, className, id, ...rest }: FieldProps) {
  const inputId = id ?? `f-${label.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <label htmlFor={inputId} className="grid gap-1.5">
      <span className="label-caps">{label}</span>
      <input
        id={inputId}
        {...rest}
        className={cn(
          "h-10 w-full rounded-control border border-line bg-graphite-0 px-3 text-body text-ink-0",
          "placeholder:text-ink-3 focus:border-copper-400 focus:outline-none focus:ring-2 focus:ring-copper-400/20",
          className,
        )}
      />
      {hint ? <span className="text-[11.5px] text-ink-3">{hint}</span> : null}
    </label>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
      <div className="mb-1 h-10 w-10 rounded-full border border-dashed border-line" aria-hidden />
      <p className="text-body text-ink-1">{title}</p>
      {hint ? <p className="max-w-sm text-[12.5px] text-ink-2">{hint}</p> : null}
      {action}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 px-2 py-6 text-ink-2" role="status" aria-live="polite">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-copper-400" aria-hidden />
      <span className="text-[12.5px]">{label ?? "正在读取…"}</span>
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-line bg-graphite-2 px-1.5 py-0.5 font-mono text-[10.5px] text-ink-2">
      {children}
    </kbd>
  );
}
