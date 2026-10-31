import { Building2, Landmark, Mountain, Sparkles, UtensilsCrossed } from "lucide-react";
import type { ReactNode } from "react";

import type { AttractionKind } from "@/lib/api";

type Icon = typeof Landmark;

const ICON: Record<AttractionKind, Icon> = {
  museum: Building2,
  landmark: Landmark,
  viewpoint: Mountain,
  food: UtensilsCrossed,
  experience: Sparkles,
};

const LABEL: Record<AttractionKind, string> = {
  museum: "Museum",
  landmark: "Landmark",
  viewpoint: "Viewpoint",
  food: "Food",
  experience: "Experience",
};

/** Pastel fill per kind, for a card without a photo and for the kind chip. */
export const ATTRACTION_FILL: Record<AttractionKind, string> = {
  museum: "bg-[#f7d6e0]",
  landmark: "bg-pastel-sea",
  viewpoint: "bg-[#c9f2e2]",
  food: "bg-[#ffe2c2]",
  experience: "bg-pastel-blush",
};

export function attractionKindLabel(kind: AttractionKind): string {
  return LABEL[kind];
}

export function AttractionKindIcon({
  kind,
  className = "size-4 shrink-0",
}: {
  kind: AttractionKind;
  className?: string;
}): ReactNode {
  const Icon = ICON[kind];
  return <Icon className={className} aria-hidden />;
}
