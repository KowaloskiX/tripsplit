import type { ReactNode } from "react";

import { usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";

type BackgroundVideoProps = {
  src: string;
  poster: string;
  className?: string;
};

/**
 * A muted, looping, decorative video that covers its positioned parent. With reduced motion
 * (or before the video loads) the poster is shown instead.
 */
export function BackgroundVideo({ src, poster, className }: BackgroundVideoProps): ReactNode {
  const reduced = usePrefersReducedMotion();
  const cover = cn("pointer-events-none absolute inset-0 size-full object-cover", className);
  if (reduced) return <img src={poster} alt="" aria-hidden className={cover} />;
  return (
    <video
      className={cover}
      src={src}
      poster={poster}
      autoPlay
      muted
      loop
      playsInline
      preload="metadata"
      aria-hidden
      tabIndex={-1}
    />
  );
}
