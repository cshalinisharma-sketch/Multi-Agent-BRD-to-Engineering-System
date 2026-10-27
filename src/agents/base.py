"""Agent base class and shared run context."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Type

from pydantic import BaseModel

from ..contracts import CriticIssue, ParsedBRD
from ..llm import LLMClient
from ..prompts import PROMPTS, SHARED_RULES
from ..rag.retriever import Retriever
from ..rag.store import Hit
from ..run_logger import RunLogger


@dataclass
class RunContext:
    llm: LLMClient
    retriever: Retriever
    logger: RunLogger
    brd: Optional[ParsedBRD] = None
    artifacts: dict[str, Any] = field(default_factory=dict)       # agent -> latest validated output
    history: dict[str, list] = field(default_factory=dict)        # agent -> [output per revision]
    routing: Any = None
    quarantined_terms: list[str] = field(default_factory=list)


@dataclass
class FixContext:
    """Structured view of Critic feedback for one agent (also rendered into the LLM prompt)."""
    issues: list[CriticIssue] = field(default_factory=list)

    def codes(self) -> set[str]:
        return {i.code for i in self.issues}

    def items(self, code: str) -> list[str]:
        out: list[str] = []
        for i in self.issues:
            if i.code == code:
                out += i.target_items
        return out

    def __bool__(self):
        return bool(self.issues)


def short(text: str, n: int = 90) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


class BaseAgent:
    name: str = "base"
    output_model: Type[BaseModel]

    def __init__(self, ctx: RunContext):
        self.ctx = ctx

    # --------------------------------------------------------------- helpers
    @property
    def brd(self) -> ParsedBRD:
        return self.ctx.brd

    def routed(self) -> list[str]:
        return list(self.ctx.routing.routes.get(self.name, [])) if self.ctx.routing else []

    def search(self, query: str, span: dict, **kw) -> list[Hit]:
        return self.ctx.retriever.search(self.name, query, span=span, **kw)

    def cite(self, text: str, hits: list[Hit], max_n: int = 2) -> list[str]:
        return self.ctx.retriever.cite(self.name, text, hits, max_n)

    def targeted_cite(self, text: str, span: dict, max_n: int = 2) -> list[str]:
        """Revision behaviour for uncited claims: retrieve with the claim itself as the query."""
        hits = self.search(text, span, top_k=3)
        return self.cite(text, hits, max_n)

    def brd_block(self) -> str:
        reqs = [{"id": r.id, "priority": r.priority, "category": r.category, "text": r.text} for r in self.brd.requirements]
        return f"<brd>\nTITLE: {self.brd.title}\nDOMAIN: {self.brd.domain}\nOBJECTIVES: {self.brd.objectives}\n" \
               f"OUT OF SCOPE: {self.brd.out_of_scope}\nCONSTRAINTS: {self.brd.constraints.model_dump()}\n" \
               f"BRD REQUIREMENTS: {json.dumps(reqs)}\n</brd>"

    @staticmethod
    def context_block(hits: list[Hit]) -> str:
        return "RETRIEVED CONTEXT:\n" + "\n".join(f"[{h.chunk_id}] {h.text[:900]}" for h in hits)

    def user_prompt(self, hits: list[Hit], upstream: dict, fix: FixContext, previous: Optional[BaseModel]) -> str:
        parts = [self.brd_block(), f"REQUIREMENTS ROUTED TO YOU: {self.routed()}", self.context_block(hits)]
        for k, v in upstream.items():
            parts.append(f"UPSTREAM {k.upper()}:\n{v.model_dump_json() if isinstance(v, BaseModel) else json.dumps(v)}")
        if previous is not None and fix:
            parts.append("YOUR PREVIOUS OUTPUT:\n" + previous.model_dump_json())
            parts.append("CRITIC FEEDBACK (fix every item):\n" + "\n".join(
                f"- [{i.code}/{i.dimension}] {i.message} Items: {i.target_items}. Fix: {i.suggested_fix}" for i in fix.issues))
        return "\n\n".join(parts)

    def system_prompt(self) -> str:
        return PROMPTS[self.name] + "\n" + SHARED_RULES

    # --------------------------------------------------------------- template method
    def run(self, revision: int = 0, fix: Optional[FixContext] = None) -> BaseModel:
        fix = fix or FixContext()
        previous = self.ctx.artifacts.get(self.name)
        upstream = self.upstream()
        with self.ctx.logger.agent_span(self.name, "revise" if revision else "generate",
                                        {"brd": self.brd.content_hash, "routed": self.routed(),
                                         "fix": [i.code for i in fix.issues]}, revision) as span:
            hits = self.retrieve(span, fix)
            out = self.ctx.llm.generate(
                self.name, self.output_model, self.system_prompt(),
                self.user_prompt(hits, upstream, fix, previous),
                heuristic=lambda: self.heuristic(hits, upstream, fix, span), span=span)
            self.reground(out, fix, span)
            span["output_obj"] = out.model_dump()
            span["output_summary"] = self.summarize(out)
            span["revision_fixes"] = sorted(fix.codes())
        return out

    def reground(self, out: BaseModel, fix: FixContext, span: dict) -> None:
        """Revision step for groundedness feedback (works for LLM and offline output alike):
        claims flagged as uncited or invalidly grounded get a targeted retrieval with the claim
        text as query; if nothing relevant is found the claim is marked as an assumption."""
        from ..guardrails import iter_claim_objects
        # scope_creep on an enabler = missing org-standard justification -> look for one
        targets = set(fix.items("uncited_claims")) | set(fix.items("invalid_grounding")) | set(fix.items("scope_creep"))
        if not targets:
            return
        for obj, item_id, text, _kind in iter_claim_objects(self.name, out):
            if item_id in targets:
                obj.citations = self.targeted_cite(text, span)
                if not obj.citations:
                    obj.assumption = obj.assumption or "No supporting knowledge-base source found; expert judgement pending EM review."

    # --------------------------------------------------------------- to implement
    def upstream(self) -> dict:
        return {}

    def retrieve(self, span: dict, fix: FixContext) -> list[Hit]:
        raise NotImplementedError

    def heuristic(self, hits: list[Hit], upstream: dict, fix: FixContext, span: dict) -> BaseModel:
        raise NotImplementedError

    def summarize(self, out: BaseModel) -> dict:
        return {}
