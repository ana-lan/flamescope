"use client";

import type { ReactNode } from "react";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { fmtNumber, OUTCOME_ORDER, outcomeColor, outcomeLabel } from "@/lib/format";
import type { Facets, TestsQuery } from "@/lib/types";

export type Filters = {
  experiments: string[];
  outcomes: string[];
  fuel: string;
  pMin: string; // kPa, kept as text so a half-typed number doesn't fight the input
  pMax: string;
  o2Min: string; // percent in the UI, fraction in the API
  o2Max: string;
  includeSummary: boolean;
};

export const EMPTY_FILTERS: Filters = {
  experiments: [],
  outcomes: [],
  fuel: "",
  pMin: "",
  pMax: "",
  o2Min: "",
  o2Max: "",
  includeSummary: false,
};

function num(s: string): number | undefined {
  if (s.trim() === "") return undefined;
  const n = Number(s);
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}

const pctToFrac = (v: number | undefined) => (v == null ? undefined : Math.min(v, 100) / 100);

export function toQuery(f: Filters): TestsQuery {
  return {
    experiment: f.experiments.length ? f.experiments : undefined,
    outcome: f.outcomes.length ? f.outcomes : undefined,
    fuel: f.fuel.trim() || undefined,
    p_min: num(f.pMin),
    p_max: num(f.pMax),
    o2_min: pctToFrac(num(f.o2Min)),
    o2_max: pctToFrac(num(f.o2Max)),
    single_only: f.includeSummary ? undefined : true,
  };
}

export function activeCount(f: Filters): number {
  return (
    f.experiments.length +
    f.outcomes.length +
    [f.fuel, f.pMin, f.pMax, f.o2Min, f.o2Max].filter((s) => s.trim() !== "").length +
    (f.includeSummary ? 1 : 0)
  );
}

export function FilterPanel({
  facets,
  value,
  onChange,
}: {
  facets?: Facets;
  value: Filters;
  onChange: (f: Filters) => void;
}) {
  const set = (patch: Partial<Filters>) => onChange({ ...value, ...patch });
  const toggle = (key: "experiments" | "outcomes", item: string) => {
    const cur = value[key];
    set({ [key]: cur.includes(item) ? cur.filter((x) => x !== item) : [...cur, item] });
  };
  const r = facets?.ranges;
  const rank = (o: string) => {
    const i = (OUTCOME_ORDER as readonly string[]).indexOf(o);
    return i === -1 ? 99 : i;
  };

  return (
    <div className="space-y-6">
      <Group label="Experiment">
        {facets ? (
          <div className="flex flex-wrap gap-1.5">
            {[...facets.experiments]
              .sort((a, b) => b.n - a.n)
              .map((e) => (
                <Chip
                  key={e.experiment}
                  pressed={value.experiments.includes(e.experiment)}
                  onClick={() => toggle("experiments", e.experiment)}
                  title={e.psi_id}
                >
                  {e.experiment} <span className="num opacity-60">{e.n}</span>
                </Chip>
              ))}
          </div>
        ) : (
          <Skeleton className="h-28" />
        )}
      </Group>

      <Group label="Outcome" hint="Recorded for FLEX droplets and CFI-G gas jets">
        {facets ? (
          <div className="flex flex-wrap gap-1.5">
            {[...facets.outcomes]
              .sort((a, b) => rank(a.outcome) - rank(b.outcome))
              .map((o) => (
                <Chip key={o.outcome} pressed={value.outcomes.includes(o.outcome)} onClick={() => toggle("outcomes", o.outcome)}>
                  <span className="size-2 rounded-full" style={{ background: outcomeColor(o.outcome) }} aria-hidden />
                  {outcomeLabel(o.outcome)} <span className="num opacity-60">{o.n}</span>
                </Chip>
              ))}
          </div>
        ) : (
          <Skeleton className="h-16" />
        )}
      </Group>

      <Group label="Fuel or material">
        <Input
          value={value.fuel}
          onChange={(e) => set({ fuel: e.target.value })}
          placeholder="heptane, methanol, cotton"
          list="fuel-options"
          className="h-8 text-sm"
        />
        <datalist id="fuel-options">
          {facets?.fuels.map((f) => <option key={f.fuel} value={f.fuel} />)}
        </datalist>
      </Group>

      <Group label="Pressure (kPa)">
        <RangeInputs
          min={value.pMin}
          max={value.pMax}
          onMin={(v) => set({ pMin: v })}
          onMax={(v) => set({ pMax: v })}
          phMin={r?.p_min != null ? fmtNumber(r.p_min) : "min"}
          phMax={r?.p_max != null ? fmtNumber(r.p_max) : "max"}
        />
      </Group>

      <Group label="O2 (%)">
        <RangeInputs
          min={value.o2Min}
          max={value.o2Max}
          onMin={(v) => set({ o2Min: v })}
          onMax={(v) => set({ o2Max: v })}
          phMin={r?.o2_min != null ? fmtNumber(r.o2_min * 100) : "min"}
          phMax={r?.o2_max != null ? fmtNumber(r.o2_max * 100) : "max"}
        />
      </Group>

      <label className="flex cursor-pointer items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={value.includeSummary}
          onChange={(e) => set({ includeSummary: e.target.checked })}
          className="size-4 accent-primary"
        />
        Include summary rows <span className="text-xs text-muted-foreground">(test-day and fuel totals)</span>
      </label>
    </div>
  );
}

function Group({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
        {hint && <p className="text-[11px] text-muted-foreground/70">{hint}</p>}
      </div>
      {children}
    </div>
  );
}

function Chip({
  pressed,
  onClick,
  title,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  title?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      title={title}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors",
        pressed
          ? "border-primary bg-primary/15 text-foreground"
          : "text-muted-foreground hover:border-foreground/25 hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function RangeInputs({
  min,
  max,
  onMin,
  onMax,
  phMin,
  phMax,
}: {
  min: string;
  max: string;
  onMin: (v: string) => void;
  onMax: (v: string) => void;
  phMin: string;
  phMax: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <Input type="number" inputMode="decimal" step="any" min={0} value={min} onChange={(e) => onMin(e.target.value)} placeholder={phMin} aria-label="minimum" className="num h-8 text-sm" />
      <span className="text-xs text-muted-foreground">to</span>
      <Input type="number" inputMode="decimal" step="any" min={0} value={max} onChange={(e) => onMax(e.target.value)} placeholder={phMax} aria-label="maximum" className="num h-8 text-sm" />
    </div>
  );
}