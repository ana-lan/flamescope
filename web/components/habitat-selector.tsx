"use client";

import { cn } from "@/lib/utils";
import { fmtKpa, fmtPct, KIND_LABEL } from "@/lib/format";
import type { Habitat, HabitatSlug } from "@/lib/types";

export function HabitatSelector({
  habitats,
  value,
  onChange,
}: {
  habitats: Habitat[];
  value: HabitatSlug;
  onChange: (slug: HabitatSlug) => void;
}) {
  return (
    <div role="radiogroup" aria-label="Habitat atmosphere" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {habitats.map((h) => {
        const selected = h.slug === value;
        return (
          <button
            key={h.slug}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(h.slug)}
            className={cn(
              "rounded-xl border bg-card p-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
              selected ? "border-primary bg-primary/5 ring-1 ring-primary/40" : "hover:border-foreground/25",
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <span className="font-medium leading-tight">{h.name}</span>
              <span
                className={cn(
                  "shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider",
                  h.kind === "historical" ? "text-muted-foreground" : "text-foreground/80",
                )}
              >
                {KIND_LABEL[h.kind] ?? h.kind}
              </span>
            </div>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
              <dt className="text-muted-foreground">Pressure</dt>
              <dd className="num">
                {fmtKpa(h.pressure_kpa)}
                {h.pressure_psia != null && <span className="text-muted-foreground"> · {h.pressure_psia} psia</span>}
              </dd>
              <dt className="text-muted-foreground">O2</dt>
              <dd className={cn("num", selected && "text-primary")}>{fmtPct(h.o2_frac)}</dd>
              <dt className="text-muted-foreground">ppO2</dt>
              <dd className="num">{fmtKpa(h.pp_o2_kpa)}</dd>
            </dl>
          </button>
        );
      })}
    </div>
  );
}