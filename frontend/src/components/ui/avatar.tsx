import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Pastel fills with black initials; a name always lands on the same one. */
const PALETTE = [
  "bg-pastel-sea",
  "bg-pastel-apricot",
  "bg-pastel-blush",
  "bg-[#e6dcff]",
  "bg-[#ffe2c2]",
  "bg-[#c9f2e2]",
  "bg-[#efe8d6]",
] as const;

export function initialsOf(name: string): string {
  const words = name
    .trim()
    .split(/[\s._-]+/)
    .filter(Boolean);
  const first = words[0]?.[0] ?? "?";
  const second = words.length > 1 ? (words[words.length - 1]?.[0] ?? "") : (words[0]?.[1] ?? "");
  return `${first}${second}`.toUpperCase();
}

function paletteOf(name: string): string {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return PALETTE[hash % PALETTE.length] ?? PALETTE[0];
}

type AvatarProps = {
  name: string;
  size?: "sm" | "md";
  className?: string;
};

/** Initials in a coloured circle. Decorative: the name is always rendered next to it. */
export function Avatar({ name, size = "md", className }: AvatarProps): ReactNode {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center rounded-full font-medium text-pastel-ink ring-2 ring-surface",
        size === "sm" ? "size-8 text-[11px]" : "size-9 text-xs",
        paletteOf(name),
        className,
      )}
    >
      {initialsOf(name)}
    </span>
  );
}

type AvatarStackProps = {
  /** `id` keys the circle: two people may share a name. */
  people: readonly { id: string; name: string }[];
  /** How many circles before a "+N". */
  max?: number;
  label?: string;
};

// A small overlap: with the 2 px ring, a bigger one covered the right half of the previous
// circle's second initial ("ON" read as "OI").
const STACK_OVERLAP = "-ml-1";

export function AvatarStack({ people, max = 5, label }: AvatarStackProps): ReactNode {
  const shown = people.slice(0, max);
  const rest = people.length - shown.length;
  return (
    <span
      className="inline-flex items-center"
      role="img"
      aria-label={label ?? people.map((person) => person.name).join(", ")}
    >
      {shown.map((person, index) => (
        <Avatar
          key={person.id}
          name={person.name}
          size="sm"
          className={index > 0 ? STACK_OVERLAP : ""}
        />
      ))}
      {rest > 0 && (
        <span
          aria-hidden
          className={`${STACK_OVERLAP} inline-flex size-8 items-center justify-center rounded-full bg-surface-sunken text-[11px] font-semibold text-muted ring-2 ring-surface`}
        >
          +{rest}
        </span>
      )}
    </span>
  );
}
