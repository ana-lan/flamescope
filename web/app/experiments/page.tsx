import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/components/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Explorer } from "@/components/explorer/explorer";

export const metadata: Metadata = { title: "Experiments" };

export default function ExperimentsPage() {
  return (
    <>
      <PageHeader
        eyebrow="Experiment explorer"
        title="Every test, every condition"
        description="Filter the ISS combustion tests by experiment, outcome, fuel, pressure and oxygen. Click any row to open the investigation behind it, with its DOI."
      />
      <Suspense fallback={<Skeleton className="h-96 rounded-xl" />}>
        <Explorer />
      </Suspense>
    </>
  );
}