import type { Habitat, HabitatSlug, Verdict } from "@/lib/types";
import { HABITAT_SLUGS } from "@/lib/types";

export const DEFAULT_HABITAT: HabitatSlug = "lunar";

export function isHabitatSlug(v: string | null | undefined): v is HabitatSlug {
  return !!v && (HABITAT_SLUGS as readonly string[]).includes(v);
}

export function fmtNumber(v: number): string {
  return v.toLocaleString("en-US", { maximumFractionDigits: Math.abs(v) >= 100 ? 0 : 1 });
}

// 0.265 -> "26.5%", 0.21 -> "21%"
export function fmtPct(frac: number | null | undefined): string {
  if (frac == null) return "n/a";
  return `${(frac * 100).toLocaleString("en-US", { maximumFractionDigits: 1 })}%`;
}

export function fmtKpa(v: number | null | undefined): string {
  if (v == null) return "n/a";
  return `${v.toLocaleString("en-US", { maximumFractionDigits: 1 })} kPa`;
}

export function formatValue(value: number | string | null, unit: string | null): string {
  if (value == null) return "n/a";
  const s = typeof value === "number" ? fmtNumber(value) : value;
  if (!unit) return s;
  if (unit === "%") return `${s}%`;
  if (unit === "x" || unit === "×") return `${s}x`;
  return `${s} ${unit}`;
}

const OUTCOME_LABELS: Record<string, string> = {
  extinction: "went out early",
  completion: "burned away",
  disruption: "broke apart",
  self_extinguished: "self-extinguished",
  flow_terminated: "still burning at flow stop",
  no_ignition: "no ignition",
};

export function outcomeLabel(outcome: string | null): string {
  if (!outcome) return "not recorded";
  return OUTCOME_LABELS[outcome] ?? outcome.replace(/_/g, " ");
}

export const KIND_LABEL: Record<Habitat["kind"], string> = {
  current: "In service",
  proposed: "Proposed",
  historical: "Historical",
};

export const VERDICT: Record<Verdict, { label: string; className: string }> = {
  well_covered: { label: "Well covered", className: "border-success/40 bg-success/10 text-success" },
  sparse: { label: "Sparse data", className: "border-warning/40 bg-warning/10 text-warning" },
  near_only: { label: "Nearby tests only", className: "border-warning/40 bg-warning/10 text-warning" },
  untested: { label: "Untested", className: "border-destructive/40 bg-destructive/10 text-destructive" },
};

// Insight units are descriptive ("x fewer tests", "share of tests", "O2 fraction").
// Split them into a big number with a real unit plus a small caption.
export function insightValue(value: number | string | null, unit: string | null): { big: string; caption: string | null } {
    const u = (unit ?? "").trim();
    if (value == null) return { big: "n/a", caption: u || null };
    if (typeof value === "string") return { big: value, caption: u || null };
  
    if (/^(x|×)(\s|$)/i.test(u)) {
      return { big: `${fmtNumber(value)}x`, caption: u.replace(/^(x|×)\s*/i, "") || null };
    }
    if (u === "%") return { big: `${fmtNumber(value)}%`, caption: null };
    if (/share|fraction|frac/i.test(u) && value >= 0 && value <= 1) {
      const pct = (value * 100).toLocaleString("en-US", { maximumFractionDigits: 0 });
      return { big: `${pct}%`, caption: u.replace(/\s*fraction\s*/i, " ").trim() || null };
    }
    return { big: fmtNumber(value), caption: u || null };
}

// Order for the outcome strip: most dangerous at the top.
export const OUTCOME_ORDER = [
  "flow_terminated",
  "completion",
  "disruption",
  "self_extinguished",
  "extinction",
  "no_ignition",
] as const;

const OUTCOME_COLOR: Record<string, string> = {
  flow_terminated: "var(--primary)", // still burning: the danger color
  completion: "var(--chart-5)",
  disruption: "var(--chart-4)",
  self_extinguished: "var(--chart-3)",
  extinction: "var(--chart-2)",
  no_ignition: "var(--muted-foreground)",
};

export function outcomeColor(outcome: string | null): string {
  return (outcome && OUTCOME_COLOR[outcome]) || "var(--muted-foreground)";
}

export function fmtRange(
  a: number | null | undefined,
  b: number | null | undefined,
  fmt: (v: number) => string,
): string {
  if (a == null || b == null) return "n/a";
  return a === b ? fmt(a) : `${fmt(a)} to ${fmt(b)}`;
}

export const HABITAT_SHORT: Record<HabitatSlug, string> = {
  iss: "ISS",
  gateway: "Gateway",
  lunar: "Lunar / Mars",
  apollo1: "Apollo 1",
};

export function fmtSeconds(s: number | null | undefined): string {
  return s == null ? "n/a" : `${s.toFixed(1)} s`;
}