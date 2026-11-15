// Same patterns as backend/ignitiq/agent.py (CITATION_RE, CITATION_ID_RE), documented in docs/api.md.
// (?!\() skips real markdown links like [text](url).
const CITATION_RE = /\[([^[\]]{2,120})\](?!\()/g;
const CITATION_ID_RE = /^(PSI-\d+|NASA:[a-z0-9_]+)$/;
const SPLIT_RE = /[,;]\s*/;

export const CITE_PREFIX = "#cite:";

// "PSI-69, NASA:guide_2015" -> ["PSI-69", "NASA:guide_2015"], or null if any part isn't a valid id
export function splitIds(group: string): string[] | null {
  const ids = group
    .split(SPLIT_RE)
    .map((s) => s.trim())
    .filter(Boolean);
  return ids.length > 0 && ids.every((id) => CITATION_ID_RE.test(id)) ? ids : null;
}

// [PSI-69, NASA:guide_2015] -> [PSI-69](#cite:PSI-69) [NASA:guide_2015](#cite:NASA:guide_2015)
export function linkifyCitations(md: string): string {
  return md.replace(CITATION_RE, (whole, inner: string) => {
    const ids = splitIds(inner);
    if (!ids) return whole;
    return ids.map((id) => `[${id}](${CITE_PREFIX}${id})`).join(" ");
  });
}

export function citeIdFromHref(href?: string): string | null {
  return href?.startsWith(CITE_PREFIX) ? decodeURIComponent(href.slice(CITE_PREFIX.length)) : null;
}