"""Agent 7 — Critic (Validation group).

Scores every Planning/Design artifact on four rubric dimensions, runs
cross-agent consistency checks and guardrail checks, and emits specific,
item-level feedback addressed to the originating agent. The Orchestrator uses
`decision`/`agents_to_revise` to drive the revision loop (max 2 cycles).

Rubric (1-5 per dimension; thresholds from the brief):
  groundedness  : share of claims with >=1 valid citation      (>= 75%  -> pass)
  completeness  : share of routed requirements addressed         (100%    -> pass)
  consistency   : cross-agent + BRD contradictions               (0       -> pass)
  actionability : judge score                                    (>= 4.0  -> pass)
Badges: GREEN all pass & overall >= 4.0; AMBER one below or overall 3.0-3.9;
RED two or more below or overall < 3.0.
"""
from __future__ import annotations

import re
from typing import Any

from ..config import ACTIONABILITY_MIN, COMPLETENESS_MIN, CONSISTENCY_MAX, GROUNDEDNESS_MIN, MAX_REVISIONS
from ..contracts import ArtifactScore, CriticIssue, CriticReport
from ..guardrails import check_grounding, iter_claims, out_of_scope_terms
from ..prompts import CRITIC_JUDGE
from .base import BaseAgent

ARTIFACTS = ["plan_generator", "schedule_estimator", "solution_architect", "poc_planner", "tech_stack_recommender"]
VERIFIABLE = re.compile(r"\d|sign-off|signed off|approved|accepted|pass|complete|deploys|met|verified|recorded|reviewed", re.I)


def score_ratio(r: float) -> float:
    return 5.0 if r >= 0.9 else 4.0 if r >= 0.75 else 3.0 if r >= 0.6 else 2.0 if r >= 0.4 else 1.0


def score_cov(r: float) -> float:
    return 5.0 if r >= 1.0 else 3.5 if r >= 0.9 else 3.0 if r >= 0.75 else 2.0 if r >= 0.5 else 1.0


def score_contra(n: int) -> float:
    return 5.0 if n == 0 else 3.0 if n == 1 else 2.0 if n == 2 else 1.0


def badge_for(below: list, overall: float) -> str:
    if len(below) >= 2 or overall < 3.0:
        return "RED"
    if len(below) == 1 or overall < 4.0:
        return "AMBER"
    return "GREEN"


def actionability(name: str, art: Any) -> tuple[float, list[str]]:
    """Heuristic actionability judge (1-5): share of items an EM can act on without follow-up."""
    fr, why = [], []

    def add(label, items, ok):
        items = list(items)
        if items:
            v = sum(1 for i in items if ok(i)) / len(items)
            fr.append(v)
            if v < 1:
                why.append(f"{label}: {v:.0%}")

    if name == "plan_generator":
        add("phases with verifiable exit criteria", art.phases, lambda p: any(VERIFIABLE.search(e) for e in p.exit_criteria))
        add("risks with mitigation+owner", art.risks, lambda r: len(r.mitigation) > 15 and bool(r.owner_role))
        add("milestones with acceptance", art.milestones, lambda m: len(m.acceptance) > 10)
        add("phases traceable to BRD or template", art.phases, lambda p: bool(p.brd_refs or p.citations))
    elif name == "schedule_estimator":
        add("estimates with roles", art.phase_estimates, lambda e: bool(e.roles))
        add("estimates with analog basis", art.phase_estimates, lambda e: "analog" in e.basis and bool(e.citations))
        fr.append(1.0 if art.p80_duration_weeks >= art.total_duration_weeks else 0.0)
        fr.append(1.0 if (art.fits_deadline is not None or art.assumptions) else 0.0)
    elif name == "solution_architect":
        add("components with responsibility and trace", art.components, lambda c: len(c.responsibility) > 15 and bool(c.brd_refs or c.citations))
        add("NFRs mapped to concrete mechanisms", art.nfr_mapping, lambda m: len(m.mechanism) > 30)
        fr.append(1.0 if len(art.pattern.alternatives_considered) >= 1 else 0.0)
        fr.append(1.0 if art.data_flows else 0.0)
    elif name == "poc_planner":
        add("measurable success criteria", art.success_criteria, lambda s: s.measurable and bool(re.search(r"\d", s.target)))
        fr.append(1.0 if art.go_no_go else 0.0)
        fr.append(1.0 if art.modular_boundaries else 0.0)
    elif name == "tech_stack_recommender":
        add("options with explicit trade-offs", art.options, lambda o: len(o.pros) >= 1 and len(o.cons) >= 1)
        add("options grounded in decision log/standards", art.options, lambda o: bool(o.citations))
        fr.append(1.0 if art.rationale and art.weights else 0.0)
    v = sum(fr) / len(fr) if fr else 0.0
    score = round(1 + 4 * v, 2)
    if name == "poc_planner" and any(not s.measurable for s in art.success_criteria):
        score = min(score, 3.5)  # hard gate: a PoC with any unmeasurable success criterion is not actionable
        why.append("hard gate: unmeasurable PoC success criteria")
    return score, why


