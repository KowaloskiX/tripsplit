import { type ReactNode, useEffect, useState } from "react";

type LiveFrameProps = {
  /** The frame URL; it changes (cache buster) whenever a newer frame should be fetched. */
  src: string;
  alt: string;
  /** Shown instead of a frame until the first one loads, e.g. "step 3 · searching". */
  placeholder: string;
};

/**
 * The agent's live browser view. A new frame is preloaded off-screen and swapped in only once
 * it has loaded, so the panel never shows an empty bordered strip: before the first frame (or
 * while the run has none, e.g. it has not opened the page yet) it shows the placeholder text.
 */
export function LiveFrame({ src, alt, placeholder }: LiveFrameProps): ReactNode {
  const [shown, setShown] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    const image = new Image();
    image.onload = () => {
      if (current) setShown(src);
    };
    image.src = src;
    return () => {
      current = false;
    };
  }, [src]);

  if (shown === null) {
    return (
      <p className="text-sm text-muted" role="status">
        {placeholder}
      </p>
    );
  }
  return (
    <img
      src={shown}
      alt={alt}
      className="w-full rounded-[var(--radius-control)] border border-line bg-surface-sunken"
    />
  );
}
