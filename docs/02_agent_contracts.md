# 2. Agent Contract Reference

Principle: **one role = one job = one output contract.** Every contract is a pydantic v2 model in `src/contracts.py`; the generated JSON Schemas are in `docs/schemas/` (`python -m src.tools.export_schemas`). Every consumer re-validates its input with `guardrails.validate_handoff()`; a violation raises `ContractViolation`, is logged, and triggers the retry path.

## Shared building blocks

| Type | Fields | Purpose |
|---|---|---|
| `Grounded` (mixin) | `brd_refs[]`, `citations[]`, `assumption?` | Every claim says which requirement it serves and which retrieved chunk supports it. Used by the Critic for groundedness, completeness and hallucination checks. |
| `Flag` | `id, kind (ambiguity · contradiction · missing_section · feasibility · injection · pii · scope), severity, message, brd_refs[], resolution?` | Issues are surfaced, never silently resolved. `resolution` records the conservative default applied. |

## Who produces / consumes what

| # | Agent | Output contract | Consumed by | Key validators (beyond types) |
|---|---|---|---|---|
| – | `brd_parser` tool | `ParsedBRD` | all agents | ≥3 requirements; unique requirement IDs |
| 1 | Orchestrator | `RoutingDecision` | all specialists | only known agent names in `routes`; complexity 1–5 |
| 2 | Plan Generator | `EngineeringPlan` | Schedule, PoC, Critic, exporters | ≥2 phases, every phase has ≥1 deliverable and ≥1 exit criterion; milestones reference existing phases |
| 3 | Schedule Estimator | `Schedule` | PoC, Tech Stack, Critic | durations > 0; phases end after they start; `total_duration_weeks` equals the last phase's end week |
| 4 | Solution Architect | `Architecture` | PoC, Tech Stack, Critic | ≥2 components; data flows and NFR mappings only reference existing components; pattern justified vs ≥1 alternative |
| 5 | PoC Planner | `PoCPlan` | Critic, Jira export | ≥1 success criterion; duration ≤ 8 weeks |
| 6 | Tech Stack Recommender | `TechStackRecommendation` | Critic, exporters | 2–3 options; recommended id must be one of them; scores 1–5 |
| 7 | Critic | `CriticReport` | Orchestrator (revision loop), dashboard | decision ∈ pass/revise/escalate |

## Contract details

### `ParsedBRD` (Layer 1)
`brd_id`, `content_hash` (SHA-256, used in logs instead of content), `title`, `domain`, `classification`, `objectives[]`, `in_scope[]`, `out_of_scope[]`, `requirements[Requirement]`, `constraints{deadline_weeks, team_size, budget, deployment}`, `stakeholders[]`, `success_metrics[]`, `open_questions[]`, `sections_found[]`, `missing_sections[]`, `flags[Flag]`.

`Requirement`: `id` (from the BRD or auto-assigned `FR-A01`), `text`, `section`, `category` (functional · non_functional · integration · constraint · data), `subcategory` (performance, security, workflow, ingestion …), `priority` (must · should · could), `ambiguous_terms[]`.

### 1 · `RoutingDecision`
`brd_id`, `complexity_estimate` (1–5), `routes{agent: [requirement ids]}`, `workflows[]`, `escalations[flag ids]`, `rationale`.

### 2 · `EngineeringPlan`
`template_used`, `phases[Phase{id, name, objective, effort_share_pct, deliverables[], exit_criteria[], +Grounded}]`, `milestones[Milestone{id, name, phase_id, acceptance, +Grounded}]`, `risks[Risk{id, description, likelihood, impact, mitigation, owner_role, +Grounded}]`, `team[TeamRole{role, count, justification, +Grounded}]`, `assumptions[]`, `flags[]`, `reflection{checks_run[], issues_found[], changes_made[]}`.
*Reflection pattern:* after drafting, the agent re-checks Must coverage, exit criteria, risk owners and headcount, fixes issues and records them in `reflection`.

