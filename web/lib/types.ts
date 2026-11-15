// Mirrors backend/api/schemas.py (the API contract). If they disagree, schemas.py wins:
// fix this file to match it.

// ------------------------------------------------------------ habitats

export type HabitatSlug = "iss" | "gateway" | "lunar" | "apollo1";
export const HABITAT_SLUGS: readonly HabitatSlug[] = ["iss", "gateway", "lunar", "apollo1"];

export interface Health {
  status: "ok" | "degraded";
  version: string;
  db: Record<string, number>;
  index: Record<string, unknown>;
  llm_chain: string[];
  warm: Record<string, string>;
  warm_s: number | null;
  uptime_s: number | null;
}

export interface Habitat {
  slug: HabitatSlug;
  name: string;
  kind: "current" | "proposed" | "historical";
  pressure_psia: number | null;
  pressure_kpa: number;
  o2_frac: number;
  pp_o2_kpa: number;
  source: string | null;
  source_url: string | null;
  note: string | null;
}

// ------------------------------------------------------------ insights

export interface Source {
  psi_id: string;
  acronym?: string | null;
  title?: string | null;
  doi?: string | null;
  doi_url?: string | null;
}

export interface Insight {
  id: string;
  rank: number;
  title: string;
  value: number | string | null;
  unit: string | null;
  explanation: string | null;
  sql: string;
  source_psi_ids: string[];
  habitats: string[] | null;
  detail: Record<string, unknown> | string | null;
  sources: Source[];
}

// ------------------------------------------------------------ tests

export type Outcome =
  | "extinction"
  | "completion"
  | "disruption"
  | "self_extinguished"
  | "flow_terminated"
  | "no_ignition";

export type TestExtra = Record<string, unknown> & {
  row_kind?: "summary" | null;
  source_file?: string;
  source_row?: number;
  raw?: Record<string, unknown>;
};

export interface TestRow {
  test_pk: number;
  psi_id: string;
  experiment: string;
  test_id: string | null;
  fuel: string | null;
  material: string | null;
  pressure_kpa: number | null;
  o2_frac: number | null;
  diluent: string | null;
  diluent_frac: number | null;
  flow_cm_s: number | null;
  outcome: string | null;
  burn_time_s: number | null;
  spread_rate_mm_s: number | null;
  extra: TestExtra;
}

export interface TestsPage {
  total: number;
  limit: number;
  offset: number;
  rows: TestRow[];
}

// a type alias (not an interface) so it fits the generic query-string builder
export type TestsQuery = {
  experiment?: string[];
  psi_id?: string[];
  outcome?: string[];
  fuel?: string;
  p_min?: number;
  p_max?: number;
  o2_min?: number; // fraction 0 to 1
  o2_max?: number;
  single_only?: boolean;
  include_duplicates?: boolean;
  include_raw?: boolean;
  limit?: number; // 1 to 1000
  offset?: number;
};

export interface FacetExperiment {
  experiment: string;
  psi_id: string;
  n: number;
  n_outcome: number;
  n_conditions: number;
  n_summary: number;
}

export interface Facets {
  experiments: FacetExperiment[];
  outcomes: { outcome: string; n: number }[];
  fuels: { fuel: string; n: number }[];
  ranges: { p_min: number | null; p_max: number | null; o2_min: number | null; o2_max: number | null };
}

// ------------------------------------------------------------ investigations

export interface InvestigationSummary {
  psi_id: string;
  acronym: string | null; // null for ground studies: label by title
  title: string;
  project_type: string | null;
  mission_name: string | null;
  doi: string | null;
  doi_url: string | null;
  n_publications: number | null;
  n_tests: number;
}

export interface InvestigationFull {
  psi_id: string;
  acronym: string | null;
  title: string;
  doi: string | null;
  doi_url: string | null;
  objective: string | null;
  approach: string | null;
  hypothesis?: string | null;
  research_impacts?: string | null;
  hardware?: string | null;
  description?: string | null;
  project_type?: string | null;
  mission_name?: string | null;
}

export interface TestStats {
  n_rows: number;
  n_single_tests: number;
  p_min_kpa: number | null;
  p_max_kpa: number | null;
  o2_min: number | null;
  o2_max: number | null;
  top_fuels: { fuel: string; n: number }[];
  outcomes: Record<string, number>;
}

export interface Publication {
  pub_id: string | number;
  title: string | null;
  authors: string | null;
  doi: string | null;
  doi_url: string | null;
  has_abstract: boolean;
}

export interface InvestigationDetail {
  investigation: InvestigationFull;
  cite_as: string;
  tests: TestStats;
  publications: Publication[];
}

// ------------------------------------------------------------ coverage

export type Verdict = "well_covered" | "sparse" | "near_only" | "untested";

