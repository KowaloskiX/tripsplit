import { Check, Copy } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";

export function inviteUrl(inviteCode: string, origin = window.location.origin): string {
  return `${origin}/join/${encodeURIComponent(inviteCode)}`;
}

export function InviteLink({ inviteCode }: { inviteCode: string }): ReactNode {
  const [copied, setCopied] = useState(false);
  const url = inviteUrl(inviteCode);

  const copy = async (): Promise<void> => {
    await navigator.clipboard.writeText(url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2_000);
  };

  return (
    <div className="flex min-w-0 items-center gap-2">
      {/* The URL is read out, not shown: the button is what people use. */}
      <code className="sr-only">{url}</code>
      <Button variant="outline" size="sm" onClick={() => void copy()} aria-label="Copy invite link">
        {copied ? (
          <Check className="size-3.5" aria-hidden />
        ) : (
          <Copy className="size-3.5" aria-hidden />
        )}
        {copied ? "Copied" : "Invite friends"}
      </Button>
    </div>
  );
}
