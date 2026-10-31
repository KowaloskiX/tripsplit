import { SendHorizontal } from "lucide-react";
import { type FormEvent, type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { usePostMessage } from "./mutations";

export function MessageInput({ tripId }: { tripId: string }): ReactNode {
  const [text, setText] = useState("");
  const post = usePostMessage(tripId);

  const submit = (event: FormEvent): void => {
    event.preventDefault();
    const message = text.trim();
    if (!message) return;
    post.mutate(
      { path: { trip_id: tripId }, body: { text: message } },
      { onSuccess: () => setText("") },
    );
  };

  return (
    <form onSubmit={submit} className="flex gap-2">
      <label htmlFor="feed-message" className="sr-only">
        Message the group
      </label>
      <Input
        id="feed-message"
        placeholder="Message the group…"
        value={text}
        maxLength={2000}
        onChange={(event) => setText(event.target.value)}
      />
      <Button type="submit" disabled={post.isPending || !text.trim()} aria-label="Send">
        <SendHorizontal className="size-4" aria-hidden />
      </Button>
    </form>
  );
}
