"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, API_URL, ApiError } from "@/lib/api";
import { askStream } from "@/lib/sse";
import { useSuggested } from "@/lib/hooks";
import type { AskEvent, HabitatSlug } from "@/lib/types";

type Check = { name: string; expect: string; run: () => Promise<string> };

async function expectError(fn: () => Promise<unknown>): Promise<string> {
  try {
    await fn();
    return "no error (wrong)";
  } catch (e) {
    return e instanceof ApiError ? `${e.kind} ${e.status ?? ""}`.trim() : String(e);
  }
}

const CHECKS: Check[] = [
  {
    name: "GET /health",
    expect: "ok, 1999 tests, 316 chunks",
    run: async () => {
      const h = await api.health();
      return `${h.status}, ${h.db.tests} tests, ${String(h.index.chunks)} chunks`;
    },
  },
  {
    name: "GET /habitats",
    expect: "iss, gateway, lunar, apollo1",
    run: async () => (await api.habitats()).map((h) => h.slug).join(", "),
  },
  {
    name: "GET /insights",
    expect: "5 insights, rank 1 coverage_gap",
    run: async () => {
      const r = await api.insights();
      return `${r.length} insights, rank 1 ${r[0]?.id}`;
    },
  },
  {
    name: "GET /insights?habitat=lunar",
    expect: "a subset of the 5",
    run: async () => (await api.insights("lunar")).map((i) => i.id).join(", "),
  },
  {
    name: "GET /tests",
    expect: "total 1953, 200 rows",
    run: async () => {
      const p = await api.tests();
      return `total ${p.total}, ${p.rows.length} rows`;
    },
  },
  {
    name: "GET /tests?experiment=FLEX&o2_min=0.3",
    expect: "total > 0, every row FLEX, min O2 >= 0.3",
    run: async () => {
      const p = await api.tests({ experiment: ["FLEX"], o2_min: 0.3 });
      const exps = [...new Set(p.rows.map((r) => r.experiment))].join("/");
      const minO2 = Math.min(...p.rows.map((r) => r.o2_frac ?? 1));
      return `total ${p.total}, ${exps}, min O2 ${minO2}`;
    },
  },
  {
    name: "GET /tests/facets",
    expect: "p 43.0 to 506.6 kPa, O2 0.12 to 0.4",
    run: async () => {
      const f = await api.facets();
      const r = f.ranges;
      return `${f.experiments.length} experiments, ${f.fuels.length} fuels, p ${r.p_min?.toFixed(1)} to ${r.p_max?.toFixed(1)} kPa, O2 ${r.o2_min} to ${r.o2_max}`;
    },
  },
  {
    name: "GET /investigations",
    expect: "23 items, first PSI-10",
    run: async () => {
      const r = await api.investigations();
      return `${r.length} items, first ${r[0]?.psi_id}`;
    },
  },
  {
    name: "GET /investigations/PSI-69",
    expect: "FLEX, 274 rows, doi 10.60555/mbq8-0451",
    run: async () => {
      const d = await api.investigation("PSI-69");
      return `${d.investigation.acronym}, ${d.tests.n_rows} rows, doi ${d.investigation.doi}`;
    },
  },
  {
    name: "GET /coverage?habitat=lunar",
    expect: "sparse, 11 in box, nearest 0.69",
    run: async () => {
      const c = await api.coverage("lunar");
      const s = c.summary;
      return `${s.verdict}, ${s.n_in_box} in box, nearest ${s.nearest_distance}, ${c.points.length} points`;
    },
  },
  {
    name: "GET /ask/suggested",
    expect: "at least 1 question",
    run: async () => `${(await api.suggested()).length} questions`,
  },
  {
    name: "404: /investigations/PSI-9999",
    expect: "not_found 404",
    run: () => expectError(() => api.investigation("PSI-9999")),
  },
  {
    name: "422: /coverage?habitat=mars",
    expect: "validation 422",
    run: () => expectError(() => api.coverage("mars" as HabitatSlug)),
  },
];

