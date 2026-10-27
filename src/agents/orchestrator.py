"""Agent 1 — Orchestrator (hub of the hub-and-spoke pattern).

Responsibilities: input guardrails, BRD parsing (tool), routing requirements to
specialists, state management, retries/fallbacks, the Critic revision loop
(max 2 cycles with dependency cascade), escalations, the HITL gate and exports.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..config import AGENT_MAX_RETRIES, MAX_REVISIONS, OUTPUT_DIR, PROFILES, RunOptions
from ..contracts import (AGENT_OUTPUT_MODELS, CriticIssue, CriticReport, Flag, ParsedBRD, RoutingDecision)
from ..guardrails import (ContractViolation, InputRejected, quarantine_injections, redact, validate_file,
                          validate_handoff, validate_parsed, validate_text)
from ..llm import ALLOW_EXTERNAL_ENV, LLMClient, gate_tracing
from ..parsing.brd_parser import ParseError, parse_brd, read_text
from ..rag.retriever import Retriever, load_or_build
from ..run_logger import RunLogger, sha
from ..tools import exporters
from ..tools.jira_mock import MockJiraClient
from ..tools.registry import call_tool
from .base import BaseAgent, FixContext, RunContext
from .critic import ARTIFACTS, Critic
from .plan_generator import PlanGenerator
from .poc_planner import PoCPlanner
from .schedule_estimator import ScheduleEstimator
from .solution_architect import SolutionArchitect
from .tech_stack import TechStackRecommender

AGENT_CLASSES = {"plan_generator": PlanGenerator, "schedule_estimator": ScheduleEstimator,
                 "solution_architect": SolutionArchitect, "poc_planner": PoCPlanner,
                 "tech_stack_recommender": TechStackRecommender}
WORKFLOWS = {"planning": ["plan_generator", "schedule_estimator"],
             "design": ["solution_architect", "poc_planner", "tech_stack_recommender"]}
# downstream dependents re-run when an upstream artifact is revised
DEPENDENTS = {"plan_generator": ["schedule_estimator", "poc_planner"],
              "solution_architect": ["poc_planner", "tech_stack_recommender"],
              "schedule_estimator": ["poc_planner", "tech_stack_recommender"],
              "poc_planner": [], "tech_stack_recommender": []}
REVISION_ORDER = ["plan_generator", "solution_architect", "schedule_estimator", "poc_planner", "tech_stack_recommender"]


@dataclass
class PipelineState:
    run_id: str
    run_dir: Path
    source_name: str
    status: str = "started"
    brd: Optional[ParsedBRD] = None
    routing: Optional[RoutingDecision] = None
    artifacts: dict = field(default_factory=dict)
    revisions: list = field(default_factory=list)       # [{"round", "agent", "artifact"}]
    critic_reports: list[CriticReport] = field(default_factory=list)
    escalations: list[Flag] = field(default_factory=list)
    fix_memory: dict = field(default_factory=dict)      # agent -> accumulated CriticIssues
    guardrail_events: list = field(default_factory=list)
    hitl: dict = field(default_factory=dict)
    exports: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


class OrchestratorAgent(BaseAgent):
    """The routing decision itself is an agent output with its own contract."""
    name = "orchestrator"
    output_model = RoutingDecision

    def retrieve(self, span, fix):
        return []

    def heuristic(self, hits, upstream, fix, span):
        b = self.brd
        R = b.requirements
        ids = lambda pred: [r.id for r in R if pred(r)]
        n = sum(r.category in ("functional", "non_functional") for r in R)
        n_int = sum(r.category == "integration" for r in R)
        cx = max(1, min(5, 1 + (n > 8) + (n > 15) + (n_int >= 3)))  # quick size-based triage (refined by the Architect)
        routes = {
            "plan_generator": ids(lambda r: r.category in ("functional", "integration", "constraint")),
            "schedule_estimator": ids(lambda r: r.category == "constraint"),
            "solution_architect": ids(lambda r: r.category in ("functional", "non_functional", "integration")),
            "poc_planner": ids(lambda r: r.category == "integration"
                               or (r.category == "non_functional" and r.subcategory in ("performance", "availability", "scalability", "usability"))
                               or (r.category == "functional" and r.ambiguous_terms and r.priority != "could")),
            "tech_stack_recommender": ids(lambda r: r.category in ("non_functional", "integration")),
        }
        esc = [f.id for f in b.flags if f.kind in ("contradiction", "feasibility", "injection")
               or (f.kind == "missing_section" and f.severity == "high")]
        return RoutingDecision(brd_id=b.brd_id, complexity_estimate=cx, routes=routes,
                               workflows=["planning", "design", "validation"], escalations=esc,
                               rationale=(f"{n} functional/NFR requirements and {n_int} integrations -> initial complexity {cx}. "
                                          "Planning group gets functional/integration/constraint requirements; Design group gets "
                                          "functional/NFR/integration; PoC gets integrations, critical NFRs and ambiguous Musts."))

    def run(self, revision=0, fix=None):
        with self.ctx.logger.agent_span(self.name, "route", {"brd": self.brd.content_hash}, revision) as span:
            out = self.ctx.llm.generate(self.name, RoutingDecision, self.system_prompt(),
                                        self.brd_block(), heuristic=lambda: self.heuristic([], {}, None, span), span=span)
            # deterministic safety net: every requirement must be routed somewhere
            routed = {r for v in out.routes.values() for r in v}
            missing = [r.id for r in self.brd.requirements if r.id not in routed]
            if missing:
                out.routes.setdefault("plan_generator", []).extend(missing)
                span["guardrail_triggers"].append(f"unrouted_requirements:{missing}")
            span["decisions"] = [{"decision": "routing", "complexity": out.complexity_estimate,
                                  "routes": {k: len(v) for k, v in out.routes.items()}}]
            span["output_obj"] = out.model_dump()
        return out


class Pipeline:
    engine = "classic"

    def __init__(self, options: Optional[RunOptions] = None, llm: Optional[LLMClient] = None, output_dir: Path = OUTPUT_DIR):
        self.opt = options or RunOptions()
        self.llm = llm or LLMClient()
        self.output_dir = output_dir
        self.store = load_or_build()

    # ------------------------------------------------------------------ helpers
    def _say(self, msg: str):
        if not self.opt.extra.get("quiet"):
            print(msg, file=sys.stderr)

    def _guard(self, state, stage, **kw):
        state.guardrail_events.append({"stage": stage, **kw})
        self.logger.log("guardrail", stage=stage, **kw)

    def run_agent(self, state: PipelineState, ctx: RunContext, name: str, revision: int) -> bool:
        fix = FixContext(state.fix_memory.get(name, []))
        last = None
        for attempt in range(1, AGENT_MAX_RETRIES + 2):
            try:
                agent = AGENT_CLASSES[name](ctx)
                out = agent.run(revision=revision, fix=fix)
                # schema compliance at the hand-off: consumer-side validation
                out = validate_handoff(AGENT_OUTPUT_MODELS[name], out, name, "critic")
                if not ctx.retriever.retrieved(name):
                    out.assumptions.append("DISCLAIMER: no knowledge-base context was retrieved; output is ungrounded.")
                    self._guard(state, "rag", type="no_rag_hits", agent=name)
                ctx.artifacts[name] = out
                state.revisions.append({"round": revision, "agent": name, "artifact": out.model_dump()})
                return True
            except ContractViolation as cv:
                last = cv
                self.logger.log("contract_violation", producer=cv.producer, consumer=cv.consumer, attempt=attempt,
                                errors=cv.errors[:400])
            except Exception as exc:  # agent crash -> retry
                last = exc
                self.logger.log("agent_error", agent=name, attempt=attempt, error=f"{type(exc).__name__}: {str(exc)[:300]}")
        state.errors.append(f"{name}: {last}")
        return False

    # ------------------------------------------------------------------ main entry
    def run(self, brd_path: Path) -> PipelineState:
        """Classic sequential driver. `src.graph.GraphPipeline` runs the same stages as a LangGraph StateGraph."""
        state, ctx = self.start(brd_path)
        if not self.ingest(state, ctx):
            return state
        self.route(state, ctx)

        # ---------------- Workflow A (planning) and B (design)
        for wf in ("planning", "design"):
            for name in WORKFLOWS[wf]:
                if not self.run_stage_agent(state, ctx, name, 0):
                    return state
                self._say(f"  ✓ {wf}/{name}")

        # ---------------- Workflow C (validation): Critic loop with max 2 revisions
        critic = Critic(ctx)
        for rnd in range(MAX_REVISIONS + 1):
            report = self.critic_round(state, critic, rnd)
            if report.decision != "revise":
                break
            for name in self.revision_targets(state, report):
                if not self.run_stage_agent(state, ctx, name, rnd + 1):
                    return state

        jira = self.escalate(state, ctx)
        self.write_draft(state)
        state.hitl = self.hitl_gate(state)
        self.complete(state, jira)
        return state

    # ------------------------------------------------------------------ stages (shared with src.graph)
    def start(self, brd_path: Path) -> tuple[PipelineState, RunContext]:
        brd_path = Path(brd_path)
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + sha(brd_path.name + str(datetime.now()), 6)
        if self.opt.run_label:
            run_id = f"{self.opt.run_label}-{run_id}"
        run_dir = self.output_dir / run_id
        self.logger = RunLogger(run_dir, run_id)
        self.brd_path = brd_path
        state = PipelineState(run_id=run_id, run_dir=run_dir, source_name=brd_path.name)
        profile = PROFILES[self.opt.profile]
        retriever = Retriever(self.store, profile, self.logger)
        ctx = RunContext(llm=self.llm, retriever=retriever, logger=self.logger)
        tracing = gate_tracing()
        if tracing == "blocked":
            self._say(f"  ! LangSmith tracing disabled: it would record BRD text; set {ALLOW_EXTERNAL_ENV}=1 to allow")
        self.logger.log("run_start", provider=self.llm.provider, backend=self.llm.backend, engine=self.engine, tracing=tracing,
                        kb_version=self.store.version,
                        profile=profile.name, file_ext=brd_path.suffix,
                        file_hash=sha(brd_path.read_bytes()) if brd_path.exists() else None)
        self._say(f"▶ run {run_id} | engine={self.engine} | provider={self.llm.provider} | profile={profile.name}")
        return state, ctx

    def ingest(self, state: PipelineState, ctx: RunContext) -> bool:
        """Layer 1: input guardrails + parsing tool. Returns False (run finished as rejected) on bad input."""
        brd_path = self.brd_path
        try:
            validate_file(brd_path)
            raw = call_tool(self.logger, "read_document", read_text, brd_path)
            validate_text(raw)
            clean, pii = redact(raw)
            if pii:
                self._guard(state, "input", type="pii_redacted", counts=pii)
            clean, injected, terms = quarantine_injections(clean)
            ctx.quarantined_terms = terms
            if injected:
                self._guard(state, "input", type="prompt_injection_quarantined", refs=injected, n_terms=len(terms))
            brd = call_tool(self.logger, "brd_parser", parse_brd, brd_path, clean)
            validate_parsed(brd)
        except (InputRejected, ParseError, ValueError) as e:
            reasons = getattr(e, "reasons", [str(e)])
            self._guard(state, "input", type="input_rejected", reasons=reasons)
            state.status = "rejected"
            state.errors = reasons
            self._say("✖ input rejected: " + "; ".join(reasons))
            self._finish(state)
            return False
        if injected:
            brd.flags.append(Flag(id="INJ-1", kind="injection", severity="high", brd_refs=injected,
                                  message=f"Instruction-like content in {', '.join(injected)} was quarantined and not sent to any agent.",
                                  resolution="Requirement removed from scope; EM to confirm with the BRD author."))
        if pii:
            brd.flags.append(Flag(id="PII-1", kind="pii", severity="medium",
                                  message=f"Redacted before processing: {pii}.", resolution="Redacted; never logged."))
        ctx.brd = state.brd = brd
        self.logger.log("brd_parsed", brd_id=brd.brd_id, content_hash=brd.content_hash, n_requirements=len(brd.requirements),
                        sections=brd.sections_found, missing=brd.missing_sections,
                        flags={k: sum(f.kind == k for f in brd.flags) for k in {f.kind for f in brd.flags}},
                        classification=brd.classification)
        self._say(f"  parsed '{brd.title}': {len(brd.requirements)} requirements, {len(brd.flags)} flags")
        return True

    def route(self, state: PipelineState, ctx: RunContext) -> RoutingDecision:
        """Agent 1 routing decision."""
        ctx.routing = state.routing = OrchestratorAgent(ctx).run()
        state.escalations = [f for f in state.brd.flags if f.id in ctx.routing.escalations]
        return ctx.routing

    def run_stage_agent(self, state: PipelineState, ctx: RunContext, name: str, revision: int) -> bool:
        """run_agent + terminate the run (status failed:<agent>) when retries are exhausted."""
        if self.run_agent(state, ctx, name, revision):
            return True
        state.status = f"failed:{name}"
        self._say(f"✖ {name} failed after retries: {state.errors[-1]}")
        self._finish(state)
        return False

    def critic_round(self, state: PipelineState, critic: Critic, rnd: int) -> CriticReport:
        report = critic.review(rnd)
        state.critic_reports.append(report)
        self._say(f"  Critic round {rnd}: {report.overall_badge} {report.overall_score} | "
                  + " ".join(f"{s.artifact.split('_')[0]}={s.badge[0]}{s.overall}" for s in report.artifact_scores)
                  + f" | {len(report.issues)} issues -> {report.decision}")
        return report

    def revision_targets(self, state: PipelineState, report: CriticReport) -> list[str]:
        """Record Critic feedback per agent; return the agents to re-run (flagged + dependents) in dependency order."""
        for i in report.issues:
            state.fix_memory.setdefault(i.target_agent, []).append(i)
        to_run = set(report.agents_to_revise)
        for a in list(to_run):
            to_run |= set(DEPENDENTS.get(a, []))
        return [name for name in REVISION_ORDER if name in to_run]

    def escalate(self, state: PipelineState, ctx: RunContext) -> MockJiraClient:
        """Collect feasibility escalations and open the escalation ticket (autonomous Agent -> Action)."""
        state.artifacts = ctx.artifacts
        for f in state.artifacts["schedule_estimator"].flags:
            if f.kind == "feasibility" and f.id not in [e.id for e in state.escalations]:
                state.escalations.append(f)
        jira = MockJiraClient(state.run_dir)
        if state.escalations:
            t = call_tool(self.logger, "jira_create_issue", exporters.create_escalation, state, jira)
            state.exports["escalation_ticket"] = t["key"]
            self._say(f"  ⚑ escalation ticket {t['key']} opened for {len(state.escalations)} BRD issue(s)")
        return jira

    def write_draft(self, state: PipelineState):
        """The EM reviews this saved draft pack at the HITL gate."""
        state.run_dir.mkdir(parents=True, exist_ok=True)
        (state.run_dir / "parsed_brd.json").write_text(state.brd.model_dump_json(indent=2))
        (state.run_dir / "engineering_pack.md").write_text(
            "> **DRAFT — pending EM review at the HITL gate.**\n\n" + exporters.to_markdown(state, self.store), encoding="utf-8")

    def complete(self, state: PipelineState, jira: MockJiraClient):
        """Exports (decision depends on HITL outcome) and persistence."""
        if self.opt.export:
            self.export(state, jira)
        state.status = "completed"
        self._finish(state)

    # ------------------------------------------------------------------ HITL
    def hitl_gate(self, state: PipelineState) -> dict:
        d = self.hitl_auto(state) if self.opt.auto_approve else self.hitl_prompt(self.hitl_payload(state))
        self.logger.log("hitl", **d)
        return d

    @staticmethod
    def hitl_auto(state: PipelineState) -> dict:
        rep = state.critic_reports[-1]
        if rep.overall_badge == "RED":
            return {"decision": "rejected", "by": "auto", "reason": "RED badge requires a human decision"}
        return {"decision": "approved", "by": "auto (demo mode)", "reason": f"{rep.overall_badge} badge"}

    @staticmethod
    def hitl_payload(state: PipelineState) -> dict:
        """JSON-safe summary the EM decides on (also the LangGraph interrupt payload)."""
        rep = state.critic_reports[-1]
        return {"title": state.brd.title, "badge": rep.overall_badge, "score": rep.overall_score,
                "revision_round": rep.revision_round,
                "artifacts": [{"artifact": s.artifact, "badge": s.badge, "overall": s.overall,
                               "below": list(s.below_threshold)} for s in rep.artifact_scores],
                "escalations": [{"id": f.id, "message": f.message} for f in state.escalations],
                "draft": str(state.run_dir / "engineering_pack.md")}

    @staticmethod
    def hitl_prompt(payload: dict) -> dict:
        print("\n================ HITL REVIEW ================")
        print(f"BRD: {payload['title']} | badge {payload['badge']} ({payload['score']}) after {payload['revision_round']} revision(s)")
        for s in payload["artifacts"]:
            print(f"  {s['artifact']:24s} {s['badge']:5s} overall={s['overall']} below={s['below']}")
        for f in payload["escalations"]:
            print(f"  ⚠ {f['id']}: {f['message']}")
        print(f"Draft pack: {payload['draft']}")
        ans = input("Approve? [a]pprove / [r]eject / [o]verride-approve RED: ").strip().lower()[:1]
        rating = input("Your EM rating of the pack 1-5 (blank to skip): ").strip()
        note = input("Notes for the record (optional): ").strip()
        return {"decision": {"a": "approved", "o": "approved_with_override"}.get(ans, "rejected"), "by": "EM (interactive)",
                "em_rating": int(rating) if rating.isdigit() else None, "note_hash": sha(note) if note else None}

    # ------------------------------------------------------------------ exports (Agent -> Decision + Tool)
    def export(self, state: PipelineState, jira: MockJiraClient):
        approved = state.hitl.get("decision", "").startswith("approved")
        plan = ["markdown", "html"] + (["pdf", "jira"] if approved else [])
        self.logger.log("decision", agent="orchestrator", decision="export_targets", value=plan,
                        reason="approved -> full export" if approved else "not approved -> draft only, no Jira push")
        md = call_tool(self.logger, "export_markdown", exporters.to_markdown, state, self.store)
        if not approved:
            md = "> **DRAFT — not approved at the HITL gate.**\n\n" + md
        p = state.run_dir / "engineering_pack.md"
        p.write_text(md, encoding="utf-8")
        state.exports["markdown"] = p.name
        if "pdf" in plan:
            call_tool(self.logger, "export_pdf", exporters.to_pdf, md, state.run_dir / "engineering_pack.pdf")
            state.exports["pdf"] = "engineering_pack.pdf"
        if "jira" in plan:
            created = call_tool(self.logger, "export_jira", exporters.to_jira, state, jira)
            (state.run_dir / "jira_export.json").write_text(json.dumps(created, indent=2))
            state.exports["jira"] = {"epics": len(created["epics"]), "stories": len(created["stories"])}

    # ------------------------------------------------------------------ persistence
    def _finish(self, state: PipelineState):
        from ..report import write_html_report
        d = state.run_dir
        d.mkdir(parents=True, exist_ok=True)
        if state.brd:
            (d / "parsed_brd.json").write_text(state.brd.model_dump_json(indent=2))
        if state.routing:
            (d / "routing.json").write_text(state.routing.model_dump_json(indent=2))
        art_dir = d / "artifacts"
        art_dir.mkdir(exist_ok=True)
        for r in state.revisions:
            (art_dir / f"{r['agent']}.rev{r['round']}.json").write_text(json.dumps(r["artifact"], indent=2, default=str))
        for i, rep in enumerate(state.critic_reports):
            (art_dir / f"critic.round{i}.json").write_text(rep.model_dump_json(indent=2))
        summary = self.summary(state)
        (d / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
        self.logger.log("run_end", status=state.status, metrics=summary.get("metrics"))
        if state.critic_reports:
            write_html_report(state, summary, d / "dashboard.html")
            state.exports.setdefault("html", "dashboard.html")
            summary["exports"] = state.exports
            (d / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
        self._say(f"■ {state.status} → {d}")

    def summary(self, state: PipelineState) -> dict:
        reps = state.critic_reports
        hist = [{"round": r.revision_round, "overall": r.overall_score, "badge": r.overall_badge, "issues": len(r.issues),
                 "artifacts": {s.artifact: {"overall": s.overall, "badge": s.badge, "groundedness_ratio": s.groundedness_ratio,
                                            "coverage_ratio": s.coverage_ratio, "contradictions": s.contradictions,
                                            "actionability": s.actionability} for s in r.artifact_scores},
                 "cross_agent_checks": r.cross_agent_checks} for r in reps]
        log = self.logger.summary()
        return {
            "run_id": state.run_id, "source": state.source_name, "status": state.status, "provider": self.llm.provider,
            "profile": self.opt.profile, "brd_id": state.brd.brd_id if state.brd else None,
            "title": state.brd.title if state.brd else None, "errors": state.errors,
            "guardrail_events": state.guardrail_events,
            "escalations": [f.model_dump() for f in state.escalations],
            "routing_complexity": state.routing.complexity_estimate if state.routing else None,
            "revision_rounds": reps[-1].revision_round if reps else 0,
            "final_badge": reps[-1].overall_badge if reps else ("RED" if state.status != "completed" else None),
            "final_score": reps[-1].overall_score if reps else None,
            "critic_history": hist, "hitl": state.hitl, "exports": state.exports,
            "metrics": log,
        }
