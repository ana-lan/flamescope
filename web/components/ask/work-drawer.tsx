"use client";

import type { ReactNode } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { fmtSeconds } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AskFinal, SqlRun } from "@/lib/types";

const PRE = "num overflow-x-auto whitespace-pre-wrap rounded-md border bg-background p-3 text-[11px] leading-relaxed";

const SOURCE_TYPE: Record<string, string> = {
  investigation: "Investigation",
  abstract: "Paper abstract",
  context: "NASA document",
  figure_index: "Figure index",
};

function cell(v: unknown): string {
  if (v == null) return "·";
  if (typeof v === "number") return v.toLocaleString("en-US", { maximumFractionDigits: 4 });
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function WorkDrawer({ final, onClose }: { final: AskFinal | null; onClose: () => void }) {
  return (
    <Sheet
      open={final !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>How I got this</SheetTitle>
          <SheetDescription>{final?.question}</SheetDescription>
        </SheetHeader>
        {final && <Body f={final} />}
      </SheetContent>
    </Sheet>
  );
}

function Body({ f }: { f: AskFinal }) {
  const tokens = (f.usage.prompt_tokens ?? 0) + (f.usage.completion_tokens ?? 0);
  return (
    <div className="space-y-8 px-4 pb-10">
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <Meta label="Answer" value={f.cached ? "Recorded" : "Live"} />
        <Meta label="Model" value={f.model?.split(":").slice(1).join(":") || "n/a"} />
        <Meta label="LLM calls" value={String(f.llm_calls)} />
        <Meta label="Time" value={fmtSeconds(f.elapsed_s)} />
        {tokens > 0 && <Meta label="Tokens" value={tokens.toLocaleString()} />}
        {f.cached_at && <Meta label="Recorded at" value={f.cached_at} />}
      </dl>

      <Section title={`SQL that ran (${f.sql_run.length})`}>
        {f.sql_run.length === 0 ? (
          <Empty>No SQL ran for this answer.</Empty>
        ) : (
          f.sql_run.map((run, i) => <SqlCard key={i} run={run} n={i + 1} />)
        )}
      </Section>

      <Section title={`Number checks (${f.grounding.numbers.length})`}>
        {f.grounding.numbers.length === 0 ? (
          <Empty>The answer has no numbers to check.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="py-1 pr-3 font-medium">Number</th>
                  <th className="py-1 pr-3 font-medium">Cited</th>
                  <th className="py-1 pr-3 font-medium">Found in</th>
                  <th className="py-1 font-medium">Check</th>
                </tr>
              </thead>
              <tbody>
                {f.grounding.numbers.map((n, i) => (
                  <tr key={i} className="border-t border-border/60">
                    <td className="num py-1 pr-3">{n.value}</td>
                    <td className="num py-1 pr-3">{n.cited.join(", ") || "·"}</td>
                    <td className="num py-1 pr-3">{n.source ?? "not found"}</td>
                    <td className={cn("py-1", n.ok ? "text-success" : "text-warning")}>{n.ok ? "ok" : "check"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title={`Passages read (${f.passages.length})`}>
        {f.passages.length === 0 ? (
          <Empty>No documents were searched for this answer.</Empty>
        ) : (
          <ul className="space-y-3">
            {f.passages.map((p) => {
              const href = p.url ?? (p.doi ? `https://doi.org/${p.doi}` : null);
              return (
                <li key={p.chunk_id} className="space-y-1 rounded-lg border p-3">
                  <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
                    <span className="text-primary">{SOURCE_TYPE[p.source_type] ?? p.source_type}</span>
                    {(p.experiment ?? p.psi_id) && <span className="num">{p.experiment ?? p.psi_id}</span>}
                    {p.field && <span>{p.field}</span>}
                    <span className="num ml-auto">score {p.score.toFixed(2)}</span>
                  </div>
                  {p.title &&
                    (href ? (
                      <a href={href} target="_blank" rel="noreferrer" className="text-sm font-medium hover:text-primary">
                        {p.title}
                      </a>
                    ) : (
                      <p className="text-sm font-medium">{p.title}</p>
                    ))}
                  <p className="text-xs leading-relaxed text-foreground/75">{p.text}</p>
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      {f.llm_trace.length > 0 && (
        <Section title="Model attempts">
          <ul className="space-y-1 text-xs">
            {f.llm_trace.map((t, i) => (
              <li key={i} className="num flex flex-wrap gap-x-3">
                <span className={t.ok ? "text-success" : "text-warning"}>{t.ok ? "ok" : "failed"}</span>
                <span>{t.model}</span>
                {t.latency_s != null && <span className="text-muted-foreground">{fmtSeconds(t.latency_s)}</span>}
                {t.prompt_tokens != null && (
                  <span className="text-muted-foreground">
                    {t.prompt_tokens}+{t.completion_tokens ?? 0} tok
                  </span>
                )}
                {t.error && (
                  <span className="text-warning">
                    {t.error}
                    {t.kind ? ` (${t.kind})` : ""}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function SqlCard({ run, n }: { run: SqlRun; n: number }) {
  const cols = run.columns ?? [];
  const shown = run.rows.slice(0, 10);
  return (
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>Query {n}</span>
        <span className="num">
          {run.row_count ?? run.rows.length} rows{run.truncated ? " (capped)" : ""}
        </span>
      </div>
      {run.auto_fixed && run.auto_fixed.length > 0 && (
        <p className="text-xs text-warning">Auto-fixed by IgnitIQ: {run.auto_fixed.join("; ")}</p>
      )}
      {run.sql && <pre className={PRE}>{run.sql.trim()}</pre>}
      {run.original_sql && (
        <details className="text-xs">
          <summary className="cursor-pointer select-none text-muted-foreground hover:text-foreground">
            The model&apos;s original query
          </summary>
          <pre className={cn(PRE, "mt-2 opacity-80")}>{run.original_sql.trim()}</pre>
        </details>
      )}
      {run.error && <p className="text-xs text-destructive">{run.error}</p>}
      {cols.length > 0 && shown.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-muted-foreground">
                {cols.map((c) => (
                  <th key={c} className="num py-1 pr-3 font-medium">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((row, i) => (
                <tr key={i} className="border-t border-border/60">
                  {row.map((v, j) => (
                    <td key={j} className="num max-w-[16rem] truncate py-1 pr-3">
                      {cell(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {run.rows.length > shown.length && (
            <p className="mt-1 text-[11px] text-muted-foreground">and {run.rows.length - shown.length} more rows</p>
          )}
        </div>
      )}
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className="num break-words text-sm">
        {value}
      </dd>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}