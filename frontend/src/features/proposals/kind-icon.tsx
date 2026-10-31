import { BedDouble, Bus, Plane, Ship, Sparkles, TrainFront } from "lucide-react";
import type { ReactNode } from "react";

import type { BookingKind, TransportMode } from "@/lib/api";

type Icon = typeof TrainFront;

/** Pastel card fill per kind: transport sky, stay lime, activity blush. */
export const KIND_FILL: Record<BookingKind, string> = {
  transport: "bg-pastel-sky",
  stay: "bg-pastel-lime",
  activity: "bg-pastel-blush",
};

const MODE_ICON: Record<TransportMode, Icon> = {
  rail: TrainFront,
  flight: Plane,
  bus: Bus,
  ferry: Ship,
};
const MODE_LABEL: Record<TransportMode, string> = {
  rail: "Train",
  flight: "Flight",
  bus: "Bus",
  ferry: "Ferry",
};
const KIND_LABEL: Record<BookingKind, string> = {
  transport: "Transport",
  stay: "Stay",
  activity: "Activity",
};

export function kindLabel(kind: BookingKind, mode: TransportMode | null): string {
  return kind === "transport" && mode ? MODE_LABEL[mode] : KIND_LABEL[kind];
}

/** Plane / train / bus / ferry for transport, a bed for a stay, sparkles for an activity. */
export function KindIcon({
  kind,
  mode,
  className = "size-4 shrink-0 text-live",
}: {
  kind: BookingKind;
  mode: TransportMode | null;
  className?: string;
}): ReactNode {
  const Icon =
    kind === "transport" && mode ? MODE_ICON[mode] : kind === "stay" ? BedDouble : Sparkles;
  return <Icon className={className} aria-label={kindLabel(kind, mode)} role="img" />;
}
