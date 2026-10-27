"""Agent 4 — Solution Architect (Design group).

Pattern selection = retrieval relevance + explicit signal matching against the
pattern library + hard constraints (deployment target, team size). Components
are derived from requirement subcategories; NFRs are mapped to mechanisms
grounded in org standards.
"""
from __future__ import annotations

import re

from ..contracts import Architecture, Component, DataFlow, Flag, NFRMapping, PatternChoice
from .base import BaseAgent, FixContext, short

UI_WORDS = ("portal", "console", "dashboard", "view", "web", "sign in", "search box", "see ", "website")

NFR_MECHANISMS = {
    "performance": ("Redis cache for hot reads, stateless services with horizontal autoscaling on latency, "
                    "load test at 2x target load before launch", ["service", "cache", "frontend"]),
    "availability": ("Multi-AZ deployment with health checks and rolling deploys; retries with backoff and "
                     "dead-letter handling for asynchronous work; SLO burn-rate alerts", ["service", "database", "messaging"]),
    "security": ("Corporate SSO (OIDC) and OAuth2 for external users, RBAC enforced in the service layer, KMS encryption "
                 "at rest, TLS 1.2+ in transit, secrets in Secrets Manager, card data tokenised via the payments vault",
                 ["auth", "service", "database", "storage"]),
    "compliance": ("Append-only audit log table with retention policy and immutable backups; access logged and reviewed",
                   ["database", "service"]),
    "scalability": ("Stateless containers on ECS Fargate with target-tracking autoscaling; broker partitions and "
                    "consumer groups sized for 3x peak", ["service", "messaging", "stream-processing"]),
    "usability": ("Org design-system components and moderated usability testing of the primary flow",
                  ["frontend"]),
    "deployment": ("Containerised services with no managed-serverless dependency so the system stays portable "
                   "between AWS and an on-premises Kubernetes cluster", ["service"]),
    "general": ("Addressed through standard service design and verified in hardening", ["service"]),
}


def parse_pattern(text: str) -> dict:
    g = lambda k: (re.search(rf"{k}:\s*(.+)", text) or [None, ""])[1]
    return {"id": g("pattern_id").strip(), "name": text.splitlines()[0].strip(),
            "signals": [s.strip() for s in g("Signals").split(",") if s.strip()],
            "complexity": int(g("Complexity") or 3), "tradeoffs": g("Trade-offs").strip()}


