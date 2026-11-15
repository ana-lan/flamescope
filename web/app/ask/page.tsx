import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/components/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { AskView } from "@/components/ask/ask-view";

export const metadata: Metadata = { title: "Ask IgnitIQ" };

export default function AskPage() {
  return (
    <>
      <PageHeader
        eyebrow="Ask IgnitIQ"
        title="Ask a fire safety question"
        description="Numbers come from SQL over real ISS test rows, explanations from the investigation write-ups, and every claim is cited. Open any answer to see the queries and checks behind it."
      />
      <Suspense fallback={<Skeleton className="h-64 rounded-xl" />}>
        <AskView />
      </Suspense>
    </>
  );
}