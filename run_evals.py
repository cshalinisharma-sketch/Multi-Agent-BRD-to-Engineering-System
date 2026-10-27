#!/usr/bin/env python3
"""Evaluation harness.

Runs every BRD in eval_dataset/brds through the pipeline (non-interactive HITL),
for one or both retrieval profiles, and scores the outputs with four methods
(rule-based, LLM-as-Judge / heuristic proxy, execution-based, reference-based
ROUGE-L) plus expected-outcome checks and Critic calibration.

  python run_evals.py                      # both profiles -> eval_results/eval_report.md
  python run_evals.py --profiles tuned
  python run_evals.py --profiles tuned --provider openai --allow-external   # live LLM (costs tokens)
"""
import argparse
import json
import os
import statistics
from pathlib import Path

from src.agents.critic import ARTIFACTS
from src.agents.orchestrator import Pipeline
from src.config import EVAL_DIR, OUTPUT_DIR, PROFILES, ROOT, RunOptions
from sklearn.metrics import cohen_kappa_score, confusion_matrix, precision_recall_fscore_support

from src.llm import ALLOW_EXTERNAL_ENV, LLMClient
from src.evals.metrics import aggregate, artifact_summary, judge, load_models, rouge_l, rule_checks
from src.rag.retriever import Retriever

RES_DIR = ROOT / "eval_results"


def artifacts_at(state, rnd: int) -> dict:
    out = {}
    for r in state.revisions:
        if r["round"] <= rnd:
            out[r["agent"]] = r["artifact"]
    return out


def expected_checks(exp: dict, state, arts) -> list[dict]:
    res = []
    c = lambda name, ok, detail="": res.append({"check": name, "pass": bool(ok), "detail": detail})
    c("status", state.status == exp["expected_status"], state.status)
    if state.status != "completed" or exp["expected_status"] != "completed":
        return res
    arch, sch, stk = arts["solution_architect"], arts["schedule_estimator"], arts["tech_stack_recommender"]
    c("pattern acceptable", arch.pattern.pattern_id in exp["acceptable_patterns"], arch.pattern.pattern_id)
    lo, hi = exp["p50_weeks_range"]
    c("p50 within expert range", lo <= sch.total_duration_weeks <= hi, f"{sch.total_duration_weeks} vs {lo}-{hi}")
    kinds = {f.kind for f in state.brd.flags} | {f.kind for f in sch.flags}
    for k in exp.get("required_flag_kinds", []):
        c(f"flag raised: {k}", k in kinds)
    if "min_contradictions" in exp:
        n = sum(f.kind == "contradiction" for f in state.brd.flags)
        c("contradictions detected", n >= exp["min_contradictions"], str(n))
    if "min_ambiguity_flags" in exp:
        n = sum(f.kind == "ambiguity" for f in state.brd.flags)
        c("ambiguities detected", n >= exp["min_ambiguity_flags"], str(n))
    rec = next(o for o in stk.options if o.id == stk.recommended_option_id)
    if exp.get("stack_must_not_be_serverless"):
        c("recommended stack is not serverless", "Lambda" not in rec.components.get("runtime", ""), rec.name)
    for t in exp.get("stack_must_include", []):
        c(f"stack includes {t}", any(t.lower() in v.lower() for v in rec.components.values()))
    if exp.get("requires_default_slo_assumption"):
        c("default SLO assumption recorded", any("default SLO" in a for a in arch.assumptions))
    blob = json.dumps({k: v.model_dump() for k, v in arts.items()}).lower()
    for t in exp.get("forbidden_terms", []):
        c(f"forbidden term absent: '{t}'", t not in blob)
    if "must_not_have_requirement" in exp:
        c(f"{exp['must_not_have_requirement']} quarantined", state.brd.req(exp["must_not_have_requirement"]) is None)
    got = {g.get("type") for g in state.guardrail_events}
    for g in exp.get("expect_guardrails", []):
        c(f"guardrail fired: {g}", g in got)
    return res


