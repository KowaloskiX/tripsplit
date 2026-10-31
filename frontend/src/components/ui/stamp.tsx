import type { CSSProperties, ReactNode } from "react";

import { cn } from "@/lib/utils";

const TONE = {
  lime: "border-ink bg-lime text-pastel-ink",
  ink: "border-ink bg-surface text-ink",
  danger: "border-danger bg-danger-soft text-danger",
  success: "border-success bg-success-soft text-success",
} as const;

type StampProps = {
  children: ReactNode;
  tone?: keyof typeof TONE;
  /** Tilt in degrees; a real stamp is never straight. */
  rotate?: number;
  /** Wait before landing, e.g. until a card has settled. */
  delayMs?: number;
  className?: string;
};

/** A rubber stamp that lands on whatever it is placed over: "chosen", "6/6 paid", "replaced". */
export function Stamp({
  children,
  tone = "lime",
  rotate = -10,
  delayMs = 0,
  className,
}: StampProps): ReactNode {
  return (
    <span
      className={cn(
        "stamp ticket-mono pointer-events-none inline-flex items-center gap-1.5 rounded-xl border-2 px-3 py-1 text-sm uppercase tracking-[0.12em] shadow-pop",
        TONE[tone],
        className,
      )}
      style={{ "--stamp-rot": `${rotate}deg`, "--delay": `${delayMs}ms` } as CSSProperties}
    >
      {children}
    </span>
  );
}
