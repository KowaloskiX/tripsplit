import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

import { CONTROL_CLASS } from "./input";

export function Textarea({ className, ...props }: ComponentProps<"textarea">): ReactNode {
  return <textarea className={cn(CONTROL_CLASS, "min-h-20 py-2.5", className)} {...props} />;
}
