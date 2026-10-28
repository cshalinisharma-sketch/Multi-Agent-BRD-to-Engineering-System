""""Evaluation methods.

1. Rule-based      – structural/schema checks, BRD section coverage, contract rules.
2. LLM-as-Judge    – actionability, specificity, grounding quality, EM-readiness.
                     Uses the configured LLM; offline it falls back to a transparent
                     heuristic proxy (clearly labelled `judge_mode: heuristic-proxy`).
3. Execution-based – schema parse rate, end-to-end completion, tool-call success.
4. Reference-based – ROUGE-L F1 of the generated plan/architecture summary vs a golden
                     reference written for each eval BRD (implemented locally, no deps).
5. Human           – EM rating captured at the interactive HITL gate (summary.hitl.em_rating).
""""
from __future__ import annotations

import json
import re
from typing import Any

from ..contracts import AGENT_OUTPUT_MODELS
from ..guardrails import iter_claims
from ..prompts import EVAL_JUDGE

ARTS = ["plan_generator", "schedule_estimator", "solution_architect", "poc_planner", "tech_stack_recommender"]


def load_models(raw: dict[str, dict]) -> dict[str, Any]:
    return {k: AGENT_OUTPUT_MODELS[k].model_validate(v) for k, v in raw.items()}


# ------------------------------------------------------------------ 1. rule-based
def rule_checks(brd, arts: dict[str, Any], store) -> list[dict]:
    out = []

    def chk(name, ok, detail=""):
        out.append({"check": name, "pass": bool(ok), "detail": detail})

    plan, sch, arch, poc, stk = (arts[k] for k in ARTS)
    ids = lambda cat: {r.id for r in brd.requirements if r.category == cat}
    refs = lambda name: {r for c in iter_claims(name, arts[name]) for r in c[2]}
    plan_refs = refs("plan_generator") | {r for t in plan.team for r in t.brd_refs}
    arch_refs = refs("solution_architect")
    miss = ids("functional") - (plan_refs & arch_refs)
    chk("functional requirements covered by plan AND architecture", not miss, ",".join(sorted(miss)))
    miss = ids("non_functional") - {m.nfr_id for m in arch.nfr_mapping}
    chk("every NFR mapped to a mechanism", not miss, ",".join(sorted(miss)))
    miss = ids("integration") - arch_refs
    chk("every integration has a component", not miss, ",".join(sorted(miss)))
    miss = ids("constraint") - (refs("schedule_estimator") | plan_refs)
    chk("constraints addressed by plan/schedule", not miss, ",".join(sorted(miss)))
    chk("every phase has exit criteria", all(p.exit_criteria for p in plan.phases))
    chk("every risk has mitigation and owner", all(r.mitigation and r.owner_role for r in plan.risks))
    chk("plan headcount respects BRD team size", not brd.constraints.team_size or plan.headcount == brd.constraints.team_size)
    chk("schedule phases == plan phases", [e.phase_id for e in sch.phase_estimates] == [p.id for p in plan.phases])
    chk("p80 >= p50", sch.p80_duration_weeks >= sch.total_duration_weeks)
    chk("deadline feasibility stated", sch.deadline_weeks is None or sch.fits_deadline is not None)
    chk("architecture justifies pattern vs >=1 alternative", len(arch.pattern.alternatives_considered) >= 1)
    chk("architecture diagram present", arch.mermaid.startswith("flowchart"))
    chk("all PoC criteria measurable", all(s.measurable for s in poc.success_criteria),
        ",".join(s.id for s in poc.success_criteria if not s.measurable))
    chk("PoC <= 25% of schedule", poc.duration_weeks <= 0.25 * sch.total_duration_weeks + 0.5)
    chk("PoC components exist in architecture", set(poc.in_scope_component_ids) <= {c.id for c in arch.components})
    chk("2-3 stack options with pros and cons", 2 <= len(stk.options) <= 3 and all(o.pros and o.cons for o in stk.options))
    rec = next(o for o in stk.options if o.id == stk.recommended_option_id)
    need = {c.category for c in arch.components} & {"messaging", "stream-processing", "search", "cache", "storage"}
    chk("recommended stack covers architecture categories", need <= set(rec.components), ",".join(sorted(need - set(rec.components))))
    kb = {c.chunk_id for c in store.chunks}
    bad = sorted({c for n in ARTS for it in iter_claims(n, arts[n]) for c in it[3] if c not in kb})
    chk("all citations resolve to knowledge-base chunks", not bad, ",".join(bad))
    unknown = sorted({r for n in ARTS for it in iter_claims(n, arts[n]) for r in it[2] if r not in brd.req_ids})
    chk("no invented requirement ids", not unknown, ",".join(unknown))
    return out