class SolutionArchitect(BaseAgent):
    name = "solution_architect"
    output_model = Architecture

    def retrieve(self, span, fix):
        b = self.brd
        nfr = " ".join(r.text for r in b.requirements if r.category == "non_functional")
        fn = " ".join(r.subcategory for r in b.requirements if r.category == "functional")
        # the pattern library is small: score every pattern (no similarity cut-off), then rank with signals
        hits = self.search(f"{b.title}. {' '.join(b.objectives)} {nfr} {fn}", span, top_k=9,
                           source_types=["architecture_pattern"], threshold=0.0)
        hits += self.search("approved technology stack architecture review criteria security privacy encryption SSO", span,
                            source_types=["standards"])
        hits += self.search("default service level objectives latency availability observability", span,
                            source_types=["standards"], top_k=2)
        hits += self.search(f"{b.domain} {b.title} past project architecture lessons", span, source_types=["past_brd"], top_k=3)
        return list({h.chunk_id: h for h in hits}.values())

    # ---------------------------------------------------------------- pattern decision
    def choose_pattern(self, hits, span):
        b = self.brd
        text = " ".join([b.title] + b.objectives + b.in_scope + [r.text for r in b.requirements]).lower()
        pats = [(h, parse_pattern(h.text)) for h in hits if h.metadata.get("source_type") == "architecture_pattern"]
        scored = []
        n_fn = sum(r.category == "functional" for r in b.requirements)
        realtime = bool(re.search(r"real[- ]time|events per second|stream", text))
        on_prem = (b.constraints.deployment or "").startswith(("on-prem", "conflict"))
        subcats = [r.subcategory for r in b.requirements if r.category == "functional"]
        words = set(re.findall(r"[a-z0-9]+", text))
        stems = {w[:6] for w in words}

        def signal_hit(sig: str) -> bool:  # every word of the signal phrase appears (6-char prefix stemming)
            toks = [t for t in re.findall(r"[a-z0-9]+", sig.lower()) if len(t) > 2]
            return bool(toks) and all((t[:6] in stems) if len(t) >= 6 else (t in words) for t in toks)

        for h, p in pats:
            sig = sum(1 for s in p["signals"] if signal_hit(s))
            score = 2.0 * h.score + 0.5 * min(sig, 6)
            notes = [f"retrieval {h.score:.2f}", f"{sig} signals"]
            if p["id"] == "serverless" and on_prem:
                score -= 10; notes.append("excluded: on-prem constraint")
            if p["id"] == "microservices" and (b.constraints.team_size or 6) <= 8:
                score -= 1.5; notes.append("single small team")
            if p["id"] == "event-driven" and realtime:
                score += 1.5; notes.append("real-time/throughput NFR")
            if p["id"] == "search-centric":
                if subcats.count("search") >= 2:
                    score += 1.0; notes.append("search is core value")
                elif subcats.count("search") == 0:
                    score -= 1.0; notes.append("no search requirements")
            if p["id"] == "event-driven" and not realtime:
                score -= 1.0; notes.append("no real-time/streaming need")
            if p["id"] in ("layered", "modular-monolith") and n_fn <= 6 and not realtime:
                score += 0.5; notes.append("small functional scope")
            if p["id"] == "modular-monolith" and (b.constraints.team_size or 6) <= 8 and not realtime and n_fn > 6:
                score += 0.5; notes.append("one team, transactional workflow")
            if p["id"] == "cqrs" and not any(r.subcategory == "reporting" and r.priority == "must" for r in b.requirements):
                score -= 0.5; notes.append("reporting is not a Must")
            scored.append((round(score, 3), p, h, notes))
        scored.sort(key=lambda x: -x[0])
        span.setdefault("decisions", []).append(
            {"decision": "architecture_pattern", "ranking": [(s, p["id"], n) for s, p, _, n in scored[:4]]})
        return scored

    def heuristic(self, hits, upstream, fix: FixContext, span):
        b = self.brd
        scored = self.choose_pattern(hits, span)
        _, pat, phit, notes = scored[0]
        alts = scored[1:3]
        fn = [r for r in b.requirements if r.category == "functional"]
        integ = [r for r in b.requirements if r.category == "integration"]
        nfr = [r for r in b.requirements if r.category == "non_functional"]
        by = lambda *subs: [r for r in fn if r.subcategory in subs]
        comps: list[Component] = []

        def add(name, resp, cat, refs, kind="feature"):
            cid = f"C{len(comps) + 1}"
            text = f"{name}: {resp}"
            if not refs:
                kind = "enabler"  # infrastructure with no direct requirement; must be justified by a standards citation
            comps.append(Component(id=cid, name=name, responsibility=resp, category=cat, kind=kind,
                                   brd_refs=sorted(set(refs)), citations=self.cite(text, hits)))
            return cid

        ui = [r for r in fn if any(w in r.text.lower() for w in UI_WORDS) or r.subcategory in ("reporting", "search", "documents")]
        ids = {}
        if ui:
            ids["frontend"] = add("Web Frontend (React SPA)", "user-facing screens for " + ", ".join(r.id for r in ui),
                                  "frontend", [r.id for r in ui])
        event = pat["id"] == "event-driven"
        if event:
            ing = by("ingestion")
            ids["ingest"] = add("Ingestion Adapters", "consume external events, validate and normalise them into canonical events",
                                "integration", [r.id for r in ing] + [r.id for r in integ if r.subcategory == "ingestion"])
            ids["broker"] = add("Event Broker", "durable, partitioned event log with replay and dead-letter topics",
                                "messaging", [r.id for r in ing])
            rules = by("rules")
            if rules:
                ids["rules"] = add("Rules & Scoring Processor", "stateful stream processing: enrichment, rule evaluation, score combination",
                                   "stream-processing", [r.id for r in rules])
            ids["service"] = add("Case & Workflow Service", "domain API for " + ", ".join(r.id for r in by("workflow", "documents")) or "workflow",
                                 "service", [r.id for r in by("workflow", "documents")])
        else:
            core = by("workflow", "documents", "integration")
            ids["service"] = add("Application Service (modular)",
                                 "domain modules and REST API for " + ", ".join(r.id for r in core),
                                 "service", [r.id for r in core])
        if by("documents"):
            ids["storage"] = add("Document Store (S3)", "encrypted object storage for uploaded documents with malware scanning",
                                 "storage", [r.id for r in by("documents")])
        if by("notification") or any(r.subcategory == "notification" for r in integ):
            ids["notify"] = add("Notification Worker", "asynchronous email/SMS/push dispatch with templates and retries",
                                "worker", [r.id for r in by("notification")] + [r.id for r in integ if r.subcategory == "notification"])
        if by("reporting"):
            ids["reporting"] = add("Reporting Read Model", "read-optimised projections for dashboards and exports (CQRS-lite)",
                                   "analytics", [r.id for r in by("reporting")])
        if by("search"):
            ids["search"] = add("Search Index & Query API", "indexing pipeline and permission-filtered query API",
                                "search", [r.id for r in by("search")])
        # one adapter per external system (anti-corruption layer)
        fn_int = by("integration", "ingestion")  # outbound calls and inbound feeds both belong to the system's adapter
        for r in integ:
            if r.subcategory == "ingestion" and event:
                continue
            sys_name = short(re.split(r"[(.]", r.text)[0], 40)
            related = [f.id for f in fn_int
                       if self.ctx.retriever.text_sim([f.text], r.text)[0] > 0.25]
            add(f"{sys_name} Adapter", f"anti-corruption layer for {sys_name}: auth, mapping, retries, contract tests",
                "integration", [r.id] + related)
        sec = [r.id for r in nfr if r.subcategory == "security"]
        ids["auth"] = add("Identity & Access (SSO/OAuth2 + RBAC)", "authentication via corporate SSO/OAuth2 and role-based authorisation",
                          "auth", sec + [r.id for r in fn if "sign in" in r.text.lower()], kind="enabler" if not sec else "feature")
        comp_refs = [r.id for r in nfr if r.subcategory == "compliance"]
        ids["db"] = add("PostgreSQL (RDS)", "system of record for domain state and the append-only audit log",
                        "database", comp_refs, kind="enabler" if not comp_refs else "feature")
        perf = [r.id for r in nfr if r.subcategory == "performance"]
        if perf:
            ids["cache"] = add("Redis Cache", "hot-read cache for latency-critical lookups", "cache", perf)
        ids["obs"] = add("Observability (OpenTelemetry + Grafana)", "traces, metrics, structured logs without PII, SLO alerts",
                         "observability", [], kind="enabler")

        # revision: map requirements the Critic found uncovered to the most similar component
        for rid in fix.items("uncovered_requirements"):
            r = b.req(rid)
            if not r or any(rid in c.brd_refs for c in comps) or r.category == "non_functional":
                continue
            sims = self.ctx.retriever.text_sim([f"{c.name} {c.responsibility}" for c in comps], r.text)
            order = sorted(range(len(comps)), key=lambda i: -sims[i])
            # the best match plus a close runner-up (e.g. inbound adapter + owning service)
            for i in [order[0]] + [j for j in order[1:2] if sims[j] >= 0.8 * sims[order[0]]]:
                comps[i].brd_refs = sorted(set(comps[i].brd_refs + [rid]))
                comps[i].responsibility += f"; also {rid}: {short(r.text, 60)}"

        # data flows
        cat_ids = {}
        for c in comps:
            cat_ids.setdefault(c.category, []).append(c.id)
        flows = []
        f = lambda s, t, d, m: flows.append(DataFlow(source=s, target=t, description=d, mode=m)) if s and t and s != t else None
        svc = ids["service"]
        f(ids.get("frontend"), svc, "HTTPS/JSON API calls", "sync")
        f(svc, ids["db"], "read/write domain state and audit entries", "sync")
        f(ids.get("frontend"), ids["auth"], "OIDC/OAuth2 login", "sync")
        if event:
            f(ids["ingest"], ids["broker"], "publish canonical events", "async")
            f(ids["broker"], ids.get("rules") or svc, "consume events", "async")
            f(ids.get("rules"), svc, "alerts / scored results", "async")
        for cid in cat_ids.get("integration", []):
            if cid != ids.get("ingest"):
                f(svc, cid, "outbound calls via adapter", "sync")
        f(svc, ids.get("storage"), "store/retrieve documents", "sync")
        f(svc, ids.get("notify"), "notification requests via queue", "async")
        f(ids["db"], ids.get("reporting"), "change-data projections", "async")
        f(svc, ids.get("search"), "index updates", "async")
        f(svc, ids.get("cache"), "cache-aside reads", "sync")

        # NFR mapping
        nfr_map, assumptions = [], []
        for r in nfr:
            mech, cats = NFR_MECHANISMS.get(r.subcategory, NFR_MECHANISMS["general"])
            cids = [i for cat in cats for i in cat_ids.get(cat, [])] or [svc]
            m = f"{r.id}: {mech}"
            if r.subcategory == "usability" and r.ambiguous_terms:
                assumptions.append(f"{r.id} is vague ({r.ambiguous_terms}); usability target deferred to PoC/product owner.")
            nfr_map.append(NFRMapping(nfr_id=r.id, mechanism=mech, component_ids=sorted(set(cids)),
                                      brd_refs=[r.id], citations=self.cite(m, hits)))
        if not nfr:
            for key, label in [("performance", "DEFAULT-LATENCY"), ("availability", "DEFAULT-AVAILABILITY"),
                               ("security", "DEFAULT-SECURITY")]:
                mech, cats = NFR_MECHANISMS[key]
                cids = [i for cat in cats for i in cat_ids.get(cat, [])] or [svc]
                nfr_map.append(NFRMapping(nfr_id=label, mechanism=mech, component_ids=sorted(set(cids)),
                                          citations=self.cite("default service level objectives " + mech, hits),
                                          assumption="BRD has no NFR section; org default SLOs applied (p95 < 300 ms, 99.5% for internal tools)."))
            assumptions.append("No NFRs in BRD: org default SLOs from engineering standards applied; confirm with business owner.")

        flags = [fl for fl in b.flags if fl.kind == "contradiction" and any(
            (rq := b.req(x)) and rq.subcategory == "deployment" for x in fl.brd_refs)]
        if flags:
            assumptions.append("Deployment target contradictory: conservative default = containerised, cloud-portable design; "
                               "serverless excluded until the EM resolves the conflict.")
        if b.constraints.deployment == "aws":
            assumptions.append("Deployed on the org AWS platform per BRD constraint.")

        n_fn = len(fn)
        cx = max(1, min(5, pat["complexity"] + (len(integ) >= 3) + (n_fn >= 10) - (n_fn <= 5)))
        pattern = PatternChoice(
            pattern_id=pat["id"], name=pat["name"],
            rationale=(f"Selected {pat['name']} ({', '.join(notes)}). Trade-offs: {pat['tradeoffs']}"),
            alternatives_considered=[f"{p['name']} (score {s:.2f}; {', '.join(n)})" for s, p, _, n in alts],
            brd_refs=[r.id for r in nfr if r.subcategory in ("performance", "scalability", "availability", "deployment")],
            citations=[phit.chunk_id] + [h.chunk_id for _, _, h, _ in alts[:1]])
        mer = ["flowchart LR"] + [f'  {c.id}["{c.name}"]' for c in comps] + \
              [f"  {fl.source} -->{'|async|' if fl.mode == 'async' else ''} {fl.target}" for fl in flows]
        arch = Architecture(pattern=pattern, components=comps, data_flows=flows, nfr_mapping=nfr_map,
                            complexity_score=cx, mermaid="\n".join(mer), assumptions=assumptions,
                            flags=[fl for fl in b.flags if fl.kind in ("ambiguity", "contradiction", "missing_section")])
        # revision: targeted retrieval for uncited claims
        for iid in fix.items("uncited_claims"):
            for c in arch.components:
                if c.id == iid and not c.citations:
                    c.citations = self.targeted_cite(f"{c.name} {c.responsibility}", span)
            for m in arch.nfr_mapping:
                if f"NFRMAP-{m.nfr_id}" == iid and not m.citations:
                    m.citations = self.targeted_cite(m.mechanism, span)
        return arch

    def summarize(self, out):
        return {"pattern": out.pattern.pattern_id, "components": len(out.components),
                "complexity": out.complexity_score, "nfr_mapped": len(out.nfr_mapping)}
