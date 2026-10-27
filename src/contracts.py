"""Output contracts (JSON schemas) for every agent hand-off.

Principle: one role = one job = one output contract. Every model below is
validated with pydantic at the hand-off boundary (see guardrails.validate_handoff).
`model_json_schema()` of each model is exported to docs/schemas/ by
`python -m src.tools.export_schemas`.
"""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

Priority = Literal["must", "should", "could"]
Severity = Literal["low", "medium", "high"]
Badge = Literal["GREEN", "AMBER", "RED"]


# --------------------------------------------------------------------------- #
# Shared building blocks
# --------------------------------------------------------------------------- #
class Grounded(BaseModel):
    """Mixin for any generated claim: what BRD requirement it serves and which
    retrieved knowledge-base chunks support it."""
    brd_refs: list[str] = Field(default_factory=list, description="Requirement IDs from the parsed BRD")
    citations: list[str] = Field(default_factory=list, description="chunk_ids retrieved from the knowledge base")
    assumption: Optional[str] = Field(None, description="Documented assumption when the BRD is silent/ambiguous")


class Flag(BaseModel):
    id: str
    kind: Literal["ambiguity", "contradiction", "missing_section", "feasibility", "injection", "pii", "scope"]
    severity: Severity
    message: str
    brd_refs: list[str] = Field(default_factory=list)
    resolution: Optional[str] = Field(None, description="Conservative default applied, if any")


# --------------------------------------------------------------------------- #
# Layer 1: BRD ingestion (output of the brd_parser tool)
# --------------------------------------------------------------------------- #
class Requirement(BaseModel):
    id: str
    text: str
    section: str
    category: Literal["functional", "non_functional", "integration", "constraint", "data"]
    subcategory: str = "general"
    priority: Priority = "must"
    ambiguous_terms: list[str] = Field(default_factory=list)


class Constraints(BaseModel):
    deadline_weeks: Optional[float] = None
    team_size: Optional[int] = None
    budget: Optional[str] = None
    deployment: Optional[str] = None  # "aws" | "on-prem" | "azure" | ...