export interface Target {
  pressure_kpa: number;
  o2_frac: number;
  pp_o2_kpa: number;
}

export interface CoverageSummary {
  n_tested: number;
  n_in_box: number;
  n_in_box_incl_duplicates: number;
  nearest_distance: number;
  verdict: Verdict;
  note: string;
}

export interface NearRow {
  test_pk: number;
  test_id: string | null;
  pressure_kpa: number;
  o2_frac: number;
  outcome: string | null;
  distance: number;
  fuel?: string | null;
  pp_o2_kpa?: number;
  d_pressure_pct?: number;
  d_o2_pts?: number;
}

export interface CoverageExperiment {
  psi_id: string;
  experiment: string;
  n_tested: number;
  n_in_box: number;
  nearest_distance: number;
  far: boolean;
  tested_range: { pressure_kpa: [number | null, number | null]; o2_frac: [number | null, number | null] };
  outcomes_in_box: Record<string, number>;
  nearest: NearRow[];
}

export interface CoveragePoint {
  psi_id: string;
  experiment: string;
  pressure_kpa: number;
  o2_frac: number;
  outcome: string | null;
  row_kind: string | null;
  in_box: boolean;
}

export interface Coverage {
  habitat: Habitat;
  target: Target;
  tolerance: { pressure_rel: number; o2_abs: number; far: number };
  summary: CoverageSummary;
  experiments: CoverageExperiment[];
  points: CoveragePoint[];
}

// ------------------------------------------------------------ ask

export interface AskRequest {
  question: string; // 3 to 500 chars
  habitat?: HabitatSlug | null;
  fresh?: boolean; // true skips the demo cache (costs tokens)
}

export interface Citation {
  id: string; // PSI-98 or NASA:apollo_1
  kind: "investigation" | "context";
  label: string;
  title: string | null;
  doi: string | null;
  url: string | null;
  known: boolean;
  verified: boolean;
}

export interface SqlRun {
  sql: string | null;
  error: string | null;
  columns: string[] | null;
  rows: unknown[][];
  row_count: number | null;
  truncated: boolean | null;
  original_sql?: string | null;
  auto_fixed?: string[] | null;
}

export interface Passage {
  chunk_id: string;
  source_type: string;
  psi_id: string | null;
  score: number;
  text: string;
  experiment?: string | null;
  field?: string | null;
  title?: string | null;
  doi?: string | null;
  psi_doi?: string | null;
  url?: string | null;
  pages?: string | number[] | null;
}

export type ToolName = "query_tests" | "search_docs" | "get_investigation" | "nearest_conditions";

export interface Step {
  tool: ToolName | string;
  args: Record<string, unknown> | null;
  summary: string;
}

export interface NumberCheck {
  value: string;
  cited: string[];
  source: string | null;
  ok: boolean;
}

export interface Grounding {
  numbers_checked: number;
  numbers: NumberCheck[];
  unverified: string[];
  misattributed: string[];
  ok: boolean | null;
}

export interface LlmTraceEntry {
  model: string;
  ok: boolean;
  prompt_tokens?: number;
  completion_tokens?: number;
  latency_s?: number;
  finish?: string;
  error?: string;
  kind?: "TPM" | "ITPM" | "OTPM" | "TPD";
  [key: string]: unknown;
}

export interface AskFinal {
  question: string;
  habitat: HabitatSlug | null;
  answer: string; // markdown with [PSI-69] style citations
  citations: Citation[];
  citations_added?: { id: string; sentence: string }[];
  sql_run: SqlRun[];
  passages: Passage[];
  steps: Step[];
  grounding: Grounding;
  answer_truncated: boolean;
  model: string | null;
  models_failed: Record<string, unknown>[];
  llm_calls: number;
  usage: Record<string, number>;
  llm_trace: LlmTraceEntry[];
  elapsed_s: number;
  cached: boolean;
  cached_at: string | null;
}

export interface Suggested {
  question: string;
  habitat: HabitatSlug | null;
  model: string | null;
  cached_at: string | null;
}

// ------------------------------------------------------------ SSE events from POST /ask

export type AskStatus =
  | { stage: "thinking"; turn: number }
  | { stage: "rate_limited"; model: string; wait_s: number }
  | { stage: "model_switch"; from: string; reason: string };

export type AskEvent =
  | { event: "start"; data: { question: string; habitat: HabitatSlug | null } }
  | { event: "status"; data: AskStatus }
  | { event: "tool_call"; data: { tool: ToolName; args: Record<string, unknown> | null; model: string } }
  | { event: "tool_result"; data: { tool: ToolName; summary: string } }
  | { event: "token"; data: { text: string } }
  | { event: "final"; data: AskFinal }
  | { event: "error"; data: { message: string } };