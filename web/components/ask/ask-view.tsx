"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowUp, History, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TurnView, type Turn } from "@/components/ask/turn-view";
import { WorkDrawer } from "@/components/ask/work-drawer";
import { applyEvent } from "@/components/ask/steps";
import { askStream } from "@/lib/sse";
import { ApiError } from "@/lib/api";
import { useSuggested } from "@/lib/hooks";
import { HABITAT_SHORT, isHabitatSlug } from "@/lib/format";
import { cn } from "@/lib/utils";
import { HABITAT_SLUGS, type AskFinal, type HabitatSlug, type Suggested } from "@/lib/types";

const MIN = 3;
const MAX = 500;

export function AskView() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const raw = params.get("habitat");
  const habitat: HabitatSlug | null = isHabitatSlug(raw) ? raw : null;
  const setHabitat = (slug: HabitatSlug | null) =>
    router.replace(slug ? `${pathname}?habitat=${slug}` : pathname, { scroll: false });

  const [input, setInput] = useState(() => params.get("q") ?? "");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [work, setWork] = useState<AskFinal | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const nextId = useRef(1);
  const bottomRef = useRef<HTMLDivElement>(null);

  const suggested = useSuggested(habitat);
  const running = turns.some((t) => t.status === "running");
  const last = turns[turns.length - 1];

  useEffect(() => () => controllerRef.current?.abort(), []);
  useEffect(() => {
    if (turns.length) bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, last?.status]);

  const update = (id: number, fn: (t: Turn) => Turn) => setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)));

  async function ask(question: string, h: HabitatSlug | null) {
    const q = question.trim();
    if (q.length < MIN || q.length > MAX || running) return;

    const id = nextId.current++;
    setTurns((ts) => [...ts, { id, question: q, habitat: h, steps: [], text: "", status: "running" }]);
    setInput("");
    const controller = new AbortController();
    controllerRef.current = controller;

    try {
      const final = await askStream(
        { question: q, habitat: h },
        {
          signal: controller.signal,
          onEvent: (e) =>
            update(id, (t) => ({
              ...t,
              steps: applyEvent(t.steps, e),
              text: e.event === "token" ? t.text + e.data.text : t.text,
            })),
        },
      );
      // final.answer is the source of truth; tokens were the live preview
      update(id, (t) => ({ ...t, final, text: final.answer, status: "done" }));
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError("server", "Something went wrong.");
      update(id, (t) => ({
        ...t,
        error: err,
        status: err.kind === "aborted" ? "stopped" : "error",
        steps: t.steps.map((s) => ({ ...s, done: true })),
      }));
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }

  // A recorded answer replays only if question AND habitat match, so suggestions send their own habitat.
  const askSuggested = (s: Suggested) => ask(s.question, s.habitat);

  const len = input.trim().length;
  const canSend = !running && len >= MIN && len <= MAX;

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <HabitatPicker value={habitat} onChange={setHabitat} disabled={running} />

      {turns.length === 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">Try a question with a recorded answer</h2>
          {!suggested.data ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-16 rounded-lg" />
              ))}
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {suggested.data.map((s) => (
                <button
                  key={s.question + s.habitat}
                  type="button"
                  onClick={() => askSuggested(s)}
                  className="rounded-lg border bg-card p-3 text-left text-sm transition-colors hover:border-primary/60"
                >
                  {s.question}
                  {s.habitat && (
                    <span className="ml-2 rounded-full border px-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                      {HABITAT_SHORT[s.habitat]}
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      {turns.map((t) => (
        <TurnView key={t.id} turn={t} onOpenWork={setWork} />
      ))}
      <div ref={bottomRef} />

      <form
        className="sticky bottom-0 z-10 -mx-4 space-y-2 border-t bg-background/90 px-4 pb-4 pt-3 backdrop-blur"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSend) ask(input, habitat);
        }}
      >
        {turns.length > 0 && suggested.data && suggested.data.length > 0 && (
          <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none]">
            {suggested.data.map((s) => (
              <button
                key={s.question + s.habitat}
                type="button"
                disabled={running}
                onClick={() => askSuggested(s)}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
              >
                <History className="size-3" aria-hidden /> {s.question}
              </button>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2 rounded-xl border bg-card p-2 focus-within:border-primary/60">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (canSend) ask(input, habitat);
              }
            }}
            rows={2}
            maxLength={MAX}
            placeholder={
              habitat
                ? `Ask about fire safety in the ${HABITAT_SHORT[habitat]} atmosphere`
                : "Ask about the ISS fire experiments"
            }
            className="max-h-40 min-h-[2.75rem] flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground"
            aria-label="Your question"
          />
          {running ? (
            <Button type="button" size="icon" variant="outline" onClick={() => controllerRef.current?.abort()} aria-label="Stop">
              <Square className="size-4" aria-hidden />
            </Button>
          ) : (
            <Button type="submit" size="icon" disabled={!canSend} aria-label="Ask">
              <ArrowUp className="size-4" aria-hidden />
            </Button>
          )}
        </div>
        <p className="flex justify-between text-[11px] text-muted-foreground">
          <span>Suggested questions replay recorded answers. New questions run live on free models.</span>
          <span className={cn("num", len > MAX && "text-destructive")}>
            {len}/{MAX}
          </span>
        </p>
      </form>

      <WorkDrawer final={work} onClose={() => setWork(null)} />
    </div>
  );
}

function HabitatPicker({
  value,
  onChange,
  disabled,
}: {
  value: HabitatSlug | null;
  onChange: (v: HabitatSlug | null) => void;
  disabled: boolean;
}) {
  const options: (HabitatSlug | null)[] = [null, ...HABITAT_SLUGS];
  return (
    <div role="radiogroup" aria-label="Habitat for new questions" className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-xs text-muted-foreground">Habitat</span>
      {options.map((slug) => {
        const selected = slug === value;
        return (
          <button
            key={slug ?? "any"}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(slug)}
            className={cn(
              "rounded-md border px-2.5 py-1 text-xs transition-colors disabled:opacity-50",
              selected ? "border-primary bg-primary/15 text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {slug ? HABITAT_SHORT[slug] : "Any"}
          </button>
        );
      })}
    </div>
  );
}