def eval_profile(profile: str, llm: LLMClient) -> dict:
    pipe = Pipeline(RunOptions(profile=profile, auto_approve=True, export=True, run_label=f"eval-{profile}",
                               extra={"quiet": True}), llm=llm, output_dir=OUTPUT_DIR / "evals" / profile)
    rows = []
    for brd in sorted((EVAL_DIR / "brds").iterdir()):
        exp = json.loads((EVAL_DIR / "expected" / f"{brd.stem}.json").read_text())
        st = pipe.run(brd)
        summ = json.loads((st.run_dir / "summary.json").read_text())
        row = {"brd": brd.stem, "type": exp["type"], "status": st.status, "run_dir": str(st.run_dir.relative_to(ROOT))}
        if st.status != "completed":
            row["expected_checks"] = expected_checks(exp, st, {})
            row["guardrails"] = [g.get("type") for g in st.guardrail_events]
            row["reasons"] = st.errors
            rows.append(row)
            continue
        retr = Retriever(pipe.store, PROFILES[profile])
        rounds = []
        for rep in st.critic_reports:
            arts = load_models(artifacts_at(st, rep.revision_round))
            rc = rule_checks(st.brd, arts, pipe.store)
            agg = aggregate(st.brd, arts)
            rounds.append({
                "round": rep.revision_round, "overall": rep.overall_score, "badge": rep.overall_badge,
                "rule_pass_rate": round(sum(x["pass"] for x in rc) / len(rc), 3),
                "rule_failures": [x["check"] + (f" ({x['detail']})" if x["detail"] else "") for x in rc if not x["pass"]],
                "groundedness": agg["groundedness"], "coverage": agg["coverage"],
                "contradictions": sum(1 for v in rep.cross_agent_checks.values() if not v),
                "actionability": round(statistics.mean(s.actionability for s in rep.artifact_scores), 2),
                "issues": len(rep.issues), "issue_codes": sorted({i.code for i in rep.issues}),
                "rouge_l": rouge_l(artifact_summary(arts), exp.get("reference_summary", "")),
                "artifact_badges": {s.artifact: s.badge for s in rep.artifact_scores},
            })
        final_arts = load_models(artifacts_at(st, st.critic_reports[-1].revision_round))
        judges = {n: judge(pipe.llm, n, final_arts[n], retr) for n in ARTIFACTS}
        m = summ["metrics"]
        row.update({
            "final_badge": summ["final_badge"], "final_score": summ["final_score"], "revision_rounds": summ["revision_rounds"],
            "rounds": rounds,
            "judge": {k: round(statistics.mean(j[k] for j in judges.values()), 2)
                      for k in ("actionability", "specificity", "grounding_quality", "em_readiness")},
            "judge_mode": next(iter(judges.values()))["judge_mode"],
            "execution": {"schema_parse_rate": round(1 - m["contract_violations"] / max(1, m["agent_executions"]), 3),
                          "e2e_completed": True, "tool_call_success_rate": m["tool_call_success_rate"],
                          "agent_executions": m["agent_executions"], "guardrail_triggers": m["guardrail_triggers"],
                          "latency_ms": round(sum(v["latency_ms"] for v in m["by_agent"].values()), 1),
                          "cost_usd": round(sum(v["cost_usd"] for v in m["by_agent"].values()), 4)},
            "escalations": [f["id"] for f in summ["escalations"]],
            "guardrails": [g.get("type") for g in st.guardrail_events],
            "expected_checks": expected_checks(exp, st, final_arts),
            "critic_round0": {s.artifact: s.scores for s in st.critic_reports[0].artifact_scores},
        })
        rows.append(row)
        print(f"  [{profile}] {brd.stem}: {row['final_badge']} {row['final_score']} after {row['revision_rounds']} rev "
              f"(round0 {rounds[0]['badge']} {rounds[0]['overall']})")
    return {"profile": profile, "provider": pipe.llm.provider, "rows": rows}


def calibration(results: dict) -> dict | None:
    f = EVAL_DIR / "critic_calibration.json"
    if not f.exists() or "tuned" not in results:
        return None
    ref = json.loads(f.read_text())
    rows = {r["brd"]: r for r in results["tuned"]["rows"] if r["status"] == "completed"}
    errs, agree, out = [], [], []
    y_expert, y_critic = [], []  # pass (meets threshold) = 1, per artifact x dimension
    thr = {"groundedness": 4, "completeness": 5, "consistency": 5, "actionability": 4}
    for item in ref["items"]:
        crit = rows.get(item["brd"], {}).get("critic_round0", {}).get(item["artifact"])
        if not crit:
            continue
        for d, v in item["expert"].items():
            errs.append(abs(crit[d] - v))
            agree.append((crit[d] >= thr[d]) == (v >= thr[d]))
            y_expert.append(int(v >= thr[d]))
            y_critic.append(int(crit[d] >= thr[d]))
        out.append({"brd": item["brd"], "artifact": item["artifact"], "expert": item["expert"],
                    "critic": {d: crit[d] for d in item["expert"]}})
    cls = classification(y_expert, y_critic) if y_expert else None
    return {"n_items": len(out), "mae": round(statistics.mean(errs), 2) if errs else None,
            "verdict_agreement": round(sum(agree) / len(agree), 3) if agree else None,
            "classification": cls, "items": out}


