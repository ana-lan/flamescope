import type { Metadata } from "next";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Experiments" };

export default function ExperimentsPage() {
  return (
    <PageHeader
      eyebrow="Experiment explorer"
      title="Every test, every condition"
      description="Filter 1,953 ISS combustion tests by experiment, fuel, pressure and oxygen."
    />
  );
}