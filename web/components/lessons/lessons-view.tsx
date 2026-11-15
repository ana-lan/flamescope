"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { ErrorNote } from "@/components/error-note";
import { LessonCard } from "@/components/lessons/lesson-card";
import { useInsights } from "@/lib/hooks";
import { insightValue } from "@/lib/format";
import { LESSONS } from "@/lib/lessons";

export function LessonsView() {
  // null = every insight, not filtered by habitat
  const insights = useInsights(null);
  const gap = insights.data?.find((i) => i.id === "coverage_gap");

  return (
    <div className="space-y-10">
      {insights.error && <ErrorNote what="the linked findings" error={insights.error} onRetry={() => insights.mutate()} />}

      <div>
        {LESSONS.map((l) => (
          <LessonCard key={l.id} lesson={l} insights={insights.data} />
        ))}
      </div>

      <section className="space-y-4 rounded-xl border border-primary/30 bg-primary/5 p-6">
        <p className="num text-xs uppercase tracking-[0.2em] text-primary">The pattern</p>
        <h2 className="text-xl font-semibold tracking-tight">
          Every one of these fires involved oxygen. The next habitats will run richer in it.
        </h2>
        <p className="max-w-3xl text-sm leading-relaxed text-foreground/85">
          NASA&apos;s proposed lunar and Mars surface habitats use 34% oxygen at 8.2 psia, so the crew can breathe at
          lower pressure and spacewalk with less prebreathe. That is exactly where the ISS fire data is thinnest
          {gap ? (
            <>
              : <span className="num font-semibold text-primary">{insightValue(gap.value, gap.unit).big}</span> fewer
              tests than near ISS conditions.
            </>
          ) : (
            "."
          )}
        </p>
        <Link href="/?habitat=lunar" className={buttonVariants({ size: "sm" })}>
          See the lunar habitat brief <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      </section>
    </div>
  );
}