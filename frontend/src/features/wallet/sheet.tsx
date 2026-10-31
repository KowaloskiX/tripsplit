import { X } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef } from "react";

import { Button } from "@/components/ui/button";

type SheetProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
};

/** A bottom sheet on a phone, a centred dialog on a wider screen. Escape and the backdrop close it. */
export function Sheet({ open, onClose, title, description, children }: SheetProps): ReactNode {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    panel.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center">
      <button
        type="button"
        aria-label="Close"
        tabIndex={-1}
        className="absolute inset-0 bg-black/45 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative max-h-[92dvh] w-full overflow-y-auto rounded-t-[var(--radius-panel)] border border-line bg-surface p-5 shadow-card focus:outline-none sm:max-w-md sm:rounded-[var(--radius-panel)] sm:p-6"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 id={titleId} className="text-xl tracking-[-0.02em] text-ink">
              {title}
            </h2>
            {description && <p className="mt-1 text-sm text-muted">{description}</p>}
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X className="size-4" aria-hidden />
          </Button>
        </div>
        {children}
      </div>
    </div>
  );
}
