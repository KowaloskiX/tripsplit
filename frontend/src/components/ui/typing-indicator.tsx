import type { CSSProperties, ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Three bouncing dots — "someone is typing". Decorative; pair it with a status text. */
export function TypingIndicator({ className }: { className?: string }): ReactNode {
  return (
    <span aria-hidden className={cn("inline-flex items-center gap-1", className)}>
      {[0, 1, 2].map((index) => (
        <span
          key={index}
          className="typing-dot size-1.5 rounded-full bg-current"
          style={{ "--i": index } as CSSProperties}
        />
      ))}
    </span>
  );
}
