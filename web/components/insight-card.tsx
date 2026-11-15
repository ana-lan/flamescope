import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SourceChip } from "@/components/source-chip";
import { insightValue } from "@/lib/format";
import type { Insight } from "@/lib/types";

export function InsightCard({ insight }: { insight: Insight }) {
  const v = insightValue(insight.value, insight.unit);

  return (
    <Card className="flex flex-col">
      <CardHeader className="space-y-2">
        <span className="num text-xs text-primary">#{insight.rank}</span>
        <CardTitle className="text-base leading-snug">{insight.title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        <div>
          <p className="num text-5xl font-semibold tracking-tight text-primary">{v.big}</p>
          {v.caption && <p className="mt-1 text-xs uppercase tracking-wider text-muted-foreground">{v.caption}</p>}
        </div>
        {insight.explanation && <p className="text-sm leading-relaxed text-muted-foreground">{insight.explanation}</p>}
        <div className="mt-auto space-y-3">
          <div className="flex flex-wrap gap-2">
            {insight.sources.map((s) => (
              <SourceChip key={s.psi_id} source={s} />
            ))}
          </div>
          <details className="text-xs">
            <summary className="cursor-pointer select-none text-muted-foreground hover:text-foreground">
              Show the SQL
            </summary>
            <pre className="num mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-md border bg-background p-3 text-[11px] leading-relaxed">
              {insight.sql.trim()}
            </pre>
          </details>
        </div>
      </CardContent>
    </Card>
  );
}