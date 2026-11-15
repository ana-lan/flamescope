"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CoverageChart, CoverageLegend } from "@/components/coverage-chart";
import { fmtNumber, fmtPct, outcomeLabel } from "@/lib/format";
import type { Coverage } from "@/lib/types";

function range(r: [number | null, number | null], fmt: (v: number) => string) {
  const [a, b] = r;
  if (a == null || b == null) return "n/a";
  return a === b ? fmt(a) : `${fmt(a)} to ${fmt(b)}`;
}

export function CoveragePanel({ coverage }: { coverage: Coverage }) {
  const { summary, experiments } = coverage;
  const near = experiments.filter((e) => !e.far).sort((a, b) => a.nearest_distance - b.nearest_distance);
  const nFar = experiments.length - near.length;

  return (
    <Card>
      <CardContent className="space-y-6 pt-6">
        <dl className="grid grid-cols-3 gap-4">
          <Stat label="Tests in the box" value={String(summary.n_in_box)} accent />
          <Stat label="Tests plotted" value={fmtNumber(summary.n_tested)} />
          <Stat
            label="Nearest test"
            value={summary.n_in_box > 0 ? "inside" : `${fmtNumber(summary.nearest_distance)} boxes`}
          />
        </dl>

        <CoverageChart coverage={coverage} />
        <CoverageLegend nInBox={coverage.points.filter((p) => p.in_box).length} />

        {near.length > 0 ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Experiment</TableHead>
                  <TableHead className="text-right">In box</TableHead>
                  <TableHead className="text-right">Nearest</TableHead>
                  <TableHead>Tested pressure</TableHead>
                  <TableHead>Tested O2</TableHead>
                  <TableHead>What happened in the box</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {near.map((e) => (
                  <TableRow key={e.psi_id + e.experiment}>
                    <TableCell>
                      <span className="font-medium">{e.experiment}</span>{" "}
                      <span className="num text-xs text-muted-foreground">{e.psi_id}</span>
                    </TableCell>
                    <TableCell className="num text-right">{e.n_in_box}</TableCell>
                    <TableCell className="num text-right">{fmtNumber(e.nearest_distance)}</TableCell>
                    <TableCell className="num text-xs">
                      {range(e.tested_range.pressure_kpa, (v) => `${fmtNumber(v)}`)} kPa
                    </TableCell>
                    <TableCell className="num text-xs">{range(e.tested_range.o2_frac, fmtPct)}</TableCell>
                    <TableCell className="text-xs">
                      {Object.keys(e.outcomes_in_box).length === 0 ? (
                        <span className="text-muted-foreground">none in the box</span>
                      ) : (
                        Object.entries(e.outcomes_in_box)
                          .sort((a, b) => b[1] - a[1])
                          .map(([o, n]) => (
                            <span key={o} className="mr-3 whitespace-nowrap">
                              <span className="num text-primary">{n}</span> {outcomeLabel(o)}
                            </span>
                          ))
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No experiment comes within 2 box widths of this atmosphere.</p>
        )}
        {nFar > 0 && (
          <p className="text-xs text-muted-foreground">
            {nFar} more {nFar === 1 ? "experiment was" : "experiments were"} tested only far from this atmosphere.
            Distance is in box widths: 1 = 15% of the habitat pressure or 3 points of O2.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={`num text-2xl font-semibold ${accent ? "text-primary" : ""}`}>{value}</dd>
    </div>
  );
}