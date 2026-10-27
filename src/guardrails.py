"""Guardrails: input validation, PII/secret redaction, prompt-injection
quarantine, schema compliance at hand-offs, hallucination detection and
scope-creep prevention.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Type

from pydantic import BaseModel, ValidationError

from .config import ALLOWED_EXTENSIONS, MAX_FILE_BYTES, MIN_BRD_CHARS
from .contracts import Flag, ParsedBRD


class InputRejected(ValueError):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class ContractViolation(ValueError):
    def __init__(self, producer: str, consumer: str, errors: str):
        super().__init__(f"{producer} -> {consumer}: {errors}")
        self.producer, self.consumer, self.errors = producer, consumer, errors


# ------------------------------------------------------------------ input validation
def validate_file(path: Path) -> None:
    reasons = []
    if not path.exists():
        raise InputRejected([f"file not found: {path.name}"])
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        reasons.append(f"unsupported file type '{path.suffix}' (allowed: {sorted(ALLOWED_EXTENSIONS)})")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        reasons.append(f"file too large ({size} bytes > {MAX_FILE_BYTES})")
    if size == 0:
        reasons.append("file is empty")
    if reasons:
        raise InputRejected(reasons)


def validate_text(text: str) -> None:
    reasons = []
    if len(text.strip()) < MIN_BRD_CHARS:
        reasons.append(f"document too short ({len(text.strip())} chars < {MIN_BRD_CHARS}); not a BRD")
    if not re.search(r"^#{1,3}\s+\S", text, re.M):
        reasons.append("no section headings found; BRD must be structured into sections")
    if not re.search(r"requirement|feature|user stor", text, re.I):
        reasons.append("no requirements section found")
    if reasons:
        raise InputRejected(reasons)


def validate_parsed(brd: ParsedBRD) -> list[Flag]:
    """Structural checks after parsing; hard failures raise, soft ones return flags."""
    if not any(r.category == "functional" for r in brd.requirements):
        raise InputRejected(["no functional requirements could be extracted"])
    return []


# ------------------------------------------------------------------ PII / secrets
PII_PATTERNS = {
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "PHONE": re.compile(r"\+?\d{1,3}[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{4}\b"),
    "API_KEY": re.compile(r"\b(?:sk|pk|rk)[-_](?:live|test)?[-_]?[A-Za-z0-9]{16,}\b|\bAKIA[0-9A-Z]{16}\b"),
    "CARD_NUMBER": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
}


def redact(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for label, pat in PII_PATTERNS.items():
        text, n = pat.subn(f"[REDACTED_{label}]", text)
        if n:
            counts[label] = n
    return text, counts


# ------------------------------------------------------------------ prompt injection
INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior|above) instructions",
    r"disregard (the )?(system|previous) (prompt|instructions)",
    r"reveal (your )?(system prompt|instructions)",
    r"you are now",
    r"act as (an? )?(unrestricted|jailbroken)",
    r"add an? .* (module|feature) to the (engineering )?plan",
]


_GENERIC = {"previous", "instructions", "engineering", "requirements", "architecture", "ignore", "reveal", "system",
            "prompt", "disregard", "unrestricted", "jailbroken", "schedule", "project", "module", "feature"}


def quarantine_injections(text: str) -> tuple[str, list[str], list[str]]:
    """Remove lines containing instruction-like content aimed at the agents.
    Returns (clean_text, quarantined_refs, watch_terms). The original lines are
    never forwarded to any agent or log. `watch_terms` are distinctive words from
    the injected line; if any later appears in an artifact it is flagged as
    scope creep (defence in depth against partial injections)."""
    kept, hits, terms = [], [], []
    for line in text.splitlines():
        if any(re.search(p, line, re.I) for p in INJECTION_PATTERNS):
            m = re.search(r"((?:FR|NFR|INT)-\d+)", line)
            hits.append(m.group(1) if m else f"line:{len(kept) + len(hits) + 1}")
            terms += [w for w in re.findall(r"[a-z]{7,}", line.lower()) if w not in _GENERIC]
            continue
        kept.append(line)
    return "\n".join(kept), hits, sorted(set(terms))


# ------------------------------------------------------------------ schema compliance
def validate_handoff(model_cls: Type[BaseModel], data: Any, producer: str, consumer: str) -> BaseModel:
    """Every consumer re-validates its input. Accepts a model instance or a dict."""
    try:
        payload = data.model_dump() if isinstance(data, BaseModel) else data
        return model_cls.model_validate(payload)
    except ValidationError as e:
        raise ContractViolation(producer, consumer, str(e)[:1500]) from e


# ------------------------------------------------------------------ hallucination & scope creep
def iter_claims(artifact_name: str, art: BaseModel) -> list[tuple[str, str, list[str], list[str], str]]:
    """(item_id, text, brd_refs, citations, kind) for every grounded claim in an artifact."""
    return [(i, t, o.brd_refs, o.citations, k) for o, i, t, k in iter_claim_objects(artifact_name, art)]


def iter_claim_objects(artifact_name: str, art: BaseModel) -> list[tuple[Any, str, str, str]]:
    """(object, item_id, text, kind) for every grounded claim; objects are mutable for re-grounding."""
    d = art
    out = []
    if artifact_name == "plan_generator":
        for p in d.phases:
            out.append((p, p.id, f"{p.name}: {p.objective}. " + "; ".join(p.deliverables), "phase"))
        for m in d.milestones:
            out.append((m, m.id, f"{m.name}: {m.acceptance}", "milestone"))
        for r in d.risks:
            out.append((r, r.id, f"{r.description}. Mitigation: {r.mitigation}", "risk"))
        for t in d.team:
            out.append((t, f"ROLE-{t.role}", f"{t.count} x {t.role}: {t.justification}", "team"))
    elif artifact_name == "schedule_estimator":
        for pe in d.phase_estimates:
            out.append((pe, f"EST-{pe.phase_id}", pe.basis, "estimate"))
    elif artifact_name == "solution_architect":
        p = d.pattern
        out.append((p, "PATTERN", f"{p.name}: {p.rationale}", "pattern"))
        for c in d.components:
            out.append((c, c.id, f"{c.name}: {c.responsibility}", c.kind))
        for m in d.nfr_mapping:
            out.append((m, f"NFRMAP-{m.nfr_id}", m.mechanism, "nfr"))
    elif artifact_name == "poc_planner":
        for s in d.success_criteria:
            out.append((s, s.id, f"{s.metric} {s.target} measured by {s.measurement}", "criterion"))
    elif artifact_name == "tech_stack_recommender":
        for o in d.options:
            out.append((o, o.id, f"{o.name}: " + "; ".join(o.pros + o.cons), "option"))
    return out


def check_grounding(artifact_name: str, art: BaseModel, brd: ParsedBRD, retrieved: set[str],
                    out_of_scope_terms: list[str], quarantined_terms: list[str], retriever=None) -> list[dict]:
    """Returns guardrail findings:
    * fabricated_citation  – cites a chunk the agent never retrieved (hallucinated source)
    * unknown_brd_ref      – references a requirement ID not in the BRD (invented requirement)
    * scope_creep          – feature item with no BRD reference, or text matching an out-of-scope /
                             quarantined (injected) term
    * weak_support         – cited chunks barely relate to the claim (possible hallucination)
    """
    findings = []
    ids = brd.req_ids
    for item_id, text, refs, cites, kind in iter_claims(artifact_name, art):
        bad_c = [c for c in cites if c not in retrieved]
        if bad_c:
            findings.append({"type": "fabricated_citation", "item": item_id, "detail": bad_c})
        bad_r = [r for r in refs if r not in ids]
        if bad_r:
            findings.append({"type": "unknown_brd_ref", "item": item_id, "detail": bad_r})
        if kind in ("feature",) and not refs:
            findings.append({"type": "scope_creep", "item": item_id, "detail": "feature component without BRD requirement"})
        if kind == "enabler" and not refs and not cites:
            findings.append({"type": "scope_creep", "item": item_id, "detail": "enabler without org-standard justification"})
        low = text.lower()
        scope_bearing = kind in ("phase", "feature", "enabler", "criterion", "milestone", "option")
        for term in (out_of_scope_terms + quarantined_terms) if scope_bearing else []:
            if term and term in low:
                findings.append({"type": "scope_creep", "item": item_id, "detail": f"mentions out-of-scope/injected term '{term}'"})
        if retriever is not None and cites and not bad_c and retriever.support(text, cites) < 0.03:
            findings.append({"type": "weak_support", "item": item_id, "detail": cites})
    return findings


def out_of_scope_terms(brd: ParsedBRD) -> list[str]:
    terms = []
    for o in brd.out_of_scope:
        o = re.sub(r"\(.*?\)", "", o).lower().strip(" .")
        if 3 < len(o) < 40:
            terms.append(o)
    return terms
