import type { Metadata } from "next";
import { PageHeader } from "@/components/page-header";
import { LessonsView } from "@/components/lessons/lessons-view";

export const metadata: Metadata = { title: "Lessons" };

export default function LessonsPage() {
  return (
    <>
      <PageHeader
        eyebrow="Lessons"
        title="Fires that shaped spaceflight"
        description="Three oxygen fires, what changed after each, and what 15 years of ISS combustion experiments can and cannot tell us about them."
      />
      <LessonsView />
    </>
  );
}