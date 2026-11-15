import type {
    AskFinal,
    AskRequest,
    Coverage,
    Facets,
    Habitat,
    HabitatSlug,
    Health,
    Insight,
    InvestigationDetail,
    InvestigationSummary,
    Suggested,
    TestsPage,
    TestsQuery,
  } from "@/lib/types";
  
  export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
  
  // Render's free tier can take about 60 s to wake, so GETs wait up to 75 s.
  export const DEFAULT_TIMEOUT_MS = 75_000;
  
  // ------------------------------------------------------------ errors
  
  export type ApiErrorKind =
    | "network" // backend unreachable
    | "timeout" // no response in time
    | "aborted" // cancelled by us (navigation, new question)
    | "not_found" // 404
    | "validation" // 422
    | "busy" // 429: too many /ask running
    | "unavailable" // 503: every model failed
    | "stream" // SSE error event
    | "server"; // anything else
  
  export class ApiError extends Error {
    readonly kind: ApiErrorKind;
    readonly status: number | null;
    readonly detail: unknown;
  
    constructor(kind: ApiErrorKind, message: string, status: number | null = null, detail: unknown = null) {
      super(message);
      this.name = "ApiError";
      this.kind = kind;
      this.status = status;
      this.detail = detail;
    }
  }
  
  function kindFromStatus(status: number): ApiErrorKind {
    if (status === 404) return "not_found";
    if (status === 422) return "validation";
    if (status === 429) return "busy";
    if (status === 503) return "unavailable";
    return "server";
  }
  
  // 404/429/503 send {"detail": "message"}; 422 sends {"detail": [{loc, msg, type}]}
  function detailMessage(detail: unknown): string | null {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const parts = (detail as { loc?: unknown[]; msg?: string }[])
        .map((d) => {
          const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : null;
          return field ? `${String(field)}: ${d.msg ?? "invalid"}` : (d.msg ?? "");
        })
        .filter(Boolean);
      return parts.length ? parts.join("; ") : null;
    }
    return null;
  }
  
  export async function errorFromResponse(res: Response): Promise<ApiError> {
    let detail: unknown = null;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail ?? null;
    } catch {
      // body was not JSON
    }
    return new ApiError(
      kindFromStatus(res.status),
      detailMessage(detail) ?? `${res.status} ${res.statusText}`,
      res.status,
      detail,
    );
  }
  
  // ------------------------------------------------------------ request core
  
  type QueryValue = string | number | boolean | null | undefined | (string | number)[];
  type Query = Record<string, QueryValue>;
  
  export function buildUrl(path: string, query?: Query): string {
    const url = new URL(API_URL + path);
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value === undefined || value === null || value === "") continue;
      if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, String(v)));
      else url.searchParams.set(key, String(value));
    }
    return url.toString();
  }
  
  export interface RequestOptions {
    signal?: AbortSignal;
    timeoutMs?: number;
  }
  
  // Links the caller's signal and a timeout to one AbortController.
  export function linkedAbort(signal: AbortSignal | undefined, timeoutMs: number) {
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    const onAbort = () => controller.abort();
    if (signal?.aborted) controller.abort();
    signal?.addEventListener("abort", onAbort, { once: true });
    return {
      signal: controller.signal,
      timedOut: () => timedOut,
      clear: () => {
        clearTimeout(timer);
        signal?.removeEventListener("abort", onAbort);
      },
    };
  }
  
  export function fetchFailure(timedOut: boolean, callerAborted: boolean, timeoutMs: number): ApiError {
    if (timedOut) return new ApiError("timeout", `No response from the backend after ${Math.round(timeoutMs / 1000)} s.`);
    if (callerAborted) return new ApiError("aborted", "Request cancelled.");
    return new ApiError("network", `Can't reach the backend at ${API_URL}.`);
  }
  
  async function request<T>(
    path: string,
    {
      query,
      method = "GET",
      body,
      signal,
      timeoutMs = DEFAULT_TIMEOUT_MS,
    }: RequestOptions & { query?: Query; method?: "GET" | "POST"; body?: unknown } = {},
  ): Promise<T> {
    const abort = linkedAbort(signal, timeoutMs);
    let res: Response;
    try {
      res = await fetch(buildUrl(path, query), {
        method,
        signal: abort.signal,
        cache: "no-store",
        headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!res.ok) throw await errorFromResponse(res);
      return (await res.json()) as T;
    } catch (e) {
      if (e instanceof ApiError) throw e;
      throw fetchFailure(abort.timedOut(), Boolean(signal?.aborted), timeoutMs);
    } finally {
      abort.clear();
    }
  }
  
  // ------------------------------------------------------------ endpoints
  
  export const api = {
    health: (o?: RequestOptions) => request<Health>("/health", o),
  
    habitats: (o?: RequestOptions) => request<Habitat[]>("/habitats", o),
  
    insights: (habitat?: HabitatSlug | null, o?: RequestOptions) =>
      request<Insight[]>("/insights", { ...o, query: { habitat } }),
  
    tests: (q: TestsQuery = {}, o?: RequestOptions) => request<TestsPage>("/tests", { ...o, query: q }),
  
    facets: (o?: RequestOptions) => request<Facets>("/tests/facets", o),
  
    investigations: (o?: RequestOptions) => request<InvestigationSummary[]>("/investigations", o),
  
    investigation: (psiId: string, o?: RequestOptions) =>
      request<InvestigationDetail>(`/investigations/${encodeURIComponent(psiId)}`, o),
  
    coverage: (habitat: HabitatSlug, perExperiment?: number, o?: RequestOptions) =>
      request<Coverage>("/coverage", { ...o, query: { habitat, per_experiment: perExperiment } }),
  
    suggested: (habitat?: HabitatSlug | null, o?: RequestOptions) =>
      request<Suggested[]>("/ask/suggested", { ...o, query: { habitat } }),
  
    // Non-streaming /ask. The Ask page uses askStream (lib/sse.ts) instead.
    ask: (req: AskRequest, o?: RequestOptions) =>
      request<AskFinal>("/ask", { timeoutMs: 120_000, ...o, method: "POST", body: { ...req, stream: false } }),
  };