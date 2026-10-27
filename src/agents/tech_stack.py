"""Agent 6 — Tech Stack Recommender (Design group).

Agent -> Decision: the agent inspects the architecture and decides which lookup
tools to call (decision-log lookup per component category, standards/familiarity
lookup, on-prem exception policy). Options are scored on scalability, team
familiarity, integration risk and cost using the retrieved familiarity matrix
and past decision outcomes.
"""
from __future__ import annotations

import re

from ..contracts import StackOption, TechStackRecommendation, ToolDecision
from .base import BaseAgent, FixContext

CATEGORY_TO_LOG = {"messaging": "messaging", "stream-processing": "stream-processing", "search": "search",
                   "database": "database", "cache": "cache", "frontend": "frontend", "service": "backend",
                   "integration": "integration", "analytics": "read-model", "worker": "serverless"}

# technology -> familiarity-matrix key
FAM_KEY = {"Java 21 + Spring Boot 3": "Java/Spring Boot", "Python 3.12 + FastAPI": "Python/FastAPI",
           "React 18 + TypeScript": "React/TypeScript", "PostgreSQL 16 (RDS)": "PostgreSQL", "Redis (ElastiCache)": "Redis",
           "Amazon SQS/SNS": "SQS/SNS", "Kafka on AWS MSK": "Kafka/MSK", "Kafka Streams": "Kafka Streams",
           "Apache Flink": "Flink", "Amazon DynamoDB": "DynamoDB", "Amazon OpenSearch": "OpenSearch",
           "AWS Lambda + API Gateway": "AWS Lambda", "Amazon EKS": "EKS", "ECS Fargate": "ECS Fargate",
           "Terraform": "Terraform", "Kubernetes (portable, EKS or on-prem)": "EKS"}
# approved list per org standards v2026.1 (Flink and Go need ARB approval)
APPROVED = (set(FAM_KEY) - {"Apache Flink"}) | {"Amazon S3"}


