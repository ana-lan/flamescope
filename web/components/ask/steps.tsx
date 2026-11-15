"use client";

import { Check, Circle, Loader2 } from "lucide-react";
import type { AskEvent } from "@/lib/types";

export type StepItem = {
  key: number;
  label: string;
  detail?: string;
  tool?: string;
  result?: string;
  done: boolean;
};

const TOOL_LABEL: Record<string, string> = {
  query_tests: "Running SQL",
  search_docs: "Searching documents",
  nearest_conditions: "Checking nearest tests",
  get_investigation: "Reading investigation",
};

function argDetail(tool: string, args: Record<string, unknown> | null): string | undefined {
  if (!args) return undefined;
  if (tool === "search_docs" && typeof args.query === "string") return `"${args.query}"`;
  if (tool === "get_investigation" && typeof args.psi_id === "string") return args.psi_id;
  if (tool === "nearest_conditions") {
    if (typeof args.habitat === "string") return args.habitat;
    if (args.pressure_kpa != null) return `${String(args.pressure_kpa)} kPa, O2 ${String(args.o2_frac)}`;
  }
  return undefined;
}

const closeAll = (steps: StepItem[]) => (steps.some((s) => !s.done) ? steps.map((s) => ({ ...s, done: true })) : steps);

// Pure: the same events always give the same steps (live run or cached replay).
export function applyEvent(steps: StepItem[], e: AskEvent): StepItem[] {
  const push = (item: Omit<StepItem, "key" | "done">) => [...closeAll(steps), { ...item, key: steps.length, done: false }];

  switch (e.event) {
    case "status": {
      const d = e.data;
      if (d.stage === "thinking") return push({ label: "Thinking" });
      if (d.stage === "rate_limited") return push({ label: `Waiting for model capacity (${Math.round(d.wait_s)} s)` });
      return push({ label: "Switching model", detail: d.reason });
    }
    case "tool_call":
      return push({
        label: TOOL_LABEL[e.data.tool] ?? e.data.tool,
        detail: argDetail(e.data.tool, e.data.args),
        tool: e.data.tool,
      });
    case "tool_result": {
      let i = -1;
      for (let j = steps.length - 1; j >= 0; j--) {
        if (steps[j].tool === e.data.tool && steps[j].result === undefined) {
          i = j;
          break;
        }
      }
      if (i === -1) return steps;
      return steps.map((s, j) => (j === i ? { ...s, result: e.data.summary, done: true } : s));
    }
    case "token":
    case "final":
    case "error":
      return closeAll(steps);
    default:
      return steps;
  }
}

export function StepList({ steps, running }: { steps: StepItem[]; running: boolean }) {
  return (
    <ol className="space-y-1.5 text-xs">
      {steps.map((s) => (
        <li key={s.key} className="flex items-start gap-2">
          <span className="mt-0.5 shrink-0">
            {s.done ? (
              <Check className="size-3.5 text-success" aria-hidden />
            ) : running ? (
              <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden />
            ) : (
              <Circle className="size-3.5 text-muted-foreground" aria-hidden />
            )}
          </span>
          <span className="min-w-0 break-words">
            <span className="text-foreground/90">{s.label}</span>
            {s.detail && <span className="text-muted-foreground"> {s.detail}</span>}
            {s.result && <span className="num text-muted-foreground"> → {s.result}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}