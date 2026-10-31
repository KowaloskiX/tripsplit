import { AlertTriangle } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import { CountUp } from "@/components/ui/number-roll";
import type { ShareChangeResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

import { formatDelta, formatMoney } from "./money";

type DisruptionAlertProps = {
  replacements: number;
  totalMinor: number;
  previousTotalMinor: number;
  shares: readonly ShareChangeResponse[];
  currency: string;
};

/**
 * The disruption moment: the alert slides in with a short shake, then every share counts from
 * its old amount to its new one, the difference ticking alongside. Presentational.
 */
export function DisruptionAlert({
  replacements,
  totalMinor,
  previousTotalMinor,
  shares,
  currency,
}: DisruptionAlertProps): ReactNode {
  const money = (minor: number): string => formatMoney(minor, currency);
  const delta = (minor: number): string => formatDelta(minor, currency);
  const totalDelta = totalMinor - previousTotalMinor;

  return (
    <div
      role="alert"
      className="alert-in space-y-3 rounded-[24px] border border-danger/30 bg-danger-soft p-4"
    >
      <p className="flex items-start gap-2.5 text-sm text-ink">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
        <span>
          Replaced {replacements} {replacements === 1 ? "purchase" : "purchases"}. Rebooking: new
          total{" "}
          <CountUp
            className="ticket-mono"
            value={totalMinor}
            from={previousTotalMinor}
            format={money}
          />{" "}
          (
          <span className={cn("ticket-mono", totalDelta > 0 ? "text-danger" : "text-success")}>
            {delta(totalDelta)}
          </span>
          ).
        </span>
      </p>
      <ul className="divide-y divide-danger/15 text-sm">
        {shares.map((share, index) => (
          <li
            key={share.user_id}
            className="rise-in flex flex-wrap justify-between gap-x-3 gap-y-0.5 py-1.5"
            style={{ "--i": index, "--delay": "350ms" } as CSSProperties}
          >
            <span className="text-ink">{share.display_name}</span>
            <span className="ticket-mono text-muted">
              <CountUp
                value={share.share_minor}
                from={share.previous_minor}
                format={money}
                durationMs={900}
              />{" "}
              <span
                className={cn(
                  "inline-block rounded-full px-1.5",
                  share.delta_minor > 0
                    ? "bg-warn-soft text-warn"
                    : share.delta_minor < 0
                      ? "bg-info-soft text-info"
                      : "",
                )}
              >
                <CountUp value={share.delta_minor} format={delta} durationMs={900} from={0} />
              </span>{" "}
              · {share.status}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