class Critic(BaseAgent):
    name = "critic"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._n = 0

    def _issue(self, code, dim, sev, agent, items, msg, fix) -> CriticIssue:
        self._n += 1
        return CriticIssue(id=f"I{self._n:03d}", code=code, dimension=dim, severity=sev, target_agent=agent,
                           target_items=items, message=msg, suggested_fix=fix)

    # ------------------------------------------------------------------ cross-agent consistency
    def cross_checks(self) -> tuple[dict[str, bool], list[CriticIssue]]:
        a = self.ctx.artifacts
        plan, sch, arch, poc, stk = (a.get(k) for k in ARTIFACTS)
        b = self.brd
        checks, issues = {}, []

        ok = [e.phase_id for e in sch.phase_estimates] == [p.id for p in plan.phases]
        checks["schedule_phases_match_plan"] = ok
        if not ok:
            issues.append(self._issue("phase_mismatch", "consistency", "high", "schedule_estimator", [],
                                      "Schedule phases do not match the plan's phases.", "Re-estimate every plan phase in order."))
        ok = sch.headcount == plan.headcount
        checks["headcount_matches_plan"] = ok
        if not ok:
            issues.append(self._issue("headcount_mismatch", "consistency", "high", "schedule_estimator", [],
                                      f"Schedule assumes {sch.headcount} engineers but the plan staffs {plan.headcount}.",
                                      "Re-estimate with the plan's team composition."))
        ok = sch.complexity_basis >= arch.complexity_score
        checks["schedule_matches_architecture_complexity"] = ok
        if not ok:
            issues.append(self._issue("complexity_mismatch", "consistency", "high", "schedule_estimator", [],
                                      f"Schedule was estimated at complexity {sch.complexity_basis} but the architecture "
                                      f"({arch.pattern.name}, {len(arch.components)} components) is complexity {arch.complexity_score}.",
                                      f"Re-select analog projects at complexity {arch.complexity_score} / pattern "
                                      f"'{arch.pattern.pattern_id}' and re-estimate."))
        # effort sanity: effort per requirement must not be far below comparable past projects
        same = [x for x in sch.analogs if x.complexity >= arch.complexity_score - 1 and x.req_count]
        n_scope = sum(1 for r in b.requirements if r.category in ("functional", "non_functional", "integration"))
        if same and n_scope:
            floor = 0.6 * min(x.actual_weeks * x.team_size / x.req_count for x in same)
            ok = sch.total_effort_person_weeks / n_scope >= floor
        else:
            ok = True
        checks["schedule_not_below_analogs"] = ok
        if not ok:
            issues.append(self._issue("duration_below_analogs", "consistency", "medium", "schedule_estimator", [],
                                      f"Effort per requirement is below 60% of the most efficient comparable past project ({floor:.1f} person-weeks).", "Re-select analogs and re-estimate effort per requirement."))
        from .plan_generator import template_for
        want = template_for(arch.complexity_score)
        ok = plan.template_used == want
        checks["plan_template_fits_architecture"] = ok
        if not ok:
            issues.append(self._issue("template_mismatch", "consistency", "high", "plan_generator", [],
                                      f"Plan uses template {plan.template_used} but the architecture is complexity "
                                      f"{arch.complexity_score} ({arch.pattern.name}), which calls for template {want}.",
                                      f"Re-plan with template {want} (e.g. add an explicit PoC / performance phase for platform work)."))
        cids = {c.id for c in arch.components}
        missing = [c for c in poc.in_scope_component_ids if c not in cids]
        checks["poc_components_exist_in_architecture"] = not missing
        if missing:
            issues.append(self._issue("poc_unknown_components", "consistency", "high", "poc_planner", missing,
                                      f"PoC scopes components {missing} that are not in the architecture.",
                                      "Scope the PoC to existing architecture components."))
        ok = poc.duration_weeks <= 0.25 * sch.total_duration_weeks + 0.5
        checks["poc_fits_schedule"] = ok
        if not ok:
            issues.append(self._issue("poc_too_long", "consistency", "medium", "poc_planner", [],
                                      f"PoC ({poc.duration_weeks} wks) exceeds 25% of the schedule ({sch.total_duration_weeks} wks).",
                                      "Shrink PoC scope to the single riskiest path."))
        rec = next(o for o in stk.options if o.id == stk.recommended_option_id)
        need = {c.category for c in arch.components} & {"messaging", "stream-processing", "search", "cache", "storage"}
        gap = sorted(need - set(rec.components))
        checks["stack_covers_architecture"] = not gap
        if gap:
            issues.append(self._issue("missing_category", "consistency", "high", "tech_stack_recommender", gap,
                                      f"Recommended stack has no technology for architecture categories {gap}.",
                                      "Add a technology for every architecture component category."))
        tight = (sch.fits_deadline is False) or (b.constraints.deadline_weeks and sch.p80_duration_weeks > b.constraints.deadline_weeks)
        ok = not (rec.team_familiarity <= 2 and tight)
        checks["stack_familiarity_fits_timeline"] = ok
        if not ok:
            issues.append(self._issue("familiarity_risk", "consistency", "high", "tech_stack_recommender", [rec.id],
                                      f"Recommended {rec.name} has low team familiarity ({rec.team_familiarity}/5) on a tight timeline.",
                                      "Re-weight towards team familiarity or justify with training/expert support in the plan."))
        on_prem = (b.constraints.deployment or "").startswith(("on-prem", "conflict"))
        ok = not (on_prem and "Lambda" in rec.components.get("runtime", ""))
        checks["stack_respects_deployment"] = ok
        if not ok:
            issues.append(self._issue("deployment_conflict", "consistency", "high", "tech_stack_recommender", [rec.id],
                                      "Serverless recommended although on-prem deployment is required/unresolved.",
                                      "Recommend a cloud-portable option."))
        return checks, issues

    # ------------------------------------------------------------------ per-artifact rubric
    def review(self, revision_round: int) -> CriticReport:
        b = self.brd
        oos = out_of_scope_terms(b)
        with self.ctx.logger.agent_span("critic", "review", {"round": revision_round,
                                                             "artifacts": {k: self.ctx.artifacts[k].model_dump_json() for k in ARTIFACTS}},
                                        revision_round) as span:
            checks, cross = self.cross_checks()
            issues = list(cross)
            scores = []
            for name in ARTIFACTS:
                art = self.ctx.artifacts[name]
                claims = iter_claims(name, art)
                retrieved = self.ctx.retriever.retrieved(name)
                findings = check_grounding(name, art, b, retrieved, oos, self.ctx.quarantined_terms, self.ctx.retriever)
                for fnd in findings:
                    span["guardrail_triggers"].append(f"{name}:{fnd['type']}:{fnd['item']}")
                    self.ctx.logger.log("guardrail", stage="critic", agent=name, **fnd)
                bad_items = {f["item"] for f in findings if f["type"] in ("fabricated_citation", "unknown_brd_ref", "weak_support")}
                cited = [c for c in claims if c[3] and c[0] not in bad_items]
                g_ratio = len(cited) / len(claims) if claims else 0.0
                uncited = [c[0] for c in claims if not c[3]]
                routed = set(self.ctx.routing.routes.get(name, []))
                covered = {r for c in claims for r in c[2]}
                if name == "plan_generator":
                    covered |= {r for t in art.team for r in t.brd_refs}
                if name == "poc_planner":
                    covered |= {r for s in art.success_criteria for r in s.brd_refs}
                cov = len(routed & covered) / len(routed) if routed else 1.0
                uncovered = sorted(routed - covered)
                contra = [i for i in cross if i.target_agent == name]
                scope = [f for f in findings if f["type"] == "scope_creep"]
                act, why = actionability(name, art)
                if not self.ctx.llm.offline:  # LLM judge refines actionability when available
                    j = self.ctx.llm.judge(CRITIC_JUDGE, f"ARTIFACT ({name}):\n{art.model_dump_json()[:12000]}", span)
                    if j and isinstance(j.get("score"), (int, float)):
                        act = round((act + float(j["score"])) / 2, 2)
                        why += [str(x) for x in j.get("reasons", [])][:3]
                s = {"groundedness": score_ratio(g_ratio), "completeness": score_cov(cov),
                     "consistency": score_contra(len(contra) + len(scope)), "actionability": act}
                below = [d for d, ok in [("groundedness", g_ratio >= GROUNDEDNESS_MIN), ("completeness", cov >= COMPLETENESS_MIN),
                                         ("consistency", len(contra) + len(scope) <= CONSISTENCY_MAX),
                                         ("actionability", act >= ACTIONABILITY_MIN)] if not ok]
                overall = round(sum(s.values()) / 4, 2)
                scores.append(ArtifactScore(artifact=name, groundedness_ratio=round(g_ratio, 3), coverage_ratio=round(cov, 3),
                                            contradictions=len(contra) + len(scope), actionability=act, scores=s,
                                            overall=overall, below_threshold=below, badge=badge_for(below, overall)))
                # ---- specific feedback
                if g_ratio < GROUNDEDNESS_MIN and uncited:
                    issues.append(self._issue("uncited_claims", "groundedness", "medium", name, uncited,
                                              f"{len(uncited)}/{len(claims)} claims have no citation ({g_ratio:.0%} cited, need >= 75%).",
                                              "Run a targeted retrieval for each listed item and cite the supporting chunk, or "
                                              "mark it as an assumption."))
                if bad_items:
                    issues.append(self._issue("invalid_grounding", "groundedness", "high", name, sorted(bad_items),
                                              "Citations reference chunks not retrieved by this agent, unknown BRD ids, or weakly related text.",
                                              "Cite only retrieved chunk_ids and existing requirement ids."))
                if uncovered:
                    issues.append(self._issue("uncovered_requirements", "completeness", "high", name, uncovered,
                                              f"Routed requirements not addressed: {', '.join(uncovered)}.",
                                              "Map each listed requirement to a concrete item (phase deliverable / component / criterion)."))
                if scope:
                    issues.append(self._issue("scope_creep", "consistency", "high", name, sorted({f['item'] for f in scope}),
                                              "Items introduce scope not present in the BRD (or match out-of-scope/injected terms).",
                                              "Remove the items or tie them to a BRD requirement."))
                if act < ACTIONABILITY_MIN:
                    items = []
                    if name == "poc_planner":
                        items = [c.id for c in art.success_criteria if not c.measurable]
                        code = "unmeasurable_criteria"
                    else:
                        code = "low_actionability"
                    issues.append(self._issue(code, "actionability", "medium", name, items,
                                              f"Actionability {act}/5 (< 4). Gaps: {'; '.join(why) or 'n/a'}.",
                                              "Make every listed item measurable (metric, numeric target, method) using org "
                                              "default SLOs where the BRD is vague, and record the assumption."))
            overall = round(sum(x.overall for x in scores) / len(scores), 2)
            all_below = [d for x in scores for d in x.below_threshold]
            n_red = sum(x.badge == "RED" for x in scores)
            n_amber = sum(x.badge == "AMBER" for x in scores)
            overall_badge = "RED" if (n_red or overall < 3.0) else ("AMBER" if (n_amber or overall < 4.0) else "GREEN")
            to_revise = sorted({i.target_agent for i in issues})
            if not to_revise:
                decision = "pass"
            elif revision_round >= MAX_REVISIONS:
                decision = "escalate"
            else:
                decision = "revise"
            report = CriticReport(revision_round=revision_round, artifact_scores=scores, issues=issues,
                                  cross_agent_checks=checks, decision=decision, agents_to_revise=to_revise,
                                  overall_badge=overall_badge, overall_score=overall)
            span["output_obj"] = report.model_dump()
            span["critic_scores"] = {x.artifact: {"overall": x.overall, "badge": x.badge, **x.scores} for x in scores}
            span["output_summary"] = {"decision": decision, "issues": len(issues), "overall": overall, "badge": overall_badge}
        return report
