import useSWR from "swr";
import { api } from "@/lib/api";
import type { HabitatSlug, TestsQuery } from "@/lib/types";

// Keys are arrays so each distinct argument set gets its own cache entry.
export const useHabitats = () => useSWR("habitats", () => api.habitats());

export const useInsights = (habitat: HabitatSlug | null) =>
  useSWR(["insights", habitat], () => api.insights(habitat), { keepPreviousData: true });

export const useCoverage = (habitat: HabitatSlug | null) =>
  useSWR(habitat ? ["coverage", habitat] : null, () => api.coverage(habitat as HabitatSlug), {
    keepPreviousData: true,
  });

export const useFacets = () => useSWR("facets", () => api.facets());

export const useTests = (q: TestsQuery | null) =>
  useSWR(q ? ["tests", JSON.stringify(q)] : null, () => api.tests(q as TestsQuery), { keepPreviousData: true });

export const useInvestigations = () => useSWR("investigations", () => api.investigations());

export const useInvestigation = (psiId: string | null) =>
  useSWR(psiId ? ["investigation", psiId] : null, () => api.investigation(psiId as string));

export const useSuggested = (habitat: HabitatSlug | null) =>
  useSWR(["suggested", habitat], () => api.suggested(habitat));