class TechStackRecommender(BaseAgent):
    name = "tech_stack_recommender"
    output_model = TechStackRecommendation

    def upstream(self):
        return {"architecture": self.ctx.artifacts["solution_architect"], "schedule": self.ctx.artifacts.get("schedule_estimator")}

    def decide_tools(self) -> list[ToolDecision]:
        arch = self.ctx.artifacts["solution_architect"]
        cats = sorted({c.category for c in arch.components})
        dec = [ToolDecision(tool="standards_lookup", reason="approved stack and team familiarity matrix are always required",
                            query="approved technology stack team familiarity matrix scores")]
        for cat in cats:
            if cat in CATEGORY_TO_LOG:
                dec.append(ToolDecision(tool="decision_log_lookup", reason=f"architecture has a {cat} component",
                                        query=f"{CATEGORY_TO_LOG[cat]} decision outcome"))
        if (self.brd.constraints.deployment or "").startswith(("on-prem", "conflict")):
            dec.append(ToolDecision(tool="standards_lookup", reason="BRD mentions on-premises deployment",
                                    query="on-premises exception serverless unavailable"))
        return dec

    def retrieve(self, span, fix):
        hits = []
        decisions = self.decide_tools()
        span.setdefault("decisions", []).append({"decision": "tool_selection", "tools": [d.model_dump() for d in decisions]})
        for d in decisions:
            if d.tool == "standards_lookup":
                hits += self.search(d.query, span, source_types=["standards"], top_k=2)
            else:
                cat = d.query.split(" decision")[0]
                hits += self.search(d.query, span, source_types=["tech_decision"], top_k=2, where={"category": cat})
        self._decisions = decisions
        return list({h.chunk_id: h for h in hits}.values())

    @staticmethod
    def familiarity(hits) -> dict[str, int]:
        for h in hits:
            if "Familiarity Matrix" in h.text:
                return {k.strip(): int(v) for k, v in re.findall(r"([A-Za-z/ .]+?)\s(\d);?", h.text.split("2026.")[-1])}
        return {}

    def heuristic(self, hits, upstream, fix: FixContext, span):
        b, arch = self.brd, upstream["architecture"]
        fam = self.familiarity(hits)
        cats = {c.category for c in arch.components}
        event = arch.pattern.pattern_id == "event-driven" or "messaging" in cats
        on_prem = (b.constraints.deployment or "").startswith(("on-prem", "conflict"))
        text = " ".join(r.text for r in b.requirements).lower()
        eps = max([int(x.replace(",", "")) for x in re.findall(r"(\d[\d,]*)\s+(?:authorization )?events per second", text)] or [0])

        def stack(backend, db, msg=None, stream=None, runtime="ECS Fargate", extra=None):
            s = {"backend": backend, "frontend": "React 18 + TypeScript", "database": db, "runtime": runtime, "iac": "Terraform"}
            if "cache" in cats:
                s["cache"] = "Redis (ElastiCache)"
            if msg and ("messaging" in cats or "worker" in cats):
                s["messaging"] = msg
            if stream and "stream-processing" in cats:
                s["stream-processing"] = stream
            if "search" in cats:
                s["search"] = "Amazon OpenSearch"
            if "storage" in cats:
                s["storage"] = "Amazon S3"
            s.update(extra or {})
            return s

        golden_msg = "Kafka on AWS MSK" if (event and eps >= 500) or "stream-processing" in cats else "Amazon SQS/SNS"
        opts = [("OPT-A", "Org golden path (containers + managed AWS data services)",
                 stack("Java 21 + Spring Boot 3", "PostgreSQL 16 (RDS)", golden_msg, "Kafka Streams"))]
        if on_prem:
            opts.append(("OPT-B", "Portable Kubernetes (cloud or on-prem)",
                         stack("Java 21 + Spring Boot 3", "PostgreSQL 16 (RDS)", "Kafka on AWS MSK", "Kafka Streams",
                               runtime="Kubernetes (portable, EKS or on-prem)")))
        else:
            opts.append(("OPT-B", "Serverless-first (Lambda + managed services)",
                         stack("AWS Lambda + API Gateway", "Amazon DynamoDB", "Amazon SQS/SNS", "Kafka Streams",
                               runtime="AWS Lambda + API Gateway")))
        if event:
            opts.append(("OPT-C", "High-throughput streaming specialist",
                         stack("Java 21 + Spring Boot 3", "Amazon DynamoDB", "Kafka on AWS MSK", "Apache Flink", runtime="Amazon EKS")))
        else:
            opts.append(("OPT-C", "Python lean stack", stack("Python 3.12 + FastAPI", "PostgreSQL 16 (RDS)", "Amazon SQS/SNS")))

        log = [h for h in hits if h.metadata.get("source_type") == "tech_decision"]
        hi_scale = bool(eps >= 1000 or re.search(r"3x peak|99\.99", text))
        weights = ({"scalability": 0.40, "team_familiarity": 0.25, "integration_risk": 0.20, "cost": 0.15} if hi_scale else
                   {"scalability": 0.20, "team_familiarity": 0.35, "integration_risk": 0.25, "cost": 0.20})
        if "familiarity_risk" in fix.codes():
            weights = {"scalability": 0.20, "team_familiarity": 0.45, "integration_risk": 0.20, "cost": 0.15}

        options = []
        for oid, name, comps in opts:
            techs = list(dict.fromkeys(comps.values()))
            known = [t for t in techs if FAM_KEY.get(t) in fam]  # managed services absent from the matrix are neutral
            fscores = [fam[FAM_KEY[t]] for t in known] or [3]
            # backend and database dominate day-to-day work, so they count double
            core = [fam[FAM_KEY[comps[k]]] for k in ("backend", "database") if k in comps and FAM_KEY.get(comps[k]) in fam]
            familiarity = max(1, min(5, int((sum(fscores) + sum(core)) / (len(fscores) + len(core)) + 0.5)))
            low_fam = [t for t, f in zip(known, fscores) if f <= 2]
            bad_outcomes = [h for h in log if any(t.split()[0].lower() in h.metadata.get("decision", "").lower() for t in techs)
                            and h.metadata.get("outcome_rating", 5) <= 3]
            approved = all(t in APPROVED for t in techs)
            relational = bool(re.search(r"audit|ledger|report|approv|balance|transaction|retain", text))
            nosql_misfit = relational and comps.get("database") == "Amazon DynamoDB" and not hi_scale
            risk = max(1, min(5, 2 + len(bad_outcomes) + (not approved) + (len(low_fam) >= 2) + nosql_misfit))
            serverless = "Lambda" in comps.get("runtime", "")
            # containers with autoscaling = 4; dedicated stream processor = 5; single-process Python = 3
            scal = 5 if "Flink" in " ".join(techs) else (3 if comps["backend"].startswith("Python") else 4)
            cost = 2 if serverless and not hi_scale else (4 if serverless or "EKS" in comps.get("runtime", "") or "Kubernetes" in comps.get("runtime", "") else 3)
            score = round(weights["scalability"] * scal + weights["team_familiarity"] * familiarity +
                          weights["integration_risk"] * (6 - risk) + weights["cost"] * (6 - cost), 2)
            pros, cons = [], []
            if familiarity >= 4:
                pros.append(f"high team familiarity (avg {sum(fscores) / len(fscores):.1f}/5 on the org matrix)")
            if approved:
                pros.append("entirely on the org approved list; no ARB exception needed")
            if scal >= 4:
                pros.append("scales horizontally for the stated peak load" if hi_scale else "comfortable headroom for growth")
            if cost <= 2:
                pros.append("pay-per-use cost at low steady volume")
            if nosql_misfit:
                cons.append("key-value store is a poor fit for relational audit/reporting queries (org default is PostgreSQL)")
            if low_fam:
                cons.append(f"low team familiarity with {', '.join(low_fam)} (matrix <= 2)")
            for h in bad_outcomes[:2]:
                cons.append(f"past decision {h.metadata['doc_id']} rated {h.metadata['outcome_rating']}/5 ({h.metadata['decision']})")
            if not approved:
                cons.append("requires architecture review board exception")
            if serverless and on_prem:
                cons.append("serverless is unavailable on-premises")
            if serverless:
                cons.append("cold starts and vendor lock-in; harder local testing")
            if scal <= 3:
                cons.append("least headroom if volume grows beyond the BRD")
            if not cons:
                cons.append("standard operational overhead of containers")
            if not pros:
                pros.append("simple to reason about")
            claim = f"{name}: " + "; ".join(pros + cons)
            options.append(StackOption(id=oid, name=name, components=comps, scalability=scal, team_familiarity=familiarity,
                                       integration_risk=risk, cost=cost, weighted_score=score, pros=pros, cons=cons,
                                       on_approved_list=approved, brd_refs=self.routed(),
                                       citations=self.cite(claim, hits, 3)))
            if not options[-1].citations:
                options[-1].citations = [h.chunk_id for h in hits if "Familiarity Matrix" in h.text][:1]
        feasible = [o for o in options if not (on_prem and "Lambda" in o.components.get("runtime", ""))]
        rec = max(feasible, key=lambda o: o.weighted_score)
        assumptions = []
        if on_prem:
            assumptions.append("Deployment target unresolved (on-prem vs AWS): recommendation limited to cloud-portable options.")
        if not fam:
            assumptions.append("Team familiarity matrix not retrieved; neutral score 3 used.")
        return TechStackRecommendation(
            options=options, recommended_option_id=rec.id, weights=weights,
            rationale=(f"{rec.name} has the best weighted score ({rec.weighted_score}) with weights {weights}: "
                       f"scalability {rec.scalability}/5, familiarity {rec.team_familiarity}/5, integration risk "
                       f"{rec.integration_risk}/5, cost {rec.cost}/5."),
            tool_decisions=self._decisions, assumptions=assumptions)

    def summarize(self, out):
        return {"recommended": out.recommended_option_id, "options": [(o.id, o.weighted_score) for o in out.options],
                "tools": [d.tool for d in out.tool_decisions]}
