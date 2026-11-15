import { outcomeColor, outcomeLabel } from "@/lib/format";

export function OutcomeTag({ outcome }: { outcome: string | null }) {
  if (!outcome) return <span className="text-muted-foreground">·</span>;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs">
      <span className="size-2 shrink-0 rounded-full" style={{ background: outcomeColor(outcome) }} aria-hidden />
      {outcomeLabel(outcome)}
    </span>
  );
}