import { ExternalLink } from "lucide-react";
import type { Source } from "@/lib/types";

export function SourceChip({ source }: { source: Source }) {
  const label = source.acronym ?? source.title ?? source.psi_id;
  const body = (
    <>
      <span className="num text-primary">{source.psi_id}</span>
      <span className="max-w-[16rem] truncate">{label}</span>
      {source.doi_url && <ExternalLink className="size-3 shrink-0 opacity-60" aria-hidden />}
    </>
  );
  const cls =
    "inline-flex items-center gap-1.5 rounded-md border bg-secondary/60 px-2 py-0.5 text-xs text-secondary-foreground";

  return source.doi_url ? (
    <a
      href={source.doi_url}
      target="_blank"
      rel="noreferrer"
      title={source.doi ? `doi:${source.doi}` : undefined}
      className={`${cls} transition-colors hover:border-primary/60`}
    >
      {body}
    </a>
  ) : (
    <span className={cls}>{body}</span>
  );
}