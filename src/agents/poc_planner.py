"""Agent 5 — PoC Planner (Design group).

Scopes a proof of concept around the riskiest architecture components
(external integrations, NFR-critical paths, ambiguous core capabilities) with
measurable success criteria.
"""
from __future__ import annotations

import re

from ..contracts import PoCPlan, SuccessCriterion
from .base import BaseAgent, FixContext, short

NUM = re.compile(r"(?:under|below|less than|at least|within|<|>|≥|≤)?\s*p?\d[\d,.]*\s*(?:ms|milliseconds|seconds?|%|"
                 r"events per second|concurrent \w+|MB|x|years?|minutes?|days?|hours?)?(?:\s+at\s+p\d+)?", re.I)

# Conservative quantification of vague requirements (org default SLOs / measurable proxies).
QUANTIFY = {
    "performance": ("p95 latency", "< 300 ms at expected peak load", "load test with k6 in a production-like environment"),
    "availability": ("monthly availability", ">= 99.9% (99.5% for internal tools)", "synthetic probes over a 7-day soak test"),
    "usability": ("primary-flow task success", ">= 90% task completion and median time-on-task <= 3 min with 5 target users",
                  "moderated usability test with the product owner"),
    "search": ("search relevance and latency", "precision@5 >= 0.8 on 50 labelled queries; p95 < 300 ms",
               "offline relevance evaluation set built with support leads"),
    "general": ("acceptance pass rate", ">= 95% of agreed acceptance tests pass", "automated acceptance tests in stage"),
}


def numeric_target(text: str) -> str:
    parts = [m.group(0).strip() for m in NUM.finditer(text) if re.search(r"\d", m.group(0))]
    return "; ".join(dict.fromkeys(parts))


class PoCPlanner(BaseAgent):
    name = "poc_planner"
    output_model = PoCPlan

    def upstream(self):
        return {"architecture": self.ctx.artifacts["solution_architect"], "schedule": self.ctx.artifacts["schedule_estimator"],
                "plan": self.ctx.artifacts["plan_generator"]}

    def retrieve(self, span, fix):
        arch = self.ctx.artifacts["solution_architect"]
        risky = " ".join(c.name for c in arch.components if c.category in ("integration", "messaging", "stream-processing", "search"))
        hits = self.search(f"proof of concept riskiest path de-risk {risky} lessons PoC success criteria", span)
        hits += self.search("default service level objectives latency availability", span, source_types=["standards"], top_k=2)
        if fix:
            hits += self.search("quantify vague requirement measurable target default SLO usability relevance", span, top_k=3)
        return list({h.chunk_id: h for h in hits}.values())

    def heuristic(self, hits, upstream, fix: FixContext, span):
        b = self.brd
        arch, sched, plan = upstream["architecture"], upstream["schedule"], upstream["plan"]
        routed = [b.req(r) for r in self.routed() if b.req(r)]
        quantify = "unmeasurable_criteria" in fix.codes()
        targets = set(fix.items("unmeasurable_criteria"))

        # components in scope: adapters for routed integrations + NFR-critical components (max 4)
        comp_for = {}
        for c in arch.components:
            for r in c.brd_refs:
                comp_for.setdefault(r, []).append(c)
        for m in arch.nfr_mapping:
            for cid in m.component_ids:
                comp_for.setdefault(m.nfr_id, []).append(next(c for c in arch.components if c.id == cid))
        ranked = []
        for r in routed:
            for c in comp_for.get(r.id, []):
                weight = {"integration": 3, "messaging": 3, "stream-processing": 3, "search": 2, "cache": 1}.get(c.category, 0)
                ranked.append((weight, c))
        ranked.sort(key=lambda x: -x[0])
        in_scope = []
        for w, c in ranked:
            if c.id not in in_scope and w > 0:
                in_scope.append(c.id)
            if len(in_scope) == 4:
                break
        if not in_scope:
            in_scope = [arch.components[0].id]
        names = [c.name for c in arch.components if c.id in in_scope]

        criteria, assumptions = [], []
        for r in routed:
            sid = f"SC-{r.id}"
            if r.category == "integration":
                sys_name = short(re.split(r"[(.]", r.text)[0], 40)
                text = (f"End-to-end round trip with {sys_name} sandbox", ">= 95% of 50 contract-test cases pass; p95 < 1 s",
                        "contract tests against the sandbox in CI")
                meas = True
            else:
                tgt = numeric_target(r.text)
                low = r.text.lower()
                key = ("search" if ("search" in low or "relevant" in low) else
                       r.subcategory if r.subcategory in QUANTIFY else "general")
                if tgt and not r.ambiguous_terms:
                    text = (short(r.text, 70), tgt, QUANTIFY.get(key, QUANTIFY["general"])[2])
                    meas = True
                elif quantify and (sid in targets or not targets):
                    metric, target, how = QUANTIFY.get(key, QUANTIFY["general"])
                    text = (metric, target, how)
                    meas = True
                    assumptions.append(f"{r.id} quantified conservatively as '{target}' (org default/proxy); confirm with product owner.")
                else:  # first pass carries the BRD wording through unchanged
                    text = (short(r.text, 70), "as stated in BRD", "to be agreed")
                    meas = False
            full = f"{text[0]} {text[1]} measured by {text[2]}"
            criteria.append(SuccessCriterion(id=sid, metric=text[0], target=text[1], measurement=text[2], measurable=meas,
                                             brd_refs=[r.id], citations=self.cite(full, hits),
                                             assumption=(f"quantified from vague BRD wording" if meas and r.ambiguous_terms else None)))
        for iid in fix.items("uncited_claims"):
            for s in criteria:
                if s.id == iid and not s.citations:
                    s.citations = self.targeted_cite(f"{s.metric} {s.target} {s.measurement}", span)

        poc_phase = next((p for p in plan.phases if "poc" in p.name.lower()), None)
        if poc_phase:
            dur = next(e.duration_weeks for e in sched.phase_estimates if e.phase_id == poc_phase.id)
        else:
            dur = 2.0 if arch.complexity_score <= 3 else 3.0
        dur = min(dur, max(1.0, round(0.25 * sched.total_duration_weeks * 2) / 2), 8.0)
        return PoCPlan(
            objective=f"De-risk {', '.join(names)} before Core Build by proving the riskiest requirements against measurable targets.",
            hypotheses=[f"{c.name} can meet its success criteria without changing the {arch.pattern.name} design"
                        for c in arch.components if c.id in in_scope],
            in_scope_component_ids=in_scope,
            out_of_scope=["production UI polish", "full data migration", "non-critical integrations"] + b.out_of_scope,
            success_criteria=criteria, duration_weeks=dur,
            modular_boundaries=[f"PoC code for {n} sits behind the production interface so it can be hardened, not rewritten"
                                for n in names] + ["Throwaway test harness and synthetic data kept outside the main repo"],
            go_no_go="Go to Core Build if every measurable Must criterion is met; otherwise the Solution Architect revisits "
                     "the pattern/stack and the EM re-baselines the schedule.",
            citations=[h.chunk_id for h in hits if "poc" in h.text.lower()][:2],
            assumptions=assumptions,
            flags=[f for f in b.flags if f.kind == "ambiguity" and set(f.brd_refs) & set(self.routed())])

    def summarize(self, out):
        return {"components": out.in_scope_component_ids, "criteria": len(out.success_criteria),
                "measurable": sum(s.measurable for s in out.success_criteria), "weeks": out.duration_weeks}