type Result = { got: string; ms: number; ok: boolean };

function summarize(e: AskEvent): string {
  switch (e.event) {
    case "start":
      return e.data.question;
    case "status":
      return e.data.stage;
    case "tool_call":
      return e.data.tool;
    case "tool_result":
      return `${e.data.tool}: ${e.data.summary}`;
    case "final":
      return `answer ${e.data.answer.length} chars`;
    case "error":
      return e.data.message;
    default:
      return "";
  }
}

export default function DevPage() {
  const [results, setResults] = useState<Record<string, Result>>({});
  const [running, setRunning] = useState(false);

  const runAll = useCallback(async () => {
    setRunning(true);
    setResults({});
    for (const c of CHECKS) {
      const t0 = performance.now();
      try {
        const got = await c.run();
        setResults((r) => ({ ...r, [c.name]: { got, ms: performance.now() - t0, ok: true } }));
      } catch (e) {
        const got = e instanceof ApiError ? `${e.kind}: ${e.message}` : String(e);
        setResults((r) => ({ ...r, [c.name]: { got, ms: performance.now() - t0, ok: false } }));
      }
    }
    setRunning(false);
  }, []);

  useEffect(() => {
    runAll();
  }, [runAll]);

  return (
    <div className="space-y-10">
      <PageHeader eyebrow="Dev" title="API client check" description={<span className="num">{API_URL}</span>}>
        <Button onClick={runAll} disabled={running}>
          {running ? "Running" : "Run again"}
        </Button>
      </PageHeader>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Check</TableHead>
            <TableHead>Expected</TableHead>
            <TableHead>Got</TableHead>
            <TableHead className="text-right">ms</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {CHECKS.map((c) => {
            const r = results[c.name];
            return (
              <TableRow key={c.name}>
                <TableCell className="num text-xs">{c.name}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{c.expect}</TableCell>
                <TableCell className={`num text-xs ${r && !r.ok ? "text-destructive" : ""}`}>
                  {r ? r.got : "..."}
                </TableCell>
                <TableCell className="num text-right text-xs">{r ? Math.round(r.ms) : ""}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      <SseReplay />
    </div>
  );
}

function SseReplay() {
  const { data: suggested } = useSuggested(null);
  const [log, setLog] = useState<string[]>([]);
  const [result, setResult] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const first = suggested?.[0];

  async function run() {
    if (!first) return;
    setRunning(true);
    setLog([]);
    setResult(null);
    let tokens = "";
    const counts: Record<string, number> = {};
    try {
      const final = await askStream(
        { question: first.question, habitat: first.habitat },
        {
          onEvent: (e) => {
            counts[e.event] = (counts[e.event] ?? 0) + 1;
            if (e.event === "token") tokens += e.data.text;
            else setLog((l) => [...l, `${e.event}  ${summarize(e)}`]);
          },
        },
      );
      setResult(
        [
          `cached=${final.cached}`,
          `tokens == answer: ${tokens === final.answer}`,
          `events ${JSON.stringify(counts)}`,
          `citations ${final.citations.map((c) => c.id).join(", ")}`,
          `grounding.ok=${final.grounding.ok}`,
        ].join("\n"),
      );
    } catch (e) {
      setResult(e instanceof ApiError ? `${e.kind}: ${e.message}` : String(e));
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">SSE replay (cached, 0 tokens)</h2>
      <p className="text-sm text-muted-foreground">{first ? first.question : "loading suggested questions..."}</p>
      <Button onClick={run} disabled={!first || running}>
        {running ? "Streaming" : "Replay over SSE"}
      </Button>
      {log.length > 0 && (
        <pre className="num overflow-x-auto rounded-lg border bg-card p-3 text-xs">{log.join("\n")}</pre>
      )}
      {result && <pre className="num overflow-x-auto rounded-lg border bg-card p-3 text-xs">{result}</pre>}
    </section>
  );
}