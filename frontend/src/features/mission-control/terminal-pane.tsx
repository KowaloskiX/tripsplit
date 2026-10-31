import { type CSSProperties, type ReactNode, useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

import { type ApiCall, type CallTone, callTone, formatCall } from "./model";

const TONE: Record<CallTone, string> = {
  ok: "text-lime",
  redirect: "text-pastel-sky",
  client: "text-[#ffc56e]",
  server: "text-[#ff9b94]",
};

/** Typing speed for a fresh line: steps per character, capped so long paths stay snappy. */
function typing(text: string): CSSProperties {
  const steps = Math.min(48, text.length);
  return { "--type-steps": steps, "--type-ms": `${Math.min(700, steps * 14)}ms` } as CSSProperties;
}

function Line({ call, fresh }: { call: ApiCall; fresh: boolean }): ReactNode {
  const text = formatCall(call);
  const tone = callTone(call.status);
  const time = text.slice(0, 8);
  return (
    <li className="relative overflow-hidden whitespace-pre">
      <span className="text-agent-fg/45">{time}</span>
      {"  "}
      <span className="text-agent-fg">{call.method.padEnd(6)}</span>{" "}
      <span className="text-agent-fg/85">{call.path}</span>
      {"  "}
      <span className={TONE[tone]}>{call.status}</span>
      {"  "}
      <span className="text-agent-fg/45">{call.ms}ms</span>
      {call.supplier && <span className="text-agent-fg/35"> · {call.supplier}</span>}
      {fresh && (
        <span
          aria-hidden
          className="type-cover absolute inset-0 border-l-2 border-lime bg-agent-bg"
          style={typing(text)}
        />
      )}
    </li>
  );
}

type TerminalPaneProps = { calls: readonly ApiCall[]; className?: string };

/** The supplier APIs being called, line by line, like a terminal tailing a log. */
export function TerminalPane({ calls, className }: TerminalPaneProps): ReactNode {
  const initial = useRef<number | null>(null);
  if (initial.current === null) initial.current = calls.length;
  const firstFresh = initial.current;
  const scroller = useRef<HTMLDivElement>(null);
  const count = calls.length;

  useEffect(() => {
    const element = scroller.current;
    // `scroll-smooth` on the element animates this (and is off for reduced motion).
    if (element && count > 0) element.scrollTop = element.scrollHeight;
  }, [count]);

  return (
    <section
      aria-label="Supplier API calls"
      className={cn("flex min-h-0 flex-col overflow-hidden rounded-[28px] bg-agent-bg", className)}
    >
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5">
        <span className="ticket-mono text-xs uppercase text-agent-tag">api · suppliers</span>
        <span className="ticket-mono text-xs text-agent-fg/50">{count} calls</span>
      </div>
      <div
        ref={scroller}
        className="ticket-mono h-40 overflow-auto scroll-smooth px-4 motion-reduce:scroll-auto py-3 text-xs leading-6 sm:h-44"
      >
        {count === 0 ? (
          <p className="text-agent-fg/45">
            $ waiting for the first call<span className="caret">▍</span>
          </p>
        ) : (
          <ol aria-label="Calls" className="min-w-max">
            {calls.map((call, index) => (
              <Line
                // biome-ignore lint/suspicious/noArrayIndexKey: an append-only log — a line's position is its identity (two calls can share time and path).
                key={`${call.at}-${call.path}-${index}`}
                call={call}
                fresh={index >= firstFresh}
              />
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
