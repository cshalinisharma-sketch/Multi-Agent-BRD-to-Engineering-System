"""Agent 3 — Schedule Estimator (Planning group).

Analog-based estimation: effort per requirement from the most similar past
projects (retrieved from the project-timeline table), scaled to the BRD scope,
spread over the plan's phases by their effort shares. p80 uses the analogs'
historical variance. When the Critic reports a complexity mismatch with the
architecture, the estimator re-selects analogs at the architecture's complexity.
"""
from __future__ import annotations

import statistics

from ..contracts import Analog, Flag, PhaseEstimate, Schedule
from .base import BaseAgent, FixContext

PHASE_ROLES = {
    "discovery": ["Tech Lead", "Product Manager"],
    "poc": ["Tech Lead", "Backend Engineer", "Data / Streaming Engineer"],
    "foundation": ["DevOps / SRE Engineer", "Tech Lead", "Backend Engineer"],
    "build": ["Backend Engineer", "Frontend Engineer", "QA / Test Automation Engineer"],
    "hardening": ["QA / Test Automation Engineer", "Backend Engineer", "DevOps / SRE Engineer"],
    "launch": ["DevOps / SRE Engineer", "Tech Lead"],
}


def half(x: float) -> float:
    return max(0.5, round(x * 2) / 2)


