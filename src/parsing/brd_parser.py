"""BRD parser tool (Layer 1: ingestion & parsing).

Reads .md/.txt/.docx, splits into canonical sections, extracts requirements with
IDs and priorities, classifies them, extracts constraints, and flags
ambiguities, contradictions and missing sections. Deterministic on purpose: the
parser is the system's source of truth for scope, so it must be reproducible.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..contracts import Constraints, Flag, ParsedBRD, Requirement
from ..run_logger import sha

SECTION_SYNONYMS = {
    "overview": ["overview", "background", "introduction", "summary", "problem statement", "context"],
    "objectives": ["business objectives", "objectives", "goals", "business goals"],
    "scope": ["scope"],
    "in_scope": ["in scope"],
    "out_of_scope": ["out of scope", "non-goals", "exclusions"],
    "functional_requirements": ["functional requirements", "features", "user stories", "requirements"],
    "non_functional_requirements": ["non-functional requirements", "nonfunctional requirements", "nfrs", "quality attributes"],
    "integrations": ["integrations", "interfaces", "dependencies", "external systems"],
    "data": ["data requirements", "data"],
    "constraints": ["constraints", "timeline", "budget"],
    "assumptions": ["assumptions"],
    "stakeholders": ["stakeholders"],
    "success_metrics": ["success metrics", "kpis", "success criteria"],
    "open_questions": ["open questions", "questions"],
}
REQUIRED_SECTIONS = ["overview", "objectives", "functional_requirements", "non_functional_requirements",
                     "constraints", "success_metrics", "out_of_scope"]

AMBIGUOUS_TERMS = ["fast", "quickly", "easy to use", "easy", "user-friendly", "intuitive", "smart", "relevant",
                   "scalable", "robust", "as needed", "as appropriate", "etc", "tbd", "and/or", "flexible",
                   "seamless", "should be able to", "modern", "efficient", "minimal"]

SUBCATEGORY_KEYWORDS = {
    "performance": ["latency", " ms", "p95", "p99", "per second", "load in", "respond", "throughput", "seconds at", "minutes of", "seconds of"],
    "availability": ["availability", "uptime", "99.", "no event loss", "failover"],
    "security": ["sso", "oauth", "encrypt", "role-based", "rbac", "permitted", "tokenis", "clear text", "access"],
    "compliance": ["audit", "retain", "retention", "pci", "hipaa", "gdpr", "sox", "explainable"],
    "scalability": ["scale", "horizontal", "concurrent", "3x"],
    "deployment": ["on-prem", "premises", "aws", "lambda", "cloud", "data centre", "data center"],
    "usability": ["easy to use", "user-friendly", "intuitive"],
    "ingestion": ["ingest", "stream", "webhook"],
    "workflow": ["approve", "reject", "assign", "queue", "status", "case", "submit", "enrol", "redeem", "adjust"],
    "notification": ["notif", "email", "sms", "push", "remind"],
    "reporting": ["dashboard", "report", "export", "analytics"],
    "search": ["search", "filter", "find"],
    "integration": [" api", "ledger", "card network", "switch", "posted to", "scoring service", "management system", "point-of-sale", "order service", "campaign tool"],
    "rules": ["rule", "score", "threshold", "fraud"],
    "documents": ["upload", "document", "evidence", "pdf"],
}

DOMAIN_KEYWORDS = {
    "fintech": ["card", "payment", "chargeback", "fraud", "ledger", "merchant", "dispute", "pci"],
    "hr": ["leave", "employee", "payroll", "hris"],
    "retail": ["store", "loyalty", "point-of-sale", "checkout", "e-commerce"],
    "healthcare": ["patient", "clinic", "hipaa"],
    "logistics": ["shipment", "carrier", "parcel"],
    "internal-tools": ["wiki", "internal", "support agents", "ticket", "survey"],
}

REQ_LINE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(?:(?P<id>(?:FR|NFR|INT|DR|REQ|CON)-\d+)\s*)?(?:\[(?P<prio>must|should|could)\]\s*)?(?P<text>.+)$", re.I)


class ParseError(ValueError):
    pass


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        import docx  # python-docx
        d = docx.Document(str(path))
        lines = []
        for p in d.paragraphs:
            style = (p.style.name or "").lower()
            t = p.text.strip()
            if not t:
                continue
            if style.startswith("heading"):
                lvl = re.search(r"(\d)", style)
                lines.append("#" * (int(lvl.group(1)) + (0 if lvl else 1) if lvl else 2) + " " + t)
            elif "list" in style:
                lines.append("- " + t)
            else:
                lines.append(t)
        for table in d.tables:
            for row in table.rows:
                lines.append("- " + " | ".join(c.text.strip() for c in row.cells))
        return "\n".join(lines)
    return path.read_text(encoding="utf-8", errors="replace")


def _canonical(heading: str) -> Optional[str]:
    h = re.sub(r"^[\d.\s]+", "", heading).strip().lower()
    for canon, syns in SECTION_SYNONYMS.items():
        if any(h == s or h.startswith(s) for s in sorted(syns, key=len, reverse=True)):
            return canon
    return None


def _sections(text: str) -> tuple[str, dict[str, list[str]]]:
    title, cur, out = "", None, {}
    for line in text.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            head = m.group(2).strip()
            if len(m.group(1)) == 1 and not title:
                title = re.sub(r"^(BRD|Business Requirements Document)\s*[:\-]\s*", "", head, flags=re.I)
                cur = None
                continue
            canon = _canonical(head)
            if canon:
                cur = canon
                out.setdefault(cur, [])
            continue
        if cur and line.strip():
            out[cur].append(line.rstrip())
    return title, out


def _bullets(lines: list[str]) -> list[str]:
    return [re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", l).strip() for l in lines if re.match(r"^\s*(?:[-*]|\d+[.)])\s+", l)]


def _subcategory(text: str, category: str) -> str:
    t = " " + text.lower()
    order = (["deployment", "performance", "availability", "security", "compliance", "scalability", "usability"]
             if category == "non_functional" else
             ["ingestion", "rules", "integration", "notification", "reporting", "search", "documents", "workflow"])
    for sub in order:
        if any(k in t for k in SUBCATEGORY_KEYWORDS[sub]):
            return sub
    return "general"


def _ambiguous(text: str) -> list[str]:
    t = " " + re.sub(r"[^a-z0-9/.\- ]", " ", text.lower()) + " "
    found = [w for w in AMBIGUOUS_TERMS if f" {w} " in t or f" {w}." in t]
    # numbers make "fast"/"scalable" concrete
    if re.search(r"\d", text):
        found = [w for w in found if w not in ("fast", "quickly", "scalable", "efficient")]
    return sorted(set(found))


def _weeks(text: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*weeks?", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*months?", text, re.I)
    if m:
        return round(float(m.group(1)) * 4.33, 1)
    return None


def _constraints(lines: list[str], full_text: str) -> Constraints:
    joined = " ".join(lines)
    team = re.search(r"team of (\d+)|(\d+)\s+engineers", joined, re.I)
    budget = re.search(r"\$\s?[\d,.]+\s*[kKmM]?", joined)
    deadline = None
    for l in lines:
        if re.search(r"go-live|launch|deliver|timeline|deadline|within", l, re.I):
            deadline = _weeks(l) or deadline
    low = full_text.lower()
    deployment = None
    if re.search(r"on-prem|on premises|on-premises|data centre|data center", low):
        deployment = "on-prem"
    if re.search(r"\baws\b|amazon web services", low):
        deployment = "aws" if deployment is None else "conflict:on-prem+aws"
    return Constraints(deadline_weeks=deadline, team_size=int(next(g for g in team.groups() if g)) if team else None,
                       budget=budget.group(0) if budget else None, deployment=deployment)


def _domain(text: str) -> str:
    low = text.lower()
    scores = {d: sum(low.count(k) for k in kws) for d, kws in DOMAIN_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def _contradictions(reqs: list[Requirement], cons: Constraints, out_of_scope: list[str]) -> list[Flag]:
    flags: list[Flag] = []
    n = 0
    # 1. deployment target conflict
    onprem = [r.id for r in reqs if re.search(r"on-prem|premises|data centre|no public cloud", r.text, re.I)]
    cloud = [r.id for r in reqs if re.search(r"\baws\b|lambda|s3\b|azure|gcp|serverless", r.text, re.I)]
    if onprem and cloud:
        n += 1
        flags.append(Flag(id=f"CON-{n}", kind="contradiction", severity="high", brd_refs=onprem + cloud,
                          message=f"Deployment conflict: {', '.join(onprem)} require on-premises while {', '.join(cloud)} require public-cloud services.",
                          resolution="Escalated to EM. Conservative default: design cloud-portable components (containers, no managed serverless) until the deployment target is decided."))
    # 2. numeric conflict on retention
    ret = [(r.id, m.group(0)) for r in reqs for m in [re.search(r"retain\w*\s+for\s+(\d+)\s+(years|months|days)", r.text, re.I)] if m]
    if len({v for _, v in ret}) > 1:
        n += 1
        flags.append(Flag(id=f"CON-{n}", kind="contradiction", severity="high", brd_refs=[i for i, _ in ret],
                          message="Conflicting retention periods: " + "; ".join(f"{i}: {v}" for i, v in ret) + ".",
                          resolution="Escalated to EM. Conservative default: retain for the longest period stated and confirm with Compliance."))
    # 3. requirement contradicts out-of-scope list
    for oos in out_of_scope:
        key = re.sub(r"[^a-z ]", "", oos.lower()).strip()
        key_terms = [w for w in key.split() if len(w) > 3]
        if not key_terms:
            continue
        for r in reqs:
            if all(w in r.text.lower() for w in key_terms):
                n += 1
                flags.append(Flag(id=f"CON-{n}", kind="contradiction", severity="medium", brd_refs=[r.id],
                                  message=f"{r.id} depends on '{oos}', which the BRD lists as out of scope.",
                                  resolution=f"Escalated to EM. Conservative default: treat {r.id} as deferred (email fallback) and keep '{oos}' out of scope."))
    # 4. feasibility: must-have load vs deadline/team
    musts = sum(1 for r in reqs if r.priority == "must")
    if cons.deadline_weeks and cons.team_size:
        capacity = cons.deadline_weeks * cons.team_size
        if musts and capacity / musts < 3.0:
            n += 1
            flags.append(Flag(id=f"CON-{n}", kind="feasibility", severity="high",
                              message=(f"{musts} Must requirements with {cons.team_size} engineers in {cons.deadline_weeks:g} weeks "
                                       f"({capacity / musts:.1f} person-weeks per Must; past projects needed >= 5)."),
                              resolution="Escalated to EM. Conservative default: plan the longer historical timeline and propose a phased release."))
    return flags


def parse_brd(path: Path, text: Optional[str] = None) -> ParsedBRD:
    text = text if text is not None else read_text(path)
    title, secs = _sections(text)
    if not secs:
        raise ParseError("no recognisable BRD sections (headings) found")

    reqs: list[Requirement] = []
    counters: dict[str, int] = {}
    sec_cat = {"functional_requirements": ("functional", "FR"), "non_functional_requirements": ("non_functional", "NFR"),
               "integrations": ("integration", "INT"), "data": ("data", "DR")}
    for sec, (cat, prefix) in sec_cat.items():
        for line in secs.get(sec, []):
            m = REQ_LINE.match(line)
            if not m:
                continue
            rid = (m.group("id") or "").upper()
            if not rid:
                counters[prefix] = counters.get(prefix, 0) + 1
                rid = f"{prefix}-A{counters[prefix]:02d}"  # auto-assigned id
            body = m.group("text").strip()
            prio = (m.group("prio") or ("must" if cat != "integration" else "must")).lower()
            reqs.append(Requirement(id=rid, text=body, section=sec, category=cat,
                                    subcategory=_subcategory(body, cat), priority=prio,
                                    ambiguous_terms=_ambiguous(body)))

    cons_lines = secs.get("constraints", [])
    cons = _constraints(cons_lines, text)
    for l in _bullets(cons_lines):
        counters["CON"] = counters.get("CON", 0) + 1
        reqs.append(Requirement(id=f"CON-{counters['CON']:02d}", text=l, section="constraints", category="constraint",
                                subcategory="timeline" if _weeks(l) or "tbd" in l.lower() else "resourcing",
                                priority="must", ambiguous_terms=_ambiguous(l)))

    in_scope = _bullets(secs.get("in_scope", []))
    out_scope = _bullets(secs.get("out_of_scope", []))
    found = sorted(secs)
    missing = [s for s in REQUIRED_SECTIONS if s not in secs or not secs[s]]

    flags: list[Flag] = []
    for i, s in enumerate(missing, 1):
        sev = "high" if s in ("non_functional_requirements", "functional_requirements") else "medium"
        res = ("Org default SLOs from engineering standards applied and recorded as assumptions."
               if s == "non_functional_requirements" else "Proceeding; flagged for EM.")
        flags.append(Flag(id=f"MISS-{i}", kind="missing_section", severity=sev,
                          message=f"BRD is missing the '{s.replace('_', ' ')}' section.", resolution=res))
    amb = [r for r in reqs if r.ambiguous_terms]
    for i, r in enumerate(amb, 1):
        flags.append(Flag(id=f"AMB-{i}", kind="ambiguity", severity="medium", brd_refs=[r.id],
                          message=f"{r.id} uses vague terms {r.ambiguous_terms}; acceptance criteria cannot be derived.",
                          resolution="Agents must quantify using org defaults and mark as assumption; confirm with product owner."))
    flags += _contradictions(reqs, cons, out_scope)

    obj = _bullets(secs.get("objectives", []))
    classification = "confidential" if re.search(r"classification:\s*confidential", text, re.I) else "internal"
    return ParsedBRD(
        brd_id=f"BRD-{sha(text, 8)}", content_hash=sha(text, 64), title=title or path.stem,
        domain=_domain(text), classification=classification, objectives=obj, in_scope=in_scope,
        out_of_scope=out_scope, requirements=reqs, constraints=cons,
        stakeholders=_bullets(secs.get("stakeholders", [])) or [l.strip() for l in secs.get("stakeholders", [])],
        success_metrics=_bullets(secs.get("success_metrics", [])), open_questions=_bullets(secs.get("open_questions", [])),
        sections_found=found, missing_sections=missing, flags=flags)
