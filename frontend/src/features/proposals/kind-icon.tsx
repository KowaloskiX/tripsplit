import { BedDouble, Sparkles, TrainFront } from "lucide-react";
import type { ReactNode } from "react";

import type { BookingKind } from "@/lib/api";

const LABEL: Record<BookingKind, string> = { train: "Train", stay: "Stay", activity: "Activity" };

export function KindIcon({ kind }: { kind: BookingKind }): ReactNode {
  const Icon = kind === "train" ? TrainFront : kind === "stay" ? BedDouble : Sparkles;
  return <Icon className="size-4 shrink-0 text-live" aria-label={LABEL[kind]} role="img" />;
}
