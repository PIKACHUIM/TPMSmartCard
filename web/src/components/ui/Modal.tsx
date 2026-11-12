import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { Button } from "./primitives";

interface ModalProps {
  open: boolean;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  width?: number;
}

export function Modal({ open, title, description, children, footer, onClose, width = 520 }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="关闭对话框"
        className="absolute inset-0 bg-graphite-0/70 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={{ width }}
        className="relative z-10 animate-fade-rise rounded-panel border border-line bg-graphite-1 p-5 shadow-lift"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-subhead text-ink-0">{title}</h2>
            {description ? <p className="mt-1 text-[12.5px] text-ink-2">{description}</p> : null}
          </div>
          <Button variant="ghost" size="sm" aria-label="关闭" onClick={onClose} icon={<X className="h-4 w-4" />} />
        </div>
        <div className="grid gap-4">{children}</div>
        {footer ? <div className="mt-5 flex justify-end gap-2">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}
