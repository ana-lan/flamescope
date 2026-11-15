"use client";

import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { fmtKpa, fmtPct, OUTCOME_ORDER, outcomeColor, outcomeLabel } from "@/lib/format";
import type { TestRow } from "@/lib/types";

type Datum = { x: number; y: number; row: TestRow };

const AXIS = { fill: "var(--muted-foreground)", fontSize: 11 };

// Stable vertical spread so stacked tests don't hide each other (same spot every render)
function jitter(pk: number): number {
  return (((pk * 9301 + 49297) % 233280) / 233280 - 0.5) * 0.5;
}

export function OutcomeStrip({ rows }: { rows: TestRow[] }) {
  const usable = rows.filter((r) => r.outcome && r.o2_frac != null);
  const present = OUTCOME_ORDER.filter((o) => usable.some((r) => r.outcome === o));

  if (!present.length) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        No recorded outcomes for these filters. Outcomes are recorded for FLEX droplets and CFI-G gas jets.
      </p>
    );
  }

  const series = present.map((o, i) => ({
    outcome: o,
    data: usable
      .filter((r) => r.outcome === o)
      .map((r) => ({ x: (r.o2_frac as number) * 100, y: i + jitter(r.test_pk), row: r })),
  }));

  return (
    <div
      className="w-full"
      style={{ height: 64 + present.length * 48 }}
      role="img"
      aria-label={`${usable.length} tests plotted by oxygen percentage and outcome`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 16, bottom: 24, left: 0 }}>
          <CartesianGrid stroke="var(--border)" horizontal={false} />
          <XAxis
            type="number"
            dataKey="x"
            domain={["dataMin - 1", "dataMax + 1"]}
            tickFormatter={(v: number) => `${Math.round(v)}%`}
            tick={AXIS}
            stroke="var(--border)"
            label={{ value: "Ambient O2", position: "insideBottom", offset: -14, ...AXIS }}
          />
          <YAxis
            type="number"
            dataKey="y"
            domain={[-0.5, present.length - 0.5]}
            ticks={present.map((_, i) => i)}
            interval={0}
            reversed
            tickFormatter={(i: number) => outcomeLabel(present[i] ?? null)}
            tick={AXIS}
            stroke="var(--border)"
            width={160}
          />
          <ZAxis range={[24, 24]} />
          {series.map((s) => (
            <Scatter key={s.outcome} data={s.data} fill={outcomeColor(s.outcome)} fillOpacity={0.75} isAnimationActive={false} />
          ))}
          <Tooltip
            cursor={false}
            isAnimationActive={false}
            content={({ active, payload }) => {
              const d = payload?.[0]?.payload as Datum | undefined;
              if (!active || !d) return null;
              const r = d.row;
              return (
                <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
                  <p className="font-medium">
                    {r.experiment} <span className="num text-muted-foreground">{r.test_id}</span>
                  </p>
                  <p className="text-muted-foreground">{r.fuel ?? r.material ?? "fuel not recorded"}</p>
                  <p className="num">
                    {fmtKpa(r.pressure_kpa)} · {fmtPct(r.o2_frac)} O2
                  </p>
                  <p>{outcomeLabel(r.outcome)}</p>
                </div>
              );
            }}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}