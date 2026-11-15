"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorNote } from "@/components/error-note";
import { activeCount, EMPTY_FILTERS, FilterPanel, toQuery, type Filters } from "@/components/explorer/filters";
import { OutcomeStrip } from "@/components/explorer/outcome-strip";
import { TestsTable } from "@/components/explorer/tests-table";
import { InvestigationPanel } from "@/components/explorer/investigation-panel";
import { useFacets, useTests } from "@/lib/hooks";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";
import type { TestsQuery } from "@/lib/types";

const PAGE_SIZE = 50;
const CHART_LIMIT = 1000;

export function Explorer() {
  const params = useSearchParams();
  const [filters, setFilters] = useState<Filters>(() => ({ ...EMPTY_FILTERS, experiments: params.getAll("experiment") }));
  const [openPsi, setOpenPsi] = useState<string | null>(() => params.get("psi"));

  const facets = useFacets();

  // Debounce the query as a string: a new object every render would never settle.
  const qKey = useDebounced(JSON.stringify(toQuery(filters)), 300);
  const query = useMemo(() => JSON.parse(qKey) as TestsQuery, [qKey]);

  // The page belongs to the query it was set for; new filters read as page 0 right away.
  const [pageState, setPageState] = useState({ key: qKey, page: 0 });
  const page = pageState.key === qKey ? pageState.page : 0;
  const setPage = (p: number) => setPageState({ key: qKey, page: p });

  const table = useTests({ ...query, limit: PAGE_SIZE, offset: page * PAGE_SIZE });

  // Chart: every matching row with a recorded outcome (unless the user picked outcomes).
  const allOutcomes = facets.data?.outcomes.map((o) => o.outcome);
  const chart = useTests(
    allOutcomes ? { ...query, outcome: query.outcome ?? allOutcomes, limit: CHART_LIMIT, offset: 0 } : null,
  );

  const total = table.data?.total ?? 0;
  const from = total ? page * PAGE_SIZE + 1 : 0;
  const to = Math.min(total, (page + 1) * PAGE_SIZE);
  const nActive = activeCount(filters);

  const filterToPsi = (psi: string) => {
    const exps = facets.data?.experiments.filter((e) => e.psi_id === psi).map((e) => e.experiment) ?? [];
    if (exps.length) {
      setFilters({ ...EMPTY_FILTERS, experiments: exps });
      setOpenPsi(null);
    }
  };
  const canFilter = (psi: string | null) => !!psi && !!facets.data?.experiments.some((e) => e.psi_id === psi);

  return (
    <>
      <div className="grid gap-8 lg:grid-cols-[17rem_minmax(0,1fr)]">
        <aside className="lg:sticky lg:top-20 lg:max-h-[calc(100dvh-6rem)] lg:self-start lg:overflow-y-auto lg:pr-2">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold">
              Filters {nActive > 0 && <span className="num text-primary">({nActive})</span>}
            </h2>
            {nActive > 0 && (
              <button type="button" onClick={() => setFilters(EMPTY_FILTERS)} className="text-xs text-muted-foreground hover:text-foreground">
                Reset
              </button>
            )}
          </div>
          {facets.error ? (
            <ErrorNote what="filters" error={facets.error} onRetry={() => facets.mutate()} />
          ) : (
            <FilterPanel facets={facets.data} value={filters} onChange={setFilters} />
          )}
        </aside>

        <div className="min-w-0 space-y-6">
          <Card>
            <CardContent className="space-y-3 pt-6">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="font-semibold">Oxygen vs what the flame did</h2>
                {chart.data && (
                  <p className="num text-xs text-muted-foreground">
                    {chart.data.total > CHART_LIMIT
                      ? `first ${CHART_LIMIT.toLocaleString()} of ${chart.data.total.toLocaleString()} tests with an outcome`
                      : `${chart.data.total.toLocaleString()} tests with an outcome`}
                  </p>
                )}
              </div>
              {chart.error ? (
                <ErrorNote what="the chart" error={chart.error} onRetry={() => chart.mutate()} />
              ) : !chart.data ? (
                <Skeleton className="h-64" />
              ) : (
                <div className={cn("transition-opacity", chart.isValidating && "opacity-60")}>
                  <OutcomeStrip rows={chart.data.rows} />
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-3 pt-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="font-semibold">
                  <span className="num text-primary">{table.data ? total.toLocaleString() : "..."}</span> tests
                  <span className="ml-2 text-xs font-normal text-muted-foreground">click a row for its investigation</span>
                </h2>
                <div className="flex items-center gap-2">
                  <span className="num text-xs text-muted-foreground">
                    {from} to {to} of {total.toLocaleString()}
                  </span>
                  <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>
                    Prev
                  </Button>
                  <Button size="sm" variant="outline" disabled={to >= total} onClick={() => setPage(page + 1)}>
                    Next
                  </Button>
                </div>
              </div>

              {table.error ? (
                <ErrorNote what="tests" error={table.error} onRetry={() => table.mutate()} />
              ) : !table.data ? (
                <Skeleton className="h-96" />
              ) : total === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">No tests match these filters.</p>
              ) : (
                <div className={cn("transition-opacity", table.isValidating && "opacity-60")}>
                  <TestsTable rows={table.data.rows} onOpen={setOpenPsi} />
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <InvestigationPanel
        psiId={openPsi}
        onClose={() => setOpenPsi(null)}
        onFilter={canFilter(openPsi) ? filterToPsi : undefined}
      />
    </>
  );
}