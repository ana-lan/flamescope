import type { Metadata } from "next";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Ask IgnitIQ" };

export default function AskPage() {
  return (
    <PageHeader
      eyebrow="Ask IgnitIQ"
      title="Ask a fire safety question"
      description="Answers are computed from real test rows and cited to the investigation. Open any answer to see the SQL and passages behind it."
    />
  );
}