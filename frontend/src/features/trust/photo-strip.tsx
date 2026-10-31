import { BedDouble } from "lucide-react";
import { type ReactNode, useState } from "react";

import { cn } from "@/lib/utils";

import type { TrustImage } from "./model";

type PhotoStripProps = {
  images: readonly TrustImage[];
  /** How many photos to show at most. */
  max?: number;
  /** Example offers get desaturated photos and an "Example" watermark. */
  example?: boolean;
  /** "cover" = the first photo, wide; "row" = equal tiles side by side. */
  layout?: "cover" | "row";
  className?: string;
};

/** A placeholder tile in the stay's pastel: shown when there is no photo or it fails to load. */
function Fallback({ label }: { label: string }): ReactNode {
  return (
    <span
      role="img"
      aria-label={label}
      className="flex size-full items-center justify-center bg-pastel-lime text-pastel-ink/60"
    >
      <BedDouble className="size-6" strokeWidth={1.5} aria-hidden />
    </span>
  );
}

function Photo({ image, example }: { image: TrustImage; example: boolean }): ReactNode {
  const [failed, setFailed] = useState(false);
  if (failed) return <Fallback label={image.alt} />;
  return (
    <img
      src={image.url}
      alt={image.alt}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
      className={cn(
        "size-full object-cover transition duration-300 group-hover/photo:scale-[1.03]",
        example && "grayscale",
      )}
    />
  );
}

/**
 * Hotel photos in fixed aspect-ratio boxes — the layout never jumps while they load, and a
 * broken URL degrades to a quiet tile instead of a broken-image icon.
 */
export function PhotoStrip({
  images,
  max = 3,
  example = false,
  layout = "row",
  className,
}: PhotoStripProps): ReactNode {
  const shown = images.slice(0, layout === "cover" ? 1 : max);
  const tiles = shown.length > 0 ? shown : [null];
  return (
    <div
      className={cn(
        "relative grid auto-cols-fr grid-flow-col gap-1.5 overflow-hidden rounded-[20px]",
        className,
      )}
    >
      {tiles.map((image) => (
        <span
          key={image?.url ?? "fallback"}
          className={cn(
            "group/photo relative block overflow-hidden bg-surface-sunken",
            layout === "cover" ? "aspect-[2/1]" : "aspect-[4/3]",
          )}
        >
          {image ? <Photo image={image} example={example} /> : <Fallback label="No photo yet" />}
        </span>
      ))}
      {example && (
        <span className="ticket-mono pointer-events-none absolute top-2 left-2 rounded-full border border-dashed border-white/80 bg-black/45 px-2 py-0.5 text-[10px] uppercase tracking-wider text-white">
          Example photo
        </span>
      )}
    </div>
  );
}
