import { BedDouble, Sparkles, TrainFront } from "lucide-react";
import type { ReactNode } from "react";

import type { BookingKind } from "@/lib/api";

const LABEL: Record<BookingKind, string> = { train: "Train", stay: "Stay", activity: "Activity" };

/** Pastel card fill per kind: transport sky, stay lime, activity blush. */
export const KIND_FILL: Record<BookingKind, string> = {
  train: "bg-pastel-sky",
  stay: "bg-pastel-lime",
  activity: "bg-pastel-blush",
};

export function KindIcon({ kind }: { kind: BookingKind }): ReactNode {
  const Icon = kind === "train" ? TrainFront : kind === "stay" ? BedDouble : Sparkles;
  return <Icon className="size-[18px] shrink-0" aria-label={LABEL[kind]} role="img" />;
}
