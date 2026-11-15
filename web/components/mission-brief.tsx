"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { MessageSquareText } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorNote } from "@/components/error-note";
import { SectionTitle } from "@/components/section-title";
import { HabitatSelector } from "@/components/habitat-selector";
import { InsightCard } from "@/components/insight-card";
import { CoveragePanel } from "@/components/coverage-panel";
import { useCoverage, useHabitats, useInsights } from "@/lib/hooks";
import { DEFAULT_HABITAT, isHabitatSlug, VERDICT } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { HabitatSlug } from "@/lib/types";

export function MissionBrief() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const raw = params.get("habitat");
  const habitat: HabitatSlug = isHabitatSlug(raw) ? raw : DEFAULT_HABITAT;
  const setHabitat = (slug: HabitatSlug) => router.replace(`${pathname}?habitat=${slug}`, { scroll: false });

  const habitats = useHabitats();
  const insights = useInsights(habitat);
  const coverage = useCoverage(habitat);
  const selected = habitats.data?.find((h) => h.slug === habitat);

  return (
    <div className="space-y-12">
      {/* 1. habitat */}
      <section aria-labelledby="habitat">
        <SectionTitle title="Pick a habitat atmosphere" hint="Lower pressure needs more oxygen to keep the crew breathing. That changes how fires behave.">
          <Link href={`/ask?habitat=${habitat}`} className={buttonVariants({ variant: "outline", size: "sm" })}>
            <MessageSquareText className="size-4" aria-hidden /> Ask about this habitat
          </Link>
        </SectionTitle>

        {habitats.error ? (
          <ErrorNote what="habitats" error={habitats.error} onRetry={() => habitats.mutate()} />
        ) : !habitats.data ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-32 rounded-xl" />
            ))}
          </div>
        ) : (
          <HabitatSelector habitats={habitats.data} value={habitat} onChange={setHabitat} />
        )}

        <div className="mt-4 space-y-2 text-sm">
          {coverage.data && coverage.data.habitat.slug === habitat && (
            <p className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-xs font-medium",
                  VERDICT[coverage.data.summary.verdict].className,
                )}
              >
                {VERDICT[coverage.data.summary.verdict].label}
              </span>
              <span className="text-muted-foreground">{coverage.data.summary.note}</span>
            </p>
          )}
          {selected?.note && (
            <p className="text-xs text-muted-foreground">
              {selected.note}
              {selected.source_url && (
                <>
                  {" "}
                  <a href={selected.source_url} target="_blank" rel="noreferrer" className="underline underline-offset-4 hover:text-foreground">
                    Source
                  </a>
                </>
              )}
            </p>
          )}
        </div>
      </section>

      {/* 2. insights */}
      <section aria-labelledby="insights">
        <SectionTitle
          title="What the ISS fire tests found"
          hint="Each number is computed with SQL from the test tables. Open a card to see the query."
        />
        {insights.error ? (
          <ErrorNote what="insights" error={insights.error} onRetry={() => insights.mutate()} />
        ) : !insights.data ? (
          <div className="grid gap-4 md:grid-cols-2">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-64 rounded-xl" />
            ))}
          </div>
        ) : insights.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">No findings are tagged for this atmosphere yet.</p>
        ) : (
          <div className={cn("grid gap-4 transition-opacity md:grid-cols-2", insights.isValidating && "opacity-60")}>
            {insights.data.map((i) => (
              <InsightCard key={i.id} insight={i} />
            ))}
          </div>
        )}
      </section>

      {/* 3. coverage */}
      <section aria-labelledby="coverage">
        <SectionTitle
          title="Where the data runs out"
          hint="Every ISS test with a recorded pressure and oxygen level. The dashed box is the habitat's neighborhood."
        />
        {coverage.error ? (
          <ErrorNote what="coverage" error={coverage.error} onRetry={() => coverage.mutate()} />
        ) : !coverage.data ? (
          <Skeleton className="h-[34rem] rounded-xl" />
        ) : (
          <div className={cn("transition-opacity", coverage.isValidating && "opacity-60")}>
            <CoveragePanel coverage={coverage.data} />
          </div>
        )}
      </section>
    </div>
  );
}

export function MissionBriefSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-32 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-64 rounded-xl" />
    </div>
  );
}