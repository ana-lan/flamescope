"use client";

import type { ReactNode } from "react";
import { ExternalLink } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { ErrorNote } from "@/components/error-note";
import { OutcomeTag } from "@/components/outcome-tag";
import { useInvestigation } from "@/lib/hooks";
import { fmtNumber, fmtPct, fmtRange } from "@/lib/format";
import type { InvestigationDetail } from "@/lib/types";

export function InvestigationPanel({
  psiId,
  onClose,
  onFilter,
}: {
  psiId: string | null;
  onClose: () => void;
  onFilter?: (psiId: string) => void;
}) {
  const { data, error, mutate } = useInvestigation(psiId);
  const ready = data && data.investigation.psi_id === psiId ? data : null;
  const inv = ready?.investigation;

  return (
    <Sheet
      open={psiId !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <p className="num text-xs text-primary">{psiId}</p>
          <SheetTitle className="text-xl">{inv ? (inv.acronym ?? inv.title) : "Loading investigation"}</SheetTitle>
          {inv && (
            <SheetDescription>
              {inv.acronym ? inv.title : null}
              {inv.mission_name ? `${inv.acronym ? " · " : ""}${inv.mission_name}` : null}
            </SheetDescription>
          )}
        </SheetHeader>

        <div className="space-y-6 px-4 pb-10">
          {error ? (
            <ErrorNote what="this investigation" error={error} onRetry={() => mutate()} />
          ) : !ready ? (
            <div className="space-y-3">
              <Skeleton className="h-8 w-2/3" />
              <Skeleton className="h-20" />
              <Skeleton className="h-40" />
            </div>
          ) : (
            <Body d={ready} onFilter={onFilter} />
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Body({ d, onFilter }: { d: InvestigationDetail; onFilter?: (psiId: string) => void }) {
  const inv = d.investigation;
  const t = d.tests;
  const outcomes = Object.entries(t.outcomes).sort((a, b) => b[1] - a[1]);

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {inv.doi_url && (
          <a
            href={inv.doi_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-md border px-2 py-1 transition-colors hover:border-primary/60"
          >
            <ExternalLink className="size-3" aria-hidden /> doi:{inv.doi}
          </a>
        )}
        <code className="num rounded-md bg-secondary px-2 py-1 text-[11px]">{d.cite_as}</code>
      </div>

      {t.n_rows > 0 ? (
        <>
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Rows" value={fmtNumber(t.n_rows)} />
            <Stat label="Single tests" value={fmtNumber(t.n_single_tests)} />
            <Stat label="Pressure kPa" value={fmtRange(t.p_min_kpa, t.p_max_kpa, fmtNumber)} />
            <Stat label="O2" value={fmtRange(t.o2_min, t.o2_max, (v) => fmtPct(v))} />
          </dl>

          {outcomes.length > 0 && (
            <Section title="Outcomes">
              <div className="flex flex-wrap gap-x-5 gap-y-2">
                {outcomes.map(([o, n]) => (
                  <span key={o} className="flex items-center gap-2">
                    <OutcomeTag outcome={o} />
                    <span className="num text-xs text-muted-foreground">{n}</span>
                  </span>
                ))}
              </div>
            </Section>
          )}

          {t.top_fuels.length > 0 && (
            <Section title="Most-tested fuels">
              <div className="flex flex-wrap gap-1.5">
                {t.top_fuels.map((f) => (
                  <span key={f.fuel} className="rounded-md border bg-secondary/60 px-2 py-0.5 text-xs">
                    {f.fuel} <span className="num text-muted-foreground">{f.n}</span>
                  </span>
                ))}
              </div>
            </Section>
          )}

          {onFilter && (
            <Button size="sm" variant="outline" onClick={() => onFilter(inv.psi_id)}>
              Show only these tests
            </Button>
          )}
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          Ground study with no test table. IgnitIQ uses its write-up as text when answering questions.
        </p>
      )}

      <TextSection title="Objective" text={inv.objective} open />
      <TextSection title="Approach" text={inv.approach} />
      <TextSection title="Hypothesis" text={inv.hypothesis} />
      <TextSection title="Research impacts" text={inv.research_impacts} />

      {d.publications.length > 0 && (
        <Section title={`Publications (${d.publications.length})`}>
          <ul className="space-y-3">
            {d.publications.slice(0, 12).map((p) => (
              <li key={String(p.pub_id)} className="text-sm">
                <p className="leading-snug">
                  {p.doi_url ? (
                    <a href={p.doi_url} target="_blank" rel="noreferrer" className="hover:text-primary">
                      {p.title ?? "Untitled"}
                    </a>
                  ) : (
                    (p.title ?? "Untitled")
                  )}
                </p>
                {p.authors && <p className="truncate text-xs text-muted-foreground">{p.authors}</p>}
              </li>
            ))}
          </ul>
          {d.publications.length > 12 && (
            <p className="mt-2 text-xs text-muted-foreground">and {d.publications.length - 12} more</p>
          )}
        </Section>
      )}
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className="num text-sm">{value}</dd>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

function TextSection({ title, text, open }: { title: string; text?: string | null; open?: boolean }) {
  if (!text) return null;
  return (
    <details open={open} className="group">
      <summary className="cursor-pointer select-none text-xs font-medium uppercase tracking-wider text-muted-foreground hover:text-foreground">
        {title}
      </summary>
      <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-foreground/85">{text}</p>
    </details>
  );
}