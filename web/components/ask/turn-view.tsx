"use client";

import { FileSearch, Loader2, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SourceChip } from "@/components/source-chip";
import { AnswerMarkdown } from "@/components/ask/answer-markdown";
import { StepList, type StepItem } from "@/components/ask/steps";
import { ApiError } from "@/lib/api";
import { fmtSeconds, HABITAT_SHORT } from "@/lib/format";
import type { AskFinal, HabitatSlug } from "@/lib/types";

export type Turn = {
  id: number;
  question: string;
  habitat: HabitatSlug | null;
  steps: StepItem[];
  text: string;
  status: "running" | "done" | "error" | "stopped";
  final?: AskFinal;
  error?: ApiError;
};

export function TurnView({ turn, onOpenWork }: { turn: Turn; onOpenWork: (f: AskFinal) => void }) {
  const f = turn.final;
  const running = turn.status === "running";
  const added = new Set(f?.citations_added?.map((c) => c.id) ?? []);
  const badNumbers = f?.grounding.numbers.filter((n) => !n.ok) ?? [];
  const badCites = f?.citations.filter((c) => !c.verified) ?? [];
  const goodCites = f?.citations.filter((c) => c.verified) ?? [];

  return (
    <article className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <p className="text-lg font-medium leading-snug">{turn.question}</p>
        {turn.habitat && (
          <span className="rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">
            {HABITAT_SHORT[turn.habitat]}
          </span>
        )}
      </div>

      <div className="space-y-4 rounded-xl border bg-card p-5">
        {turn.steps.length > 0 &&
          (f ? (
            <details className="text-xs">
              <summary className="cursor-pointer select-none text-muted-foreground hover:text-foreground">
                {turn.steps.length} steps · {fmtSeconds(f.elapsed_s)}
              </summary>
              <div className="mt-2">
                <StepList steps={turn.steps} running={false} />
              </div>
            </details>
          ) : (
            <StepList steps={turn.steps} running={running} />
          ))}

        {running && turn.steps.length === 0 && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden /> Connecting
          </p>
        )}

        {turn.text && (
          <div>
            <AnswerMarkdown text={turn.text} citations={f?.citations} added={added} />
            {running && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-primary align-middle" aria-hidden />}
          </div>
        )}

        {f?.answer_truncated && (
          <p className="text-xs text-muted-foreground">The answer hit its length limit and was cut short.</p>
        )}

        {(badNumbers.length > 0 || badCites.length > 0) && (
          <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-warning">
            <p className="flex items-center gap-2 text-sm font-medium">
              <TriangleAlert className="size-4" aria-hidden /> Check these before relying on them
            </p>
            <ul className="mt-1 space-y-0.5 text-xs">
              {badNumbers.map((n, i) => (
                <li key={`n${i}`}>
                  <span className="num">{n.value}</span>:{" "}
                  {n.source ? `found in ${n.source}, which this sentence does not cite` : "not found in any tool result"}
                </li>
              ))}
              {badCites.map((c) => (
                <li key={c.id}>
                  <span className="num">{c.id}</span>: cited, but no tool returned it
                </li>
              ))}
            </ul>
          </div>
        )}

        {turn.error && <TurnError error={turn.error} stopped={turn.status === "stopped"} />}

        {f && (
          <div className="space-y-3 border-t pt-4">
            {goodCites.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {goodCites.map((c) => (
                  <SourceChip key={c.id} source={{ psi_id: c.id, acronym: c.label, title: c.title, doi_url: c.url }} />
                ))}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted-foreground">
              <span
                className={
                  f.cached
                    ? "rounded-full border px-2 py-0.5"
                    : "rounded-full border border-success/40 bg-success/10 px-2 py-0.5 text-success"
                }
                title={f.cached_at ? `Recorded ${f.cached_at}` : undefined}
              >
                {f.cached ? "Recorded answer" : "Live answer"}
              </span>
              {f.model && <span className="num">{f.model.split(":").slice(1).join(":")}</span>}
              <span className="num">{fmtSeconds(f.elapsed_s)}</span>
              <Button size="sm" variant="outline" className="ml-auto" onClick={() => onOpenWork(f)}>
                <FileSearch className="size-4" aria-hidden /> How I got this
              </Button>
            </div>
          </div>
        )}
      </div>
    </article>
  );
}

function TurnError({ error, stopped }: { error: ApiError; stopped: boolean }) {
  if (stopped) return <p className="text-sm text-muted-foreground">Stopped.</p>;
  const hint =
    error.kind === "busy" || error.kind === "stream" || error.kind === "unavailable"
      ? " Try one of the suggested questions: they replay recorded answers instantly."
      : "";
  return (
    <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
      {error.message}
      {hint}
    </p>
  );
}