"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { citeIdFromHref, linkifyCitations } from "@/lib/citations";
import { CitationChip } from "@/components/ask/citation-chip";
import type { Citation } from "@/lib/types";

export function AnswerMarkdown({
  text,
  citations,
  added,
}: {
  text: string;
  citations?: Citation[];
  added?: Set<string>;
}) {
  const byId = new Map((citations ?? []).map((c) => [c.id, c]));

  return (
    <div className="space-y-3 text-[15px] leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const id = citeIdFromHref(href);
            if (id) return <CitationChip id={id} citation={byId.get(id)} added={added?.has(id)} />;
            return (
              <a href={href} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-4">
                {children}
              </a>
            );
          },
          ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5">{children}</ol>,
          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
          h1: ({ children }) => <h3 className="pt-1 font-semibold">{children}</h3>,
          h2: ({ children }) => <h3 className="pt-1 font-semibold">{children}</h3>,
          h3: ({ children }) => <h3 className="pt-1 font-semibold">{children}</h3>,
          code: ({ children }) => <code className="num rounded bg-secondary px-1 py-0.5 text-[13px]">{children}</code>,
          table: ({ children }) => (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border-b px-2 py-1 text-left font-medium text-muted-foreground">{children}</th>
          ),
          td: ({ children }) => <td className="num border-b border-border/60 px-2 py-1">{children}</td>,
        }}
      >
        {linkifyCitations(text)}
      </ReactMarkdown>
    </div>
  );
}