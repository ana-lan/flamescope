"""Response models: the API contract. Endpoints declare these as response_model, and the
contract test validates live responses against them. docs/api.md describes the same shapes.

extra="allow": required fields are enforced, additional fields pass through untouched.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from ignitiq import conditions

HABITAT_SLUGS = tuple(h["slug"] for h in conditions.list_habitats())
HabitatSlug = Literal[HABITAT_SLUGS]  # Literal["iss", "gateway", "lunar", "apollo1"] from the database


class Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------- meta and habitats

class Health(Loose):
    status: Literal["ok", "degraded"]
    version: str
    db: dict[str, int]
    index: dict[str, Any]
    llm_chain: list[str]
    warm: dict[str, str]
    warm_s: float | None
    uptime_s: float | None


class Habitat(Loose):
    slug: str
    name: str
    kind: str
    pressure_psia: float | None
    pressure_kpa: float
    o2_frac: float
    pp_o2_kpa: float
    source: str | None
    source_url: str | None
    note: str | None


# ---------------------------------------------------------------- insights

class Source(Loose):
    psi_id: str
    acronym: str | None = None
    title: str | None = None
    doi: str | None = None
    doi_url: str | None = None


class Insight(Loose):
    id: str
    rank: int
    title: str
    value: float | str | None
    unit: str | None
    explanation: str | None
    sql: str
    source_psi_ids: list[str]
    habitats: list[str] | None
    detail: dict[str, Any] | str | None
    sources: list[Source]


# ---------------------------------------------------------------- tests

class TestRow(Loose):
    test_pk: int
    psi_id: str
    experiment: str
    test_id: str | None
    fuel: str | None
    material: str | None
    pressure_kpa: float | None
    o2_frac: float | None
    diluent: str | None
    diluent_frac: float | None
    flow_cm_s: float | None
    outcome: str | None
    burn_time_s: float | None
    spread_rate_mm_s: float | None
    extra: dict[str, Any]


class TestsPage(Loose):
    total: int
    limit: int
    offset: int
    rows: list[TestRow]


class FacetExperiment(Loose):
    experiment: str
    psi_id: str
    n: int
    n_outcome: int
    n_conditions: int
    n_summary: int


class FacetOutcome(Loose):
    outcome: str
    n: int


class FacetFuel(Loose):
    fuel: str
    n: int


class Facets(Loose):
    experiments: list[FacetExperiment]
    outcomes: list[FacetOutcome]
    fuels: list[FacetFuel]
    ranges: dict[str, float | None]


# ---------------------------------------------------------------- investigations

class InvestigationSummary(Loose):
    psi_id: str
    acronym: str | None
    title: str
    project_type: str | None
    mission_name: str | None
    doi: str | None
    doi_url: str | None
    n_publications: int | None
    n_tests: int


class InvestigationFull(Loose):
    psi_id: str
    acronym: str | None
    title: str
    doi: str | None
    doi_url: str | None
    objective: str | None
    approach: str | None


class TestStats(Loose):
    n_rows: int
    n_single_tests: int
    p_min_kpa: float | None
    p_max_kpa: float | None
    o2_min: float | None
    o2_max: float | None
    top_fuels: list[dict[str, Any]]
    outcomes: dict[str, int]


class Publication(Loose):
    pub_id: str | int
    title: str | None
    authors: str | None
    doi: str | None
    doi_url: str | None
    has_abstract: bool


class InvestigationDetail(Loose):
    investigation: InvestigationFull
    cite_as: str
    tests: TestStats
    publications: list[Publication]


# ---------------------------------------------------------------- coverage

class Target(Loose):
    pressure_kpa: float
    o2_frac: float
    pp_o2_kpa: float


class CoverageSummary(Loose):
    n_tested: int
    n_in_box: int
    n_in_box_incl_duplicates: int
    nearest_distance: float
    verdict: Literal["well_covered", "sparse", "near_only", "untested"]
    note: str


class NearRow(Loose):
    test_pk: int
    test_id: str | None
    pressure_kpa: float
    o2_frac: float
    outcome: str | None
    distance: float


class CoverageExperiment(Loose):
    psi_id: str
    experiment: str
    n_tested: int
    n_in_box: int
    nearest_distance: float
    far: bool
    tested_range: dict[str, list[float | None]]
    outcomes_in_box: dict[str, int]
    nearest: list[NearRow]


class Point(Loose):
    psi_id: str
    experiment: str
    pressure_kpa: float
    o2_frac: float
    outcome: str | None
    row_kind: str | None
    in_box: bool


class Coverage(Loose):
    habitat: Habitat
    target: Target
    tolerance: dict[str, float]
    summary: CoverageSummary
    experiments: list[CoverageExperiment]
    points: list[Point]


# ---------------------------------------------------------------- ask

class Citation(Loose):
    id: str
    kind: Literal["investigation", "context"]
    label: str
    title: str | None
    doi: str | None
    url: str | None
    known: bool
    verified: bool


class SqlRun(Loose):
    sql: str | None
    error: str | None
    columns: list[str] | None
    rows: list[list[Any]]
    row_count: int | None
    truncated: bool | None
    original_sql: str | None = None
    auto_fixed: list[str] | None = None


class Passage(Loose):
    chunk_id: str
    source_type: str
    psi_id: str | None
    score: float
    text: str


class Step(Loose):
    tool: str
    args: dict[str, Any] | None
    summary: str


class NumberCheck(Loose):
    value: str
    cited: list[str]
    source: str | None
    ok: bool


class Grounding(Loose):
    numbers_checked: int
    numbers: list[NumberCheck] = []
    unverified: list[str]
    misattributed: list[str] = []
    ok: bool | None = None


class AskFinal(Loose):
    question: str
    habitat: str | None
    answer: str
    citations: list[Citation]
    sql_run: list[SqlRun]
    passages: list[Passage]
    steps: list[Step]
    grounding: Grounding
    answer_truncated: bool
    model: str | None
    models_failed: list[dict[str, Any]]
    llm_calls: int
    usage: dict[str, int]
    llm_trace: list[dict[str, Any]] = []
    elapsed_s: float
    cached: bool
    cached_at: str | None = None


class Suggested(Loose):
    question: str
    habitat: str | None
    model: str | None
    cached_at: str | None