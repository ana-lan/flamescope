import useSWR from "swr";
import { api } from "@/lib/api";
import type { HabitatSlug, TestsQuery } from "@/lib/types";

// Keys are arrays so each distinct argument set gets its own cache entry.
export const useHabitats = () => useSWR("habitats", () => api.habitats());

export const useInsights = (habitat: HabitatSlug | null) =>
  useSWR(["insights", habitat], () => api.insights(habitat));

export const useCoverage = (habitat: HabitatSlug | null) =>
  useSWR(habitat ? ["coverage", habitat] : null, () => api.coverage(habitat as HabitatSlug));

export const useFacets = () => useSWR("facets", () => api.facets());

export const useTests = (q: TestsQuery) => useSWR(["tests", JSON.stringify(q)], () => api.tests(q));

export const useInvestigations = () => useSWR("investigations", () => api.investigations());

export const useInvestigation = (psiId: string | null) =>
  useSWR(psiId ? ["investigation", psiId] : null, () => api.investigation(psiId as string));

export const useSuggested = (habitat: HabitatSlug | null) =>
  useSWR(["suggested", habitat], () => api.suggested(habitat));