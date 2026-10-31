import { Clock } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

const TICK_MS = 30_000;

/** "23h 14m left", "9m left", "expired" — a hold's remaining time, minute precision. */
export function holdLeft(expiresAt: string, now: number): string {
  const minutes = Math.floor((new Date(expiresAt).getTime() - now) / 60_000);
  if (minutes <= 0) return "expired";
  const hours = Math.floor(minutes / 60);
  return hours > 0 ? `${hours}h ${minutes % 60}m left` : `${minutes}m left`;
}

/** The supplier holds this price until `expiresAt`; a lapsed hold is re-held at start. */
export function HoldCountdown({ expiresAt }: { expiresAt: string }): ReactNode {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, []);
  const left = holdLeft(expiresAt, now);
  return (
    <span
      className={`inline-flex items-center gap-1 font-mono text-xs ${
        left === "expired" ? "text-danger" : "text-live"
      }`}
    >
      <Clock className="size-3" aria-hidden />
      price held · {left}
    </span>
  );
}
