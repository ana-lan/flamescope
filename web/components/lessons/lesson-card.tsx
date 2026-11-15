"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowRight, MessageSquareText, TriangleAlert } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { insightValue } from "@/lib/format";
import type { Lesson } from "@/lib/lessons";
import type { Insight } from "@/lib/types";

export function LessonCard({ lesson, insights }: { lesson: Lesson; insights?: Insight[] }) {
  const linked = lesson.insightIds
    .map((id) => insights?.find((i) => i.id === id))
    .filter((i): i is Insight => !!i);
  const loading = !insights && lesson.insightIds.length > 0;
  const gap = lesson.insightIds.length === 0;

  return (
    <article className="grid gap-6 border-t py-10 first:border-t-0 first:pt-0 md:grid-cols-[9rem_minmax(0,1fr)]">
      <div className="space-y-1">
        <p className="num text-4xl font-semibold text-primary">{lesson.year}</p>
        <p className="text-xs text-muted-foreground">{lesson.date}</p>
      </div>

      <div className="space-y-6">
        <header className="space-y-2">
          <h2 className="text-2xl font-semibold tracking-tight">{lesson.title}</h2>
          <p className="text-sm text-muted-foreground">{lesson.setting}</p>
          <p className="num inline-block rounded-md border bg-secondary/60 px-2 py-0.5 text-xs">{lesson.atmosphere}</p>
        </header>

        <div className="grid gap-6 sm:grid-cols-2">
          <Block title="What happened">{lesson.happened}</Block>
          <Block title="What changed">{lesson.changed}</Block>
        </div>

        <section
          className={
            gap
              ? "space-y-4 rounded-xl border border-warning/30 bg-warning/5 p-5"
              : "space-y-4 rounded-xl border bg-card p-5"
          }
        >
          <h3 className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-primary">
            {gap && <TriangleAlert className="size-3.5 text-warning" aria-hidden />}
            {gap ? "Outside the ISS data" : "What the ISS data says"}
          </h3>
          <p className="text-sm leading-relaxed text-foreground/85">{lesson.dataSays}</p>

          {loading && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Skeleton className="h-24 rounded-lg" />
              <Skeleton className="h-24 rounded-lg" />
            </div>
          )}

          {linked.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2">
              {linked.map((i) => {
                const v = insightValue(i.value, i.unit);
                return (
                  <Link
                    key={i.id}
                    href={lesson.habitat ? `/?habitat=${lesson.habitat}` : "/"}
                    className="group rounded-lg border bg-background/60 p-4 transition-colors hover:border-primary/60"
                  >
                    <p className="num text-2xl font-semibold text-primary">{v.big}</p>
                    {v.caption && (
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{v.caption}</p>
                    )}
                    <p className="mt-2 text-sm leading-snug">{i.title}</p>
                    <p className="num mt-2 text-[11px] text-muted-foreground">
                      {i.source_psi_ids.join(", ")}
                      <ArrowRight className="ml-1 inline size-3 transition-transform group-hover:translate-x-0.5" aria-hidden />
                    </p>
                  </Link>
                );
              })}
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            {lesson.links.map((l) => (
              <Link key={l.href} href={l.href} className={buttonVariants({ variant: "outline", size: "sm" })}>
                {l.label} <ArrowRight className="size-3.5" aria-hidden />
              </Link>
            ))}
            <Link
              href={`/ask?q=${encodeURIComponent(lesson.ask)}`}
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              <MessageSquareText className="size-3.5" aria-hidden /> Ask IgnitIQ about this
            </Link>
          </div>
        </section>
      </div>
    </article>
  );
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{title}</h3>
      <p className="text-sm leading-relaxed text-foreground/85">{children}</p>
    </div>
  );
}