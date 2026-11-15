import type { Metadata } from "next";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Lessons" };

export default function LessonsPage() {
  return (
    <PageHeader
      eyebrow="Lessons"
      title="Fires that shaped spaceflight"
      description="Apollo 1, Apollo 13 and Mir, linked to what the ISS experiments now tell us."
    />
  );
}