import {
  BadgeCheck,
  Circle,
  ExternalLink,
  type LucideIcon,
  MousePointerClick,
  Repeat,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  SquareMousePointer,
  TextCursorInput,
  Timer,
  UserCheck,
  Workflow,
} from "lucide-react";
import type { ReactNode } from "react";

import { Badge, type BadgeTone } from "@/components/ui/badge";

import { SOURCE_LABEL } from "./model";
import type { FlowNodeType, StepSource, StepStatus } from "./schema";

export const NODE_ICON: Record<FlowNodeType, LucideIcon> = {
  open_url: ExternalLink,
  fill: TextCursorInput,
  choose: SquareMousePointer,
  click: MousePointerClick,
  loop: Repeat,
  verify: ScanSearch,
  approve: ShieldCheck,
  extract: Workflow,
  wait: Timer,
  other: Circle,
};

export const NODE_TYPE_LABEL: Record<FlowNodeType, string> = {
  open_url: "open page",
  fill: "fill",
  choose: "choose",
  click: "click",
  loop: "loop",
  verify: "verify",
  approve: "approval",
  extract: "read page",
  wait: "wait",
  other: "step",
};

const SOURCE_TONE: Record<StepSource, BadgeTone> = {
  flow: "sky",
  rule: "neutral",
  llm: "blush",
  human: "lime",
};
const SOURCE_ICON: Record<StepSource, LucideIcon> = {
  flow: Repeat,
  rule: BadgeCheck,
  llm: Sparkles,
  human: UserCheck,
};
const SOURCE_TITLE: Record<StepSource, string> = {
  flow: "Replayed from a recorded flow, no LLM call",
  rule: "Decided by a deterministic rule, no LLM call",
  llm: "Decided by the LLM planner",
  human: "Decided by a person",
};

/** Where a step's decision came from: "replay", "rule" or "AI". */
export function SourceChip({ source }: { source: StepSource }): ReactNode {
  const Icon = SOURCE_ICON[source];
  return (
    <Badge tone={SOURCE_TONE[source]} title={SOURCE_TITLE[source]} data-source={source}>
      <Icon className="size-3" aria-hidden />
      {SOURCE_LABEL[source]}
    </Badge>
  );
}

export const STATUS_LABEL: Record<StepStatus, string> = {
  pending: "waiting",
  running: "running",
  done: "done",
  failed: "failed",
  healed: "healed",
};

export const STATUS_TONE: Record<StepStatus, BadgeTone> = {
  pending: "outline",
  running: "lime",
  done: "success",
  failed: "danger",
  healed: "blush",
};