def aggregate(brd, arts: dict[str, Any]) -> dict:
    claims = [c for n in ARTS for c in iter_claims(n, arts[n])]
    cited = sum(1 for c in claims if c[3])
    covered = {r for c in claims for r in c[2]} | {r for t in arts["plan_generator"].team for r in t.brd_refs}
    return {"claims": len(claims), "groundedness": round(cited / len(claims), 3) if claims else 0,
            "coverage": round(len(covered & brd.req_ids) / len(brd.req_ids), 3)}


# ------------------------------------------------------------------ 2. LLM-as-Judge (+ heuristic proxy)
def judge(llm, name: str, art, retriever, span: dict | None = None) -> dict:
    from ..agents.critic import actionability
    span = span if span is not None else {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "guardrail_triggers": []}
    if not llm.offline:
        j = llm.judge(EVAL_JUDGE, f"ARTIFACT TYPE: {name}\n{art.model_dump_json()[:12000]}", span)
        if j and all(k in j for k in ("actionability", "specificity", "grounding_quality", "em_readiness")):
            return {**{k: float(j[k]) for k in ("actionability", "specificity", "grounding_quality", "em_readiness")},
                    "judge_mode": "llm", "rationale": j.get("rationale", "")[:300]}
    # ---- transparent heuristic proxy (offline)
    act, _ = actionability(name, art)
    text = art.model_dump_json()
    words = max(1, len(re.findall(r"[A-Za-z]+", text)))
    concrete = len(re.findall(r"\b\d+(?:\.\d+)?\s*(?:%|ms|weeks?|wks|s\b|x\b|person-weeks)|\b(?:FR|NFR|INT|CON)-\d+", text))
    specificity = round(min(5.0, 1 + 4 * min(1.0, concrete / (words / 25))), 2)
    claims = iter_claims(name, art)
    sup = [retriever.support(c[1], c[3]) for c in claims if c[3]]
    gq = round(min(5.0, 1 + 4 * min(1.0, (sum(sup) / len(sup)) / 0.35)) if sup else 1.0, 2)
    flags = getattr(art, "flags", [])
    resolved = (sum(1 for f in flags if f.resolution) / len(flags)) if flags else 1.0
    em = round(1 + 4 * (0.5 * resolved + 0.25 * bool(getattr(art, "assumptions", None) is not None) +
                        0.25 * (act >= 4)), 2)
    return {"actionability": act, "specificity": specificity, "grounding_quality": gq, "em_readiness": em,
            "judge_mode": "heuristic-proxy"}


# ------------------------------------------------------------------ 4. reference-based
def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def rouge_l(candidate: str, reference: str) -> float:
    a, b = _tok(candidate), _tok(reference)
    if not a or not b:
        return 0.0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    lcs = prev[-1]
    p, r = lcs / len(a), lcs / len(b)
    return round(2 * p * r / (p + r), 3) if p + r else 0.0


def artifact_summary(arts: dict[str, Any]) -> str:
    plan, sch, arch, poc, stk = (arts[k] for k in ARTS)
    rec = next(o for o in stk.options if o.id == stk.recommended_option_id)
    return (f"{len(plan.phases)}-phase plan: " + ", ".join(p.name for p in plan.phases) + ". "
            f"{arch.pattern.name} with " + ", ".join(c.name for c in arch.components) + ". "
            f"Schedule {sch.total_duration_weeks:g} weeks p50 with {sch.headcount} engineers. "
            f"PoC on " + ", ".join(c.name for c in arch.components if c.id in poc.in_scope_component_ids) + ". "
            f"Recommended stack: " + ", ".join(rec.components.values()) + ".")