### 3 · `Schedule`
`phase_estimates[PhaseEstimate{phase_id, effort_person_weeks, duration_weeks, start_week, end_week, roles[], basis, +Grounded}]`, `total_duration_weeks` (p50), `p80_duration_weeks`, `total_effort_person_weeks`, `headcount`, `complexity_basis`, `analogs[Analog{project_id, chunk_id, complexity, actual_weeks, team_size, variance_pct, req_count}]`, `deadline_weeks`, `fits_deadline`, `assumptions[]`, `flags[]`.

### 4 · `Architecture`
`pattern{pattern_id, name, rationale, alternatives_considered[], +Grounded}`, `components[Component{id, name, responsibility, category, kind (feature · enabler), +Grounded}]`, `data_flows[{source, target, description, mode sync/async}]`, `nfr_mapping[{nfr_id, mechanism, component_ids[], +Grounded}]`, `complexity_score`, `mermaid`, `assumptions[]`, `flags[]`.
*Scope rule:* a `feature` component must reference a BRD requirement; an `enabler` (CI/CD, observability, auth with no requirement) must cite an org standard.

### 5 · `PoCPlan`
`objective`, `hypotheses[]`, `in_scope_component_ids[]`, `out_of_scope[]`, `success_criteria[SuccessCriterion{id, metric, target, measurement, measurable, +Grounded}]`, `duration_weeks`, `modular_boundaries[]`, `go_no_go`, `citations[]`, `assumptions[]`, `flags[]`.

### 6 · `TechStackRecommendation`
`options[StackOption{id, name, components{category: technology}, scalability, team_familiarity, integration_risk, cost, weighted_score, pros[], cons[], on_approved_list, +Grounded}]` (2–3), `recommended_option_id`, `rationale`, `weights{}`, `tool_decisions[{tool, reason, query}]`, `assumptions[]`, `flags[]`.

### 7 · `CriticReport`
`revision_round`, `artifact_scores[ArtifactScore{artifact, groundedness_ratio, coverage_ratio, contradictions, actionability, scores{dimension: 1–5}, overall, below_threshold[], badge}]`, `issues[CriticIssue{id, code, dimension, severity, target_agent, target_items[], message, suggested_fix}]`, `cross_agent_checks{name: bool}`, `decision`, `agents_to_revise[]`, `overall_badge`, `overall_score`.

`CriticIssue.code` values and the agent behaviour they trigger:

| code | Raised when | Revision behaviour of the target agent |
|---|---|---|
| `uncited_claims` | groundedness < 75% | targeted retrieval with each listed claim as the query; cite or mark as assumption |
| `invalid_grounding` | citation to a chunk the agent never retrieved, unknown requirement id, or weak claim↔source similarity | same targeted re-grounding |
| `uncovered_requirements` | routed requirement ids not referenced by any item | map each to the most similar component / the build phase |
| `scope_creep` | feature without requirement, enabler without standard, or out-of-scope / injected term in a scope-bearing item | re-ground enabler with a standard; deferred requirements moved to an EM decision |
| `unmeasurable_criteria` | any PoC criterion without a numeric target | quantify conservatively from org default SLOs and record the assumption |
| `complexity_mismatch` | schedule complexity basis < architecture complexity | re-select analogs at the architecture's complexity / pattern |
| `template_mismatch` | plan template does not fit the architecture complexity | re-plan with the matching template (e.g. T2 adds PoC + performance phases) |
| `headcount_mismatch`, `phase_mismatch`, `duration_below_analogs`, `poc_unknown_components`, `poc_too_long`, `missing_category`, `familiarity_risk`, `deployment_conflict` | cross-agent consistency failures | re-estimate / re-scope / re-weight accordingly |

## Contract violation handling

1. Producer output is validated by pydantic inside `LLMClient.generate` (LLM mode: validation errors are fed back into a re-prompt, up to 2 retries; then heuristic fallback).
2. The Orchestrator re-validates at the hand-off (`validate_handoff`) before storing the artifact.
3. A violation is logged as `contract_violation {producer, consumer, attempt, errors}`; the agent is retried (max 2).
4. If it still fails, the run stops with `failed:<agent>` rather than passing an invalid artifact downstream.
