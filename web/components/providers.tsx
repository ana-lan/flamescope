"use client";

import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";

// Errors that will not fix themselves on retry.
const NO_RETRY = new Set(["not_found", "validation", "aborted", "busy"]);

export function Providers({ children }: { children: ReactNode }) {
  return (
    <SWRConfig
      value={{
        revalidateOnFocus: false, // the data is static; don't refetch on every tab switch
        dedupingInterval: 60_000,
        errorRetryCount: 3,
        shouldRetryOnError: (err) => !(err instanceof ApiError && NO_RETRY.has(err.kind)),
      }}
    >
      <TooltipProvider>{children}</TooltipProvider>
    </SWRConfig>
  );
}