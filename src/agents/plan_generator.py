"""Agent 2 — Engineering Plan Generator (Planning group).

Produces phases, milestones, risks and team composition, adapted from the most
relevant org plan template, and runs a Reflection self-review before handing off.
"""
from __future__ import annotations

import re
import statistics

from ..contracts import EngineeringPlan, Flag, Milestone, Phase, Reflection, Risk, TeamRole
from ..rag.store import Hit
from .base import BaseAgent, FixContext, short

UI_WORDS = ("portal", "console", "dashboard", "view", "web", "sign in", "search box", "see ", "website", "screen")


def phase_role(name: str) -> str:
    n = name.lower()
    for key, role in [("poc", "poc"), ("discovery", "discovery"), ("shape", "discovery"), ("foundation", "foundation"),
                      ("platform", "foundation"), ("core build", "build"), ("build mvp", "build"),
                      ("integration", "hardening"), ("performance", "hardening"), ("launch", "launch"),
                      ("rollout", "launch"), ("pilot", "launch")]:
        if key in n:
            return role
    return "build"


def template_for(complexity: int) -> str:
    return "T3" if complexity <= 2 else ("T1" if complexity <= 4 else "T2")


def parse_template(hits: list[Hit], doc_id: str) -> dict:
    chunks = sorted([h for h in hits if h.metadata.get("doc_id") == doc_id],
                    key=lambda h: int(h.chunk_id.rsplit("#", 1)[1]))
    phases, milestones, risks = [], [], []
    for h in chunks:
        m = re.search(r"Phase (\d+): ([^(\n]+)\((\d+)% of effort\)", h.text)
        if m:
            deliv = re.search(r"Deliverables:\s*(.+)", h.text)
            exitc = re.search(r"Exit criteria:\s*(.+)", h.text)
            phases.append({"n": int(m.group(1)), "name": m.group(2).strip(), "pct": float(m.group(3)),
                           "deliverables": [d.strip(" .") for d in deliv.group(1).split(",")] if deliv else [],
                           "exit": [e.strip(" .") for e in exitc.group(1).split(";")] if exitc else [],
                           "chunk": h.chunk_id})
        for mm in re.finditer(r"^- (M\d+) ([^\n(]+)", h.text, re.M):
            milestones.append({"id": mm.group(1), "name": mm.group(2).strip(), "chunk": h.chunk_id})
        for rr in re.finditer(r"^- RISK: (.+?) \| Mitigation: (.+?) \| Owner: (.+)$", h.text, re.M):
            risks.append({"desc": rr.group(1).strip(), "mit": rr.group(2).strip(), "owner": rr.group(3).strip(),
                          "chunk": h.chunk_id})
    phases.sort(key=lambda p: p["n"])
    return {"phases": phases, "milestones": milestones, "risks": risks}


