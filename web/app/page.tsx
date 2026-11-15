import { Suspense } from "react";
import { PageHeader } from "@/components/page-header";
import { MissionBrief, MissionBriefSkeleton } from "@/components/mission-brief";

export default function MissionBriefPage() {
  return (
    <>
      <PageHeader
        eyebrow="Mission brief"
        title="Fire safety for the next habitat"
        description="Apollo 1 burned in pure oxygen. Lunar and Mars habitats will run richer in oxygen than the ISS. Pick an atmosphere to see what 18 ISS combustion investigations say about fire there, and where the data runs out."
      />
      <Suspense fallback={<MissionBriefSkeleton />}>
        <MissionBrief />
      </Suspense>
    </>
  );
}