"use client";

import {
  CartesianGrid,
  ReferenceArea,
  ReferenceDot,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { fmtKpa, fmtPct, outcomeLabel } from "@/lib/format";
import type { Coverage, CoveragePoint } from "@/lib/types";

type Datum = CoveragePoint & { x: number; y: number };

const P_TICKS = [50, 70, 100, 150, 200, 300, 500];
const AXIS = { fill: "var(--muted-foreground)", fontSize: 11 };

export function CoverageChart({ coverage }: { coverage: Coverage }) {
  const { target, tolerance, points, habitat } = coverage;

  const inBox: Datum[] = [];
  const other: Datum[] = [];
  for (const p of points) {
    (p.in_box ? inBox : other).push({ ...p, x: p.pressure_kpa, y: p.o2_frac * 100 });
  }

  const ty = target.o2_frac * 100;
  const dy = tolerance.o2_abs * 100;
  // Apollo 1 (100% O2) stretches the axis on purpose; round ticks either way
  const tall = ty + dy > 42;
  const yMax = tall ? 105 : 42;
  const yTicks = tall ? [10, 25, 50, 75, 100] : [10, 15, 20, 25, 30, 35, 40];
  
  return (
    <div
      className="h-80 w-full sm:h-96"
      role="img"
      aria-label={`Scatter of ${points.length} tested conditions, pressure against oxygen, with ${habitat.name} marked and ${inBox.length} tests inside its box`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 12, right: 16, bottom: 24, left: 0 }}>
          <CartesianGrid stroke="var(--border)" />
          <XAxis
            type="number"
            dataKey="x"
            scale="log"
            domain={[40, 550]}
            ticks={P_TICKS}
            allowDataOverflow
            tick={AXIS}
            stroke="var(--border)"
            label={{ value: "Pressure (kPa, log scale)", position: "insideBottom", offset: -14, ...AXIS }}
          />
          <YAxis
            type="number"
            dataKey="y"
            domain={[10, yMax]}
            ticks={yTicks}
            unit="%"
            tick={AXIS}
            stroke="var(--border)"
            width={48}
          />
          <ZAxis range={[26, 26]} />
          <ReferenceArea
            x1={target.pressure_kpa * (1 - tolerance.pressure_rel)}
            x2={target.pressure_kpa * (1 + tolerance.pressure_rel)}
            y1={ty - dy}
            y2={ty + dy}
            fill="var(--primary)"
            fillOpacity={0.08}
            stroke="var(--primary)"
            strokeOpacity={0.7}
            strokeDasharray="4 4"
          />
          <Scatter name="Other tests" data={other} fill="var(--muted-foreground)" fillOpacity={0.35} isAnimationActive={false} />
          <Scatter name="In the box" data={inBox} fill="var(--primary)" isAnimationActive={false} />
          <ReferenceDot
            x={target.pressure_kpa}
            y={ty}
            r={7}
            fill="var(--background)"
            stroke="var(--primary)"
            strokeWidth={3}
          />
          <Tooltip
            cursor={{ stroke: "var(--border)", strokeDasharray: "3 3" }}
            isAnimationActive={false}
            content={({ active, payload }) => (
              <PointTip active={active} datum={payload?.[0]?.payload as Datum | undefined} />
            )}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function PointTip({ active, datum }: { active?: boolean; datum?: Datum }) {
  if (!active || !datum) return null;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="font-medium">
        {datum.experiment} <span className="num text-muted-foreground">{datum.psi_id}</span>
      </p>
      <p className="num">
        {fmtKpa(datum.pressure_kpa)} · {fmtPct(datum.o2_frac)} O2
      </p>
      <p className="text-muted-foreground">
        {outcomeLabel(datum.outcome)}
        {datum.row_kind === "summary" ? " · summary row" : ""}
      </p>
    </div>
  );
}

export function CoverageLegend({ nInBox }: { nInBox: number }) {
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground">
      <li className="flex items-center gap-2">
        <span className="size-2.5 rounded-full bg-primary" /> In the box ({nInBox})
      </li>
      <li className="flex items-center gap-2">
        <span className="size-2.5 rounded-full bg-muted-foreground/40" /> Other tests
      </li>
      <li className="flex items-center gap-2">
        <span className="size-3 rounded-full border-[3px] border-primary bg-background" /> Habitat atmosphere
      </li>
      <li className="flex items-center gap-2">
        <span className="h-2.5 w-4 rounded-sm border border-dashed border-primary bg-primary/10" /> ±15% pressure, ±3 pts O2
      </li>
    </ul>
  );
}