class PlanGenerator(BaseAgent):
    name = "plan_generator"
    output_model = EngineeringPlan

    def complexity(self, fix: FixContext | None = None) -> int:
        """Routing estimate on the first pass; the architecture's complexity once the Critic reports
        that the chosen template does not fit the designed system."""
        arch = self.ctx.artifacts.get("solution_architect")
        if fix and "template_mismatch" in fix.codes() and arch is not None:
            return arch.complexity_score
        return self.ctx.routing.complexity_estimate

    def retrieve(self, span, fix):
        b = self.brd
        c = self.complexity(fix)
        tid = template_for(c)
        span.setdefault("decisions", []).append({"decision": "template", "value": tid,
                                                 "reason": f"complexity estimate {c}"})
        hits = self.search(f"{b.title} delivery plan template complexity {c} phases milestones", span,
                           source_types=["plan_template"])
        # tool: load the full chosen template (all phases, milestones, risk catalogue)
        hits += self.search("phases deliverables exit criteria milestones risk catalogue", span,
                            top_k=20, where={"doc_id": tid})
        integ = " ".join(r.text for r in b.requirements if r.category == "integration")
        hits += self.search(f"lessons learned delivery retrospective {b.domain} {integ}", span,
                            source_types=["past_brd", "project_timeline"])
        uniq = {h.chunk_id: h for h in hits}
        return list(uniq.values())

    # ------------------------------------------------------------------ heuristic generator
    def heuristic(self, hits, upstream, fix: FixContext, span):
        b = self.brd
        c = self.complexity(fix)
        tid = template_for(c)
        tpl = parse_template(hits, tid)
        routed = set(self.routed())
        reqs = [r for r in b.requirements if r.id in routed]
        roles = {p["name"]: phase_role(p["name"]) for p in tpl["phases"]}
        role_to_phase = {}
        for p in tpl["phases"]:
            role_to_phase.setdefault(roles[p["name"]], p["name"])

        def target_role(r) -> str | None:
            if r.category == "integration":
                return "poc" if "poc" in role_to_phase else ("hardening" if "hardening" in role_to_phase else "build")
            if r.category == "non_functional":
                if r.subcategory in ("security", "compliance", "deployment"):
                    return "foundation" if "foundation" in role_to_phase else "discovery"
                return "hardening" if "hardening" in role_to_phase else "build"
            if r.category == "constraint":
                if r.subcategory == "timeline":
                    return "launch"
                if re.search(r"team|engineer", r.text, re.I):
                    return None  # covered by team composition
                return "foundation" if "foundation" in role_to_phase else "discovery"
            if r.subcategory == "general":
                return None  # no confident keyword match -> left for reflection/critic
            return "build"

        mapping: dict[str, list] = {p["name"]: [] for p in tpl["phases"]}
        unmapped = []
        # requirements caught in an out-of-scope contradiction are deferred to an EM decision, not built
        deferred = {r: f.id for f in b.flags if f.kind == "contradiction" and "out of scope" in f.message for r in f.brd_refs}
        extra = set(fix.items("uncovered_requirements"))
        for r in reqs:
            if r.id in deferred:
                mapping[role_to_phase.get("discovery", tpl["phases"][0]["name"])].append(r)
                continue
            role = target_role(r)
            if role is None and r.id in extra:
                role = "build" if r.category == "functional" else "launch"
            if role is None:
                if r.category != "constraint":
                    unmapped.append(r)
                continue
            mapping[role_to_phase.get(role, role_to_phase.get("build"))].append(r)

        # ---- build phases
        phases = []
        amb = [f for f in b.flags if f.kind == "ambiguity"]
        for i, p in enumerate(tpl["phases"], 1):
            mapped = mapping[p["name"]]
            deliverables = list(p["deliverables"])
            exit_c = list(p["exit"])
            role = roles[p["name"]]
            if role == "discovery" and amb:
                deliverables.append("clarified acceptance criteria for ambiguous requirements " +
                                    ", ".join(r for f in amb for r in f.brd_refs))
            if role == "discovery":
                for rid, fid in deferred.items():
                    deliverables.append(f"{rid} deferred pending EM decision on {fid} (conflicts with the out-of-scope list)")
            for r in mapped:
                if r.category == "constraint" and r.subcategory == "timeline":
                    continue
                if r.id in deferred:
                    continue
                label = "constraint" if r.category == "constraint" else r.priority
                deliverables.append(f"{r.id} ({label}): {short(r.text, 70)}")
            if role == "build" and mapped:
                exit_c.append("acceptance tests pass for " + ", ".join(r.id for r in mapped if r.priority == "must"))
            objective = f"{p['name']} for {b.title}" + (f", delivering {len(mapped)} mapped requirements" if mapped else "")
            phases.append(Phase(id=f"PH{i}", name=p["name"], objective=objective, effort_share_pct=p["pct"],
                                deliverables=deliverables, exit_criteria=exit_c or ["phase review sign-off by EM"],
                                brd_refs=[r.id for r in mapped], citations=[p["chunk"]]))

        # ---- milestones (template milestones mapped to phases in order)
        milestones = []
        timeline_refs = [r.id for r in b.requirements if r.category == "constraint" and r.subcategory == "timeline"]
        for j, m in enumerate(tpl["milestones"]):
            ph = phases[min(j, len(phases) - 1)]
            last = j == len(tpl["milestones"]) - 1
            milestones.append(Milestone(id=m["id"], name=m["name"], phase_id=ph.id,
                                        acceptance=ph.exit_criteria[0],
                                        brd_refs=(timeline_refs if last else ph.brd_refs[:4]),
                                        citations=[m["chunk"]],
                                        assumption=None if (not last or b.constraints.deadline_weeks) else
                                        "No go-live date in BRD; milestone date set by Schedule Estimator p80."))

        # ---- risks
        bulk = " ".join(r.text for r in b.requirements)
        risks: list[Risk] = []
        if tpl["risks"]:
            sims = self.ctx.retriever.text_sim([r["desc"] + " " + r["mit"] for r in tpl["risks"]], bulk)
            ranked = sorted(zip(sims, tpl["risks"]), key=lambda x: -x[0])
            for s, r in ranked[:3]:
                risks.append(Risk(id=f"R{len(risks) + 1}", description=r["desc"], likelihood="medium",
                                  impact="high" if "performance" in r["desc"].lower() or "nfr" in r["desc"].lower() else "medium",
                                  mitigation=r["mit"], owner_role=r["owner"], citations=[r["chunk"]]))
        for r in b.requirements:
            if r.category == "integration":
                text = f"{r.id} {short(r.text, 60)}: sandbox access, certification or contract changes delay delivery"
                risks.append(Risk(id=f"R{len(risks) + 1}", description=text, likelihood="medium", impact="high",
                                  mitigation="Request sandbox/credentials in discovery week 1, build contract-test stubs, "
                                             "isolate behind an adapter (anti-corruption layer), make it a PoC slice",
                                  owner_role="Tech Lead", brd_refs=[r.id], citations=self.cite(text, hits)))
        for f in b.flags:
            if f.kind in ("contradiction", "feasibility"):
                risks.append(Risk(id=f"R{len(risks) + 1}", description=f"Unresolved BRD issue {f.id}: {short(f.message, 110)}",
                                  likelihood="high", impact="high", mitigation=f.resolution or "EM decision required",
                                  owner_role="Engineering Manager", brd_refs=f.brd_refs))
            elif f.kind == "ambiguity":
                risks.append(Risk(id=f"R{len(risks) + 1}", description=f"Ambiguous requirement {', '.join(f.brd_refs)} causes rework",
                                  likelihood="medium", impact="medium",
                                  mitigation="Acceptance criteria agreed with product owner before build; conservative interpretation recorded",
                                  owner_role="Product Manager", brd_refs=f.brd_refs,
                                  citations=[h.chunk_id for h in hits if "ambiguity" in h.text.lower()][:1]))

        # ---- team
        timeline_hits = [h for h in hits if h.metadata.get("source_type") == "project_timeline"]
        n = b.constraints.team_size
        assumptions = []
        team_cites = []
        if not n:
            near = [h for h in timeline_hits if abs(h.metadata["complexity"] - c) <= 1] or timeline_hits
            n = int(statistics.median([h.metadata["team_size"] for h in near])) if near else 5
            team_cites = [h.chunk_id for h in near[:2]]
            assumptions.append(f"BRD gives no team size; assumed {n} engineers from analog projects.")
        team_refs = [r.id for r in b.requirements if r.category == "constraint" and r.subcategory == "resourcing"
                     and re.search(r"team|engineer", r.text, re.I)]
        has_ui = any(any(w in r.text.lower() for w in UI_WORDS) for r in b.requirements if r.category == "functional")
        roles_l = [("Tech Lead", 1, "owns architecture decisions and integration design")]
        rem = n - 1
        if has_ui and rem > 1:
            fe = max(1, round(0.25 * (n - 2)))
            roles_l.append(("Frontend Engineer", fe, "builds the user-facing UI requirements"))
            rem -= fe
        if n >= 4 and rem > 1:
            roles_l.append(("QA / Test Automation Engineer", 1, "contract, end-to-end and performance test automation"))
            rem -= 1
        if (n >= 7 or c >= 4) and rem > 1:
            roles_l.append(("DevOps / SRE Engineer", 1, "CI/CD, IaC, observability and SLO alerting"))
            rem -= 1
        if c >= 5 and rem > 1:
            roles_l.append(("Data / Streaming Engineer", 1, "event pipeline, partitioning and consumer tuning"))
            rem -= 1
        roles_l.append(("Backend Engineer", max(rem, 1), "domain services and integrations"))
        team = [TeamRole(role=r, count=k, justification=j, brd_refs=team_refs,
                         citations=team_cites or self.cite(f"{r} {j}", hits, 1)) for r, k, j in roles_l]

        plan = EngineeringPlan(template_used=tid, phases=phases, milestones=milestones, risks=risks, team=team,
                               assumptions=assumptions,
                               flags=[f for f in b.flags if f.kind in ("ambiguity", "contradiction", "feasibility")])

        # ---- citations for items without any (first pass: one shot against agent-level hits)
        for coll in (plan.phases, plan.milestones, plan.risks):
            for it in coll:
                if not it.citations:
                    txt = getattr(it, "description", None) or getattr(it, "name", "")
                    it.citations = self.cite(txt, hits, 1)
        # revision: targeted retrieval for claims the Critic marked uncited
        uncited = set(fix.items("uncited_claims"))
        if uncited:
            for coll in (plan.phases, plan.milestones, plan.risks):
                for it in coll:
                    if it.id in uncited and not it.citations:
                        txt = getattr(it, "description", None) or f"{it.name} {getattr(it, 'acceptance', '')}"
                        it.citations = self.targeted_cite(txt, span)
            for t in plan.team:
                if f"ROLE-{t.role}" in uncited and not t.citations:
                    t.citations = self.targeted_cite(f"{t.role} {t.justification}", span)

        return self.reflect(plan, unmapped, role_to_phase)

    # ------------------------------------------------------------------ Reflection pattern
    def reflect(self, plan: EngineeringPlan, unmapped, role_to_phase) -> EngineeringPlan:
        checks = ["every Must requirement mapped to a phase", "every phase has exit criteria",
                  "every risk has mitigation and owner", "headcount respects BRD team constraint"]
        issues, changes = [], []
        build = next(p for p in plan.phases if p.name == role_to_phase.get("build", plan.phases[-1].name))
        for r in unmapped:
            if r.priority == "must":
                issues.append(f"Must requirement {r.id} not mapped to any phase")
                build.brd_refs.append(r.id)
                build.deliverables.append(f"{r.id} (must): {short(r.text, 70)}")
                changes.append(f"mapped {r.id} to '{build.name}'")
        for p in plan.phases:
            if not p.exit_criteria:
                issues.append(f"{p.id} has no exit criteria")
                p.exit_criteria = ["phase review sign-off by EM"]
                changes.append(f"added exit criteria to {p.id}")
        for r in plan.risks:
            if not r.mitigation or not r.owner_role:
                issues.append(f"{r.id} missing mitigation/owner")
                r.owner_role = r.owner_role or "Engineering Manager"
                changes.append(f"assigned owner to {r.id}")
        n = self.brd.constraints.team_size
        if n and plan.headcount != n:
            issues.append(f"headcount {plan.headcount} != BRD team {n}")
            be = next(t for t in plan.team if t.role == "Backend Engineer")
            be.count = max(1, be.count + n - plan.headcount)
            changes.append(f"adjusted backend count to match team of {n}")
        plan.reflection = Reflection(checks_run=checks, issues_found=issues, changes_made=changes)
        return plan

    def summarize(self, out):
        return {"phases": len(out.phases), "risks": len(out.risks), "headcount": out.headcount,
                "template": out.template_used, "reflection_fixes": len(out.reflection.changes_made) if out.reflection else 0}
