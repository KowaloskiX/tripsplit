import { Check, X } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { formatDuration, type NodeState } from "./model";
import type { FlowNode, StepStatus } from "./schema";
import { NODE_ICON, NODE_TYPE_LABEL, SourceChip, STATUS_LABEL, STATUS_TONE } from "./step-chips";

const DOT: Record<StepStatus, string> = {
  pending: "border-2 border-dashed border-line bg-surface text-muted",
  running: "halo bg-lime text-pastel-ink",
  done: "bg-ink text-bg",
  failed: "bg-danger-soft text-danger ring-1 ring-danger/40",
  healed: "bg-pastel-blush text-pastel-ink",
};

const CARD: Record<StepStatus, string> = {
  pending: "border-dashed border-line bg-surface/60",
  running: "border-ink bg-surface shadow-pop",
  done: "border-line bg-surface",
  failed: "border-danger/50 bg-danger-soft/50",
  healed: "border-line bg-surface",
};

/** Settled connector colour: the line below a node fills once the run has passed it. */
const LINE: Record<StepStatus, string> = {
  pending: "scale-y-0",
  running: "scale-y-50 bg-lime",
  done: "scale-y-100 bg-ink",
  failed: "scale-y-0",
  healed: "scale-y-100 bg-ink",
};

function StatusDot({
  node,
  status,
  small,
}: {
  node: FlowNode;
  status: StepStatus;
  small?: boolean;
}): ReactNode {
  const Icon = status === "done" ? Check : status === "failed" ? X : NODE_ICON[node.type];
  return (
    <span
      key={status}
      className={cn(
        "relative z-10 inline-flex shrink-0 items-center justify-center rounded-full transition duration-150",
        small ? "size-7" : "size-10",
        status !== "pending" && status !== "running" && "settle",
        DOT[status],
      )}
    >
      <Icon
        className={small ? "size-3.5" : "size-[18px]"}
        strokeWidth={status === "done" ? 3 : 2}
        aria-hidden
      />
    </span>
  );
}

function Inputs({ inputs }: { inputs: readonly string[] }): ReactNode {
  return (
    <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Reads">
      {inputs.map((input) => (
        <li
          key={input}
          className="ticket-mono rounded-full bg-surface-sunken px-2 py-0.5 text-[11px] text-muted"
        >
          {input}
        </li>
      ))}
    </ul>
  );
}

function Meta({ state }: { state: NodeState }): ReactNode {
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-1.5 sm:justify-end">
      {state.source && <SourceChip source={state.source} />}
      {state.status !== "done" && (
        <Badge tone={STATUS_TONE[state.status]} pulse={state.status === "running"}>
          {STATUS_LABEL[state.status]}
        </Badge>
      )}
      {state.durationMs > 0 && (
        <span className="ticket-mono text-xs text-muted sm:w-14 sm:text-right">
          {formatDuration(state.durationMs)}
        </span>
      )}
    </div>
  );
}

type PipelineNodeProps = {
  node: FlowNode;
  state: NodeState;
  last: boolean;
  /** Body rows of a loop, rendered inside its card. */
  children?: ReactNode;
};

/** One row of the pipeline: a status dot on the rail, the step card next to it. */
export function PipelineNode({ node, state, last, children }: PipelineNodeProps): ReactNode {
  return (
    <li
      data-node-id={node.id}
      data-status={state.status}
      aria-current={state.status === "running" ? "step" : undefined}
      className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-x-3 sm:gap-x-4"
    >
      <div className="flex flex-col items-center">
        <StatusDot node={node} status={state.status} />
        {!last && (
          <span
            aria-hidden
            className="relative my-1 w-0.5 flex-1 overflow-hidden rounded-full bg-line"
          >
            <span className={cn("flow-fill absolute inset-0 rounded-full", LINE[state.status])} />
            {/* While this step runs, a glow travels down the edge towards the next one. */}
            {state.status === "running" && (
              <span className="edge-travel absolute inset-0">
                <span className="block h-2/5 w-full rounded-full bg-gradient-to-b from-transparent via-lime to-transparent" />
              </span>
            )}
          </span>
        )}
      </div>
      <div
        className={cn(
          "mb-4 rounded-[24px] border px-4 py-3.5 transition duration-150 sm:px-5",
          CARD[state.status],
        )}
      >
        <div className="flex flex-col gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
          <div className="min-w-0">
            <p className="eyebrow text-[11px]">{NODE_TYPE_LABEL[node.type]}</p>
            <p
              className={cn(
                "mt-0.5 text-base font-medium leading-snug tracking-[-0.01em]",
                state.status === "pending" ? "text-muted" : "text-ink",
              )}
            >
              {node.label}
            </p>
          </div>
          <Meta state={state} />
        </div>
        {node.inputs && node.inputs.length > 0 && <Inputs inputs={node.inputs} />}
        {children}
      </div>
    </li>
  );
}

type LoopBodyProps = {
  node: FlowNode;
  state: NodeState;
  body: { node: FlowNode; state: NodeState }[];
};

/** "× 3 passengers" with a dot per iteration, then the repeated steps, indented. */
export function LoopBody({ node, state, body }: LoopBodyProps): ReactNode {
  const planned = node.iterations ?? 0;
  const unit = node.iteration_label ?? "time";
  return (
    <div className="mt-3 space-y-2.5">
      {planned > 0 && (
        <div className="flex items-center gap-2.5">
          <Badge tone="sky" className="text-[13px]">
            × {planned} {planned === 1 ? unit : `${unit}s`}
          </Badge>
          <ol
            className="flex items-center gap-1"
            aria-label={`${state.iterationsDone} of ${planned} ${unit}s done`}
          >
            {Array.from({ length: planned }, (_, index) => {
              const done = index < state.iterationsDone;
              const current = index === state.iterationsDone && state.status === "running";
              return (
                <li
                  // biome-ignore lint/suspicious/noArrayIndexKey: iterations have no identity beyond their position.
                  key={index}
                  className={cn(
                    "size-2.5 rounded-full transition duration-150",
                    done ? "bg-ink" : current ? "halo bg-lime" : "bg-line",
                  )}
                />
              );
            })}
          </ol>
          <span className="ticket-mono text-xs text-muted">
            {state.iterationsDone}/{planned}
          </span>
        </div>
      )}
      <ol
        className="space-y-2 rounded-[20px] bg-surface-sunken p-2.5"
        aria-label={`Repeated for each ${unit}`}
      >
        {body.map(({ node: child, state: childState }) => (
          <li
            key={child.id}
            className="flex items-center gap-3"
            data-node-id={child.id}
            data-status={childState.status}
          >
            <StatusDot node={child} status={childState.status} small />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-ink">{child.label}</p>
              {child.inputs && (
                <p className="hidden break-all font-mono text-[11px] text-muted sm:block">
                  {child.inputs.join(" · ")}
                </p>
              )}
            </div>
            {childState.source && <SourceChip source={childState.source} />}
          </li>
        ))}
      </ol>
    </div>
  );
}