class ScheduleEstimator(BaseAgent):
    name = "schedule_estimator"
    output_model = Schedule

    def upstream(self):
        up = {"plan": self.ctx.artifacts["plan_generator"]}
        if "solution_architect" in self.ctx.artifacts:
            up["architecture"] = self.ctx.artifacts["solution_architect"]
        return up

    def basis_complexity(self, fix: FixContext) -> tuple[int, str | None]:
        c = self.ctx.routing.complexity_estimate
        arch = self.ctx.artifacts.get("solution_architect")
        if arch is not None and ("complexity_mismatch" in fix.codes() or "duration_below_analogs" in fix.codes()):
            return max(c, arch.complexity_score), arch.pattern.pattern_id
        return c, None

    def retrieve(self, span, fix):
        b = self.brd
        c, pattern = self.basis_complexity(fix)
        n = len([r for r in b.requirements if r.category != "constraint"])
        q = f"past project domain {b.domain} complexity {c} {pattern or ''} {n} requirements team of {b.constraints.team_size or ''}"
        where = {"complexity": {"$in": [x for x in (c - 1, c, c + 1) if 1 <= x <= 5]}}
        hits = self.search(q, span, top_k=6, source_types=["project_timeline"], where=where)
        if pattern:
            hits += self.search(f"{pattern} project actual weeks variance", span, top_k=3,
                                source_types=["project_timeline"], where={"pattern": pattern})
        return list({h.chunk_id: h for h in hits}.values())

    def heuristic(self, hits, upstream, fix: FixContext, span):
        from .plan_generator import phase_role
        b = self.brd
        plan = upstream["plan"]
        c, pattern = self.basis_complexity(fix)
        analog_hits = [h for h in hits if h.metadata.get("source_type") == "project_timeline"]
        if pattern:  # prefer same-pattern analogs when re-estimating against the architecture
            same = [h for h in analog_hits if h.metadata.get("pattern") == pattern]
            analog_hits = same + [h for h in analog_hits if h not in same][: max(0, 3 - len(same))]
        def relevance(h):
            m = h.metadata
            return (h.score + 0.3 * (m["domain"] == b.domain) + 0.3 * (m["complexity"] == c)
                    - 0.35 * abs(m["complexity"] - c) + 0.4 * (pattern is not None and m["pattern"] == pattern))
        analog_hits = sorted(analog_hits, key=relevance, reverse=True)[:3]
        span.setdefault("decisions", []).append({"decision": "analogs", "chosen": [h.metadata["doc_id"] for h in analog_hits],
                                                 "complexity_basis": c, "pattern": pattern})
        assumptions, flags = [], []
        if not analog_hits:
            assumptions.append("No analog projects retrieved; using org default 9 person-weeks per requirement (low confidence).")
            epr, var = 9.0, 25.0
        else:
            eprs = [h.metadata["actual_weeks"] * h.metadata["team_size"] / h.metadata["req_count"] for h in analog_hits]
            epr = statistics.median(eprs)
            var = statistics.median([h.metadata["variance_pct"] for h in analog_hits])
        weight = {"must": 1.0, "should": 1.0, "could": 0.5}
        scope = [r for r in b.requirements if r.category in ("functional", "non_functional", "integration")]
        n_scope = sum(weight[r.priority] for r in scope)
        n_must = sum(1 for r in scope if r.priority == "must")
        headcount = plan.headcount
        total_effort = epr * n_scope
        duration = total_effort / headcount

        con_refs = self.routed()
        timeline_refs = [r for r in con_refs if (rq := b.req(r)) and rq.subcategory == "timeline"]
        analog_ids = [h.chunk_id for h in analog_hits]
        estimates, t = [], 0.0
        for p in plan.phases:
            d = half(duration * p.effort_share_pct / 100)
            role = phase_role(p.name)
            team_roles = {tr.role for tr in plan.team}
            roles = [r for r in PHASE_ROLES.get(role, ["Backend Engineer"]) if r in team_roles or r == "Product Manager"]
            estimates.append(PhaseEstimate(
                phase_id=p.id, effort_person_weeks=round(total_effort * p.effort_share_pct / 100, 1),
                duration_weeks=d, start_week=t, end_week=t + d, roles=roles or ["Backend Engineer"],
                basis=(f"{p.effort_share_pct:g}% of {total_effort:.0f} person-weeks; {epr:.1f} person-weeks per requirement "
                       f"(median of analog projects {', '.join(h.metadata['doc_id'] for h in analog_hits) or 'n/a'}, "
                       f"complexity basis {c}) with {headcount} engineers"),
                brd_refs=[r for r in con_refs if r not in timeline_refs],
                citations=analog_ids[:2]))
            t += d
        estimates[-1].brd_refs = con_refs
        total = estimates[-1].end_week
        p80 = half(total * (1 + var / 100))
        deadline = b.constraints.deadline_weeks
        fits = None if deadline is None else total <= deadline
        must_only = half(epr * n_must / headcount)
        if deadline is None:
            assumptions.append(f"BRD has no deadline; p50 {total:g} weeks and p80 {p80:g} weeks proposed for EM approval.")
        elif not fits:
            flags.append(Flag(id="SCH-1", kind="feasibility", severity="high", brd_refs=timeline_refs,
                              message=(f"p50 estimate {total:g} weeks exceeds the BRD deadline of {deadline:g} weeks "
                                       f"(p80 {p80:g}). A Must-only first release is estimated at {must_only:g} weeks."),
                              resolution="Escalated to EM: choose between extending the date, adding capacity, or a "
                                         "Must-only first release; schedule keeps the conservative (longer) estimate."))
        elif p80 > deadline:
            assumptions.append(f"p50 {total:g} weeks fits the {deadline:g}-week deadline but p80 ({p80:g}) does not; "
                               f"buffer is thin.")
        assumptions.append(f"Phases are sequential; parallelising Foundation with late Discovery can save ~1-2 weeks.")
        analogs = [Analog(project_id=h.metadata["doc_id"], chunk_id=h.chunk_id, complexity=h.metadata["complexity"],
                          actual_weeks=h.metadata["actual_weeks"], team_size=h.metadata["team_size"],
                          variance_pct=h.metadata["variance_pct"], req_count=h.metadata["req_count"]) for h in analog_hits]
        return Schedule(phase_estimates=estimates, total_duration_weeks=total, p80_duration_weeks=p80,
                        total_effort_person_weeks=round(total_effort, 1), headcount=headcount, complexity_basis=c,
                        analogs=analogs, deadline_weeks=deadline, fits_deadline=fits, assumptions=assumptions, flags=flags)

    def summarize(self, out):
        return {"p50_weeks": out.total_duration_weeks, "p80_weeks": out.p80_duration_weeks,
                "complexity_basis": out.complexity_basis, "fits_deadline": out.fits_deadline,
                "analogs": [a.project_id for a in out.analogs]}