class ParsedBRD(BaseModel):
    brd_id: str
    content_hash: str
    title: str
    domain: str
    classification: str = "internal"
    objectives: list[str] = Field(default_factory=list)
    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    requirements: list[Requirement]
    constraints: Constraints = Field(default_factory=Constraints)
    stakeholders: list[str] = Field(default_factory=list)
    success_metrics: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    sections_found: list[str] = Field(default_factory=list)
    missing_sections: list[str] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)

    @field_validator("requirements")
    @classmethod
    def _non_empty(cls, v):
        if len(v) < 3:
            raise ValueError("a BRD must contain at least 3 requirements")
        ids = [r.id for r in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate requirement IDs")
        return v

    def req(self, rid: str) -> Optional[Requirement]:
        return next((r for r in self.requirements if r.id == rid), None)

    @property
    def req_ids(self) -> set[str]:
        return {r.id for r in self.requirements}


# --------------------------------------------------------------------------- #
# Agent 1: Orchestrator
# --------------------------------------------------------------------------- #
class RoutingDecision(BaseModel):
    brd_id: str
    complexity_estimate: int = Field(ge=1, le=5)
    routes: dict[str, list[str]] = Field(description="agent name -> requirement IDs it must address")
    workflows: list[str]
    escalations: list[str] = Field(default_factory=list, description="flag IDs raised to the EM before generation")
    rationale: str

    @field_validator("routes")
    @classmethod
    def _agents_known(cls, v):
        known = {"plan_generator", "schedule_estimator", "solution_architect", "poc_planner", "tech_stack_recommender"}
        unknown = set(v) - known
        if unknown:
            raise ValueError(f"unknown agents in routing: {unknown}")
        return v


# --------------------------------------------------------------------------- #
# Agent 2: Engineering Plan Generator
# --------------------------------------------------------------------------- #
class Phase(Grounded):
    id: str
    name: str
    objective: str
    effort_share_pct: float = Field(ge=0, le=100)
    deliverables: list[str] = Field(min_length=1)
    exit_criteria: list[str] = Field(min_length=1)


class Milestone(Grounded):
    id: str
    name: str
    phase_id: str
    acceptance: str


class Risk(Grounded):
    id: str
    description: str
    likelihood: Severity
    impact: Severity
    mitigation: str
    owner_role: str


class TeamRole(Grounded):
    role: str
    count: int = Field(ge=1)
    justification: str


class Reflection(BaseModel):
    checks_run: list[str]
    issues_found: list[str]
    changes_made: list[str]


class EngineeringPlan(BaseModel):
    template_used: str
    phases: list[Phase] = Field(min_length=2)
    milestones: list[Milestone] = Field(min_length=1)
    risks: list[Risk] = Field(min_length=1)
    team: list[TeamRole] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    reflection: Optional[Reflection] = None

    @model_validator(mode="after")
    def _milestones_reference_phases(self):
        pids = {p.id for p in self.phases}
        bad = [m.id for m in self.milestones if m.phase_id not in pids]
        if bad:
            raise ValueError(f"milestones reference unknown phases: {bad}")
        return self

    @property
    def headcount(self) -> int:
        return sum(t.count for t in self.team)


# --------------------------------------------------------------------------- #
# Agent 3: Schedule Estimator
# --------------------------------------------------------------------------- #
class PhaseEstimate(Grounded):
    phase_id: str
    effort_person_weeks: float = Field(gt=0)
    duration_weeks: float = Field(gt=0)
    start_week: float = Field(ge=0)
    end_week: float = Field(gt=0)
    roles: list[str] = Field(default_factory=list)
    basis: str


class Analog(BaseModel):
    project_id: str
    chunk_id: str
    complexity: int
    actual_weeks: float
    team_size: int
    variance_pct: float
    req_count: int = 0


class Schedule(BaseModel):
    phase_estimates: list[PhaseEstimate] = Field(min_length=1)
    total_duration_weeks: float
    p80_duration_weeks: float
    total_effort_person_weeks: float
    headcount: int
    complexity_basis: int = Field(ge=1, le=5)
    analogs: list[Analog] = Field(default_factory=list)
    deadline_weeks: Optional[float] = None
    fits_deadline: Optional[bool] = None
    assumptions: list[str] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _monotonic(self):
        prev_end = 0.0
        for pe in self.phase_estimates:
            if pe.end_week < pe.start_week:
                raise ValueError(f"phase {pe.phase_id} ends before it starts")
            prev_end = max(prev_end, pe.end_week)
        if abs(prev_end - self.total_duration_weeks) > 0.51:
            raise ValueError("total_duration_weeks must equal the last phase end_week")
        return self


# --------------------------------------------------------------------------- #
# Agent 4: Solution Architect
# --------------------------------------------------------------------------- #
class PatternChoice(Grounded):
    pattern_id: str
    name: str
    rationale: str
    alternatives_considered: list[str] = Field(min_length=1)


class Component(Grounded):
    id: str
    name: str
    responsibility: str
    category: Literal["frontend", "api", "service", "worker", "database", "cache", "messaging",
                      "stream-processing", "search", "integration", "auth", "observability", "storage", "analytics"]
    kind: Literal["feature", "enabler"] = "feature"


class DataFlow(BaseModel):
    source: str
    target: str
    description: str
    mode: Literal["sync", "async"]


class NFRMapping(Grounded):
    nfr_id: str
    mechanism: str
    component_ids: list[str] = Field(min_length=1)


class Architecture(BaseModel):
    pattern: PatternChoice
    components: list[Component] = Field(min_length=2)
    data_flows: list[DataFlow] = Field(min_length=1)
    nfr_mapping: list[NFRMapping] = Field(default_factory=list)
    complexity_score: int = Field(ge=1, le=5)
    mermaid: str
    assumptions: list[str] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _flows_reference_components(self):
        cids = {c.id for c in self.components}
        for f in self.data_flows:
            if f.source not in cids or f.target not in cids:
                raise ValueError(f"data flow {f.source}->{f.target} references unknown component")
        for m in self.nfr_mapping:
            missing = set(m.component_ids) - cids
            if missing:
                raise ValueError(f"NFR mapping {m.nfr_id} references unknown components {missing}")
        return self


# --------------------------------------------------------------------------- #
# Agent 5: PoC Planner
# --------------------------------------------------------------------------- #
class SuccessCriterion(Grounded):
    id: str
    metric: str
    target: str
    measurement: str
    measurable: bool


class PoCPlan(BaseModel):
    objective: str
    hypotheses: list[str] = Field(min_length=1)
    in_scope_component_ids: list[str] = Field(min_length=1)
    out_of_scope: list[str] = Field(default_factory=list)
    success_criteria: list[SuccessCriterion] = Field(min_length=1)
    duration_weeks: float = Field(gt=0, le=8)
    modular_boundaries: list[str] = Field(default_factory=list)
    go_no_go: str
    citations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Agent 6: Tech Stack Recommender
# --------------------------------------------------------------------------- #
class StackOption(Grounded):
    id: str
    name: str
    components: dict[str, str] = Field(description="component category -> technology")
    scalability: int = Field(ge=1, le=5)
    team_familiarity: int = Field(ge=1, le=5)
    integration_risk: int = Field(ge=1, le=5, description="5 = highest risk")
    cost: int = Field(ge=1, le=5, description="5 = most expensive")
    weighted_score: float
    pros: list[str] = Field(min_length=1)
    cons: list[str] = Field(min_length=1)
    on_approved_list: bool


class ToolDecision(BaseModel):
    tool: str
    reason: str
    query: str


class TechStackRecommendation(BaseModel):
    options: list[StackOption] = Field(min_length=2, max_length=3)
    recommended_option_id: str
    rationale: str
    weights: dict[str, float]
    tool_decisions: list[ToolDecision] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _rec_exists(self):
        if self.recommended_option_id not in {o.id for o in self.options}:
            raise ValueError("recommended_option_id must be one of the options")
        return self


# --------------------------------------------------------------------------- #
# Agent 7: Critic
# --------------------------------------------------------------------------- #
Dimension = Literal["groundedness", "completeness", "consistency", "actionability"]


class CriticIssue(BaseModel):
    id: str
    code: str = Field(description="machine-readable issue type, e.g. uncovered_requirements, uncited_claims")
    dimension: Dimension
    severity: Severity
    target_agent: str
    target_items: list[str] = Field(default_factory=list)
    message: str
    suggested_fix: str


class ArtifactScore(BaseModel):
    artifact: str
    groundedness_ratio: float
    coverage_ratio: float
    contradictions: int
    actionability: float
    scores: dict[str, float]  # 1-5 per dimension
    overall: float
    below_threshold: list[Dimension]
    badge: Badge


class CriticReport(BaseModel):
    revision_round: int
    artifact_scores: list[ArtifactScore]
    issues: list[CriticIssue]
    cross_agent_checks: dict[str, bool]
    decision: Literal["pass", "revise", "escalate"]
    agents_to_revise: list[str]
    overall_badge: Badge
    overall_score: float


AGENT_OUTPUT_MODELS = {
    "orchestrator": RoutingDecision,
    "plan_generator": EngineeringPlan,
    "schedule_estimator": Schedule,
    "solution_architect": Architecture,
    "poc_planner": PoCPlan,
    "tech_stack_recommender": TechStackRecommendation,
    "critic": CriticReport,
}
