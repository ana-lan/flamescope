import { TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Citation } from "@/lib/types";

export function CitationChip({ id, citation, added }: { id: string; citation?: Citation; added?: boolean }) {
  const unverified = citation ? !citation.verified : false;
  const title = [
    citation?.label && citation.label !== id ? citation.label : null,
    citation?.title,
    citation?.doi ? `doi:${citation.doi}` : null,
    unverified ? "No tool returned this source. Check it before relying on it." : null,
    added ? "Citation added by IgnitIQ from the tool results" : null,
  ]
    .filter(Boolean)
    .join("\n");

  const cls = cn(
    "num mx-0.5 inline-flex items-center gap-1 rounded border px-1.5 align-baseline text-[11px] leading-5 no-underline transition-colors",
    unverified
      ? "border-warning/50 bg-warning/10 text-warning"
      : "border-primary/30 bg-primary/10 text-primary hover:border-primary/70",
    added && "border-dashed",
  );
  const body = (
    <>
      {id}
      {unverified && <TriangleAlert className="size-3" aria-label="unverified" />}
    </>
  );

  return citation?.url ? (
    <a href={citation.url} target="_blank" rel="noreferrer" title={title || id} className={cls}>
      {body}
    </a>
  ) : (
    <span title={title || id} className={cls}>
      {body}
    </span>
  );
}