def classification(y_true: list[int], y_pred: list[int]) -> dict:
    """scikit-learn metrics for the Critic's pass/fail verdicts vs the expert reference. "Fail" (needs
    revision) is the positive class: a Critic that misses real problems has low recall."""
    fails_true = [1 - y for y in y_true]
    fails_pred = [1 - y for y in y_pred]
    p, r, f1, _ = precision_recall_fscore_support(fails_true, fails_pred, average="binary", zero_division=0)
    tn, fp, fn, tp = confusion_matrix(fails_true, fails_pred, labels=[0, 1]).ravel()
    kappa = cohen_kappa_score(y_true, y_pred) if len(set(y_true) | set(y_pred)) > 1 else None
    return {"n": len(y_true), "precision": round(float(p), 3), "recall": round(float(r), 3), "f1": round(float(f1), 3),
            "cohen_kappa": round(float(kappa), 3) if kappa is not None else None,
            "confusion": {"tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn)}}


def classification_lines(c: dict) -> list[str]:
    m = c["confusion"]
    return ["Critic \"needs revision\" verdicts vs expert (scikit-learn, positive class = fail, "
            f"n = {c['n']} artifact x dimension pairs): precision {c['precision']}, recall {c['recall']}, "
            f"F1 {c['f1']}, Cohen's kappa {c['cohen_kappa']} (TP {m['tp']}, FP {m['fp']}, FN {m['fn']}, TN {m['tn']}).", ""]


def md_report(results: dict, calib) -> str:
    L = ["# Evaluation results (generated by run_evals.py)", ""]
    for prof, res in results.items():
        L += [f"## Profile `{prof}` (provider: {res['provider']})", "",
              "| BRD | Type | Status | Round-0 | Final | Revisions | Rule pass R0→Final | Grounded R0→Final | Coverage R0→Final | X-agent contradictions R0→Final | ROUGE-L | Expected checks |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in res["rows"]:
            ec = r["expected_checks"]
            ecs = f"{sum(x['pass'] for x in ec)}/{len(ec)}"
            if r["status"] != "completed":
                L.append(f"| {r['brd']} | {r['type']} | {r['status']} | – | – | – | – | – | – | – | – | {ecs} |")
                continue
            a, z = r["rounds"][0], r["rounds"][-1]
            L.append(f"| {r['brd']} | {r['type']} | {r['status']} | {a['badge']} {a['overall']} | {z['badge']} {z['overall']} | "
                     f"{r['revision_rounds']} | {a['rule_pass_rate']:.0%}→{z['rule_pass_rate']:.0%} | {a['groundedness']:.0%}→{z['groundedness']:.0%} | "
                     f"{a['coverage']:.0%}→{z['coverage']:.0%} | {a['contradictions']}→{z['contradictions']} | {z['rouge_l']} | {ecs} |")
        done = [r for r in res["rows"] if r["status"] == "completed"]
        L += ["", "**LLM-as-Judge** (mode: " + (done[0]["judge_mode"] if done else "n/a") + ")", "",
              "| BRD | Actionability | Specificity | Grounding quality | EM-readiness |", "|---|---|---|---|---|"]
        L += [f"| {r['brd']} | {r['judge']['actionability']} | {r['judge']['specificity']} | {r['judge']['grounding_quality']} | "
              f"{r['judge']['em_readiness']} |" for r in done]
        L += ["", "**Execution-based**", "", "| BRD | Schema parse rate | Tool success | Agent runs | Guardrail triggers | Latency ms | Cost $ |",
              "|---|---|---|---|---|---|---|"]
        L += [f"| {r['brd']} | {r['execution']['schema_parse_rate']:.0%} | {r['execution']['tool_call_success_rate']} | "
              f"{r['execution']['agent_executions']} | {r['execution']['guardrail_triggers']} | {r['execution']['latency_ms']} | "
              f"{r['execution']['cost_usd']} |" for r in done]
        L += ["", "**Expected-outcome / guardrail checks (failures only)**", ""]
        fails = [(r["brd"], x) for r in res["rows"] for x in r["expected_checks"] if not x["pass"]]
        L += [f"- {b}: {x['check']} ({x['detail']})" for b, x in fails] or ["- none — all expected checks passed"]
        L += ["", "**Revision trace (issues per round)**", ""]
        for r in done:
            L.append(f"- {r['brd']}: " + " → ".join(f"R{x['round']} {x['badge']} {x['overall']} [{', '.join(x['issue_codes']) or 'no issues'}]"
                                                    for x in r["rounds"]))
        L.append("")
    if len(results) == 2:
        b, t = results["baseline"]["rows"], results["tuned"]["rows"]
        pairs = [(x, y) for x in b for y in t if x["brd"] == y["brd"] and x["status"] == y["status"] == "completed"]
        mean = lambda rows, f: round(statistics.mean(f(r) for r in rows), 3)
        L += ["## Cycle improvement: baseline vs tuned retrieval", "",
              "| Metric (mean over completed BRDs) | Baseline R0 | Tuned R0 | Baseline final | Tuned final |", "|---|---|---|---|---|"]
        for name, f0, ff in [
            ("Critic overall score", lambda r: r["rounds"][0]["overall"], lambda r: r["rounds"][-1]["overall"]),
            ("Groundedness (claims cited)", lambda r: r["rounds"][0]["groundedness"], lambda r: r["rounds"][-1]["groundedness"]),
            ("Rule-based pass rate", lambda r: r["rounds"][0]["rule_pass_rate"], lambda r: r["rounds"][-1]["rule_pass_rate"]),
            ("Actionability", lambda r: r["rounds"][0]["actionability"], lambda r: r["rounds"][-1]["actionability"]),
            ("Critic issues", lambda r: r["rounds"][0]["issues"], lambda r: r["rounds"][-1]["issues"]),
        ]:
            L.append(f"| {name} | {mean([x for x, _ in pairs], f0)} | {mean([y for _, y in pairs], f0)} | "
                     f"{mean([x for x, _ in pairs], ff)} | {mean([y for _, y in pairs], ff)} |")
        L.append(f"| Revision rounds needed | – | – | {mean([x for x, _ in pairs], lambda r: r['revision_rounds'])} | "
                 f"{mean([y for _, y in pairs], lambda r: r['revision_rounds'])} |")
        L.append(f"| Green at round 0 (count) | {sum(x['rounds'][0]['badge'] == 'GREEN' for x, _ in pairs)} | "
                 f"{sum(y['rounds'][0]['badge'] == 'GREEN' for _, y in pairs)} | – | – |")
        L.append("")
    if calib:
        L += ["## Critic calibration vs expert reference scores", "",
              f"{calib['n_items']} artifacts, MAE {calib['mae']} (1-5 scale), pass/fail verdict agreement {calib['verdict_agreement']:.0%}", "",
              *(classification_lines(calib["classification"]) if calib.get("classification") else []),
              "| BRD | Artifact | Expert (G/C/Co/A) | Critic (G/C/Co/A) |", "|---|---|---|---|"]
        for it in calib["items"]:
            e, c = it["expert"], it["critic"]
            L.append(f"| {it['brd']} | {it['artifact']} | {'/'.join(str(e[k]) for k in e)} | {'/'.join(str(c[k]) for k in e)} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", nargs="+", default=["baseline", "tuned"], choices=list(PROFILES))
    ap.add_argument("--provider", default="offline", choices=["offline", "openai", "anthropic"],
                    help="offline (default) keeps the eval reproducible and free")
    ap.add_argument("--allow-external", action="store_true", help=f"same as {ALLOW_EXTERNAL_ENV}=1")
    a = ap.parse_args()
    if a.allow_external:
        os.environ[ALLOW_EXTERNAL_ENV] = "1"
    llm = LLMClient(provider=a.provider)
    RES_DIR.mkdir(exist_ok=True)
    results = {}
    for p in a.profiles:
        results[p] = eval_profile(p, llm)
        (RES_DIR / f"results_{p}.json").write_text(json.dumps(results[p], indent=2, default=str))
    calib = calibration(results)
    (RES_DIR / "eval_report.md").write_text(md_report(results, calib), encoding="utf-8")
    print(f"report: {RES_DIR / 'eval_report.md'}")


if __name__ == "__main__":
    main()
