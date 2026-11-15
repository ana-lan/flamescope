"use client";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { OutcomeTag } from "@/components/outcome-tag";
import { fmtPct } from "@/lib/format";
import type { TestRow } from "@/lib/types";

const Dot = () => <span className="text-muted-foreground">·</span>;

// extra keys that are lineage or internals, not measurements
const HIDDEN = new Set(["source_file", "source_row", "raw", "row_kind", "source_test_id"]);

// True when every measurement column is empty (BASS-style test logs).
export function isLogOnly(r: TestRow): boolean {
  return [r.pressure_kpa, r.o2_frac, r.diluent, r.outcome, r.burn_time_s, r.spread_rate_mm_s].every((v) => v == null);
}

// "date 3/30/2012 · sample num 4 · planned test num 1"
function extraSummary(extra: TestRow["extra"]): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(extra ?? {})) {
    if (HIDDEN.has(k) || v == null || v === "" || typeof v === "boolean") continue;
    if (typeof v === "object" && !Array.isArray(v)) continue;
    const val = Array.isArray(v)
      ? v.join(", ")
      : typeof v === "number"
        ? v.toLocaleString("en-US", { maximumFractionDigits: 3 })
        : String(v);
    parts.push(`${k.replace(/_/g, " ")} ${val}`);
    if (parts.length === 4) break;
  }
  return parts.join(" · ");
}

function NumCell({ v, digits = 1 }: { v: number | null; digits?: number }) {
  return (
    <TableCell className="num text-right text-xs">
      {v == null ? <Dot /> : v.toLocaleString("en-US", { maximumFractionDigits: digits })}
    </TableCell>
  );
}

export function TestsTable({ rows, onOpen }: { rows: TestRow[]; onOpen: (psiId: string) => void }) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Experiment</TableHead>
            <TableHead>Test</TableHead>
            <TableHead>Fuel / material</TableHead>
            <TableHead className="text-right">kPa</TableHead>
            <TableHead className="text-right">O2</TableHead>
            <TableHead>Diluent</TableHead>
            <TableHead>Outcome</TableHead>
            <TableHead className="text-right">Burn s</TableHead>
            <TableHead className="text-right">Spread mm/s</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => {
            const fuel = [r.fuel, r.material].filter(Boolean).join(" · ");
            const summary = r.extra?.row_kind === "summary";
            const logOnly = isLogOnly(r);
            return (
              <TableRow
                key={r.test_pk}
                tabIndex={0}
                onClick={() => onOpen(r.psi_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onOpen(r.psi_id);
                }}
                className="cursor-pointer"
                title={`Open ${r.psi_id}`}
              >
                <TableCell className="whitespace-nowrap">
                  <span className="font-medium">{r.experiment}</span>{" "}
                  <span className="num text-xs text-muted-foreground">{r.psi_id}</span>
                </TableCell>
                <TableCell className="num whitespace-nowrap text-xs">
                  {r.test_id ?? <Dot />}
                  {summary && (
                    <span className="ml-2 rounded border px-1 text-[10px] uppercase text-muted-foreground">summary</span>
                  )}
                </TableCell>
                <TableCell className="max-w-[14rem] truncate text-xs" title={fuel || undefined}>
                  {fuel || <Dot />}
                </TableCell>

                {logOnly ? (
                  <TableCell colSpan={6} className="text-xs text-muted-foreground">
                    <span className="mr-1.5 rounded border px-1 text-[10px] uppercase">{summary ? "summary" : "test log"}</span>
                    {extraSummary(r.extra) || "no measurements in the PSI table"}
                  </TableCell>
                ) : (
                  <>
                    <NumCell v={r.pressure_kpa} />
                    <TableCell className="num text-right text-xs">
                      {r.o2_frac != null ? fmtPct(r.o2_frac) : <Dot />}
                    </TableCell>
                    <TableCell className="text-xs">{r.diluent ?? <Dot />}</TableCell>
                    <TableCell>
                      <OutcomeTag outcome={r.outcome} />
                    </TableCell>
                    <NumCell v={r.burn_time_s} />
                    <NumCell v={r.spread_rate_mm_s} digits={2} />
                  </>
                )}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}