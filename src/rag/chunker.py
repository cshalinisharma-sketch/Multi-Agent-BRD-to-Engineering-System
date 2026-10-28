""""Source-type-aware chunking.

Strategy (see docs/03_rag_design.md):
* past_brd / plan_template / standards (narrative markdown): split on ##/###
  headings; each chunk = heading path + section body. Sections longer than
  MAX_CHARS are split on paragraph boundaries with a one-paragraph overlap.
  Rationale: BRD/template sections are self-contained semantic units; heading
  path gives the embedder context ("Phases > Phase 2: Technical PoC").
* architecture_pattern: one chunk per pattern (atomic; splitting would separate
  "signals" from "trade-offs").
* project_timeline / tech_decision (CSV): one chunk per row rendered as a
  sentence, with every column also stored as typed metadata for filtering.
""""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_CHARS = 1400


@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict = field(default_factory=dict)


def _front_matter(text: str) -> tuple[dict, str]:
    meta: dict = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            text = text[end + 4:]
    return meta, text


def _split_sections(body: str) -> list[tuple[list[str], str]]:
    """Return (heading_path, section_text) for every ##/### section."""
    out, path, buf = [], [], []
    title = ""
    for line in body.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            if buf and "".join(buf).strip():
                out.append((list(path), "\n".join(buf).strip()))
            buf = []
            level, head = len(m.group(1)), m.group(2).strip()
            if level == 1:
                title, path = head, []
            elif level == 2:
                path = [head]
            else:
                path = path[:1] + [head]
        else:
            buf.append(line)
    if buf and "".join(buf).strip():
        out.append((list(path), "\n".join(buf).strip()))
    return [(([title] if title else []) + p, t) for p, t in out]


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    paras = [p for p in text.split("\n") if p.strip()]
    parts, cur = [], []
    for p in paras:
        if sum(len(x) for x in cur) + len(p) > MAX_CHARS and cur:
            parts.append("\n".join(cur))
            cur = [cur[-1]]  # one-paragraph overlap
        cur.append(p)
    if cur:
        parts.append("\n".join(cur))
    return parts


PREFIX = {"past_brd": "pbrd", "plan_template": "tmpl", "standards": "std", "architecture_pattern": "pattern"}


def chunk_markdown(path: Path) -> list[Chunk]:
    meta, body = _front_matter(path.read_text(encoding="utf-8"))
    stype = meta.get("source_type", "doc")
    doc_id = meta.get("doc_id", path.stem)
    chunks: list[Chunk] = []
    if stype == "architecture_pattern":
        for heading, text in _split_sections(body):
            pid = re.search(r"pattern_id:\s*(\S+)", text)
            if not pid:
                continue
            cx = re.search(r"Complexity:\s*(\d)", text)
            chunks.append(Chunk(f"pattern:{pid.group(1)}", f"{heading[-1]}\n{text}",
                                {**meta, "source_type": stype, "doc_id": doc_id, "section": heading[-1],
                                 "pattern_id": pid.group(1), "complexity": int(cx.group(1)) if cx else 3}))
        return chunks
    n = 0
    for heading, text in _split_sections(body):
        for part in _split_long(text):
            n += 1
            hp = " > ".join(heading)
            chunks.append(Chunk(f"{PREFIX.get(stype, 'doc')}:{doc_id}#{n}", f"{hp}\n{part}",
                                {**meta, "source_type": stype, "doc_id": doc_id, "section": heading[-1] if heading else ""}))
    return chunks


def chunk_timelines(path: Path) -> list[Chunk]:
    out = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            text = (f"Past project {row['project_id']} {row['name']} (domain {row['domain']}, complexity {row['complexity']}, "
                    f"pattern {row['pattern']}): {row['req_count']} requirements, {row['integrations']} integrations, "
                    f"team of {row['team_size']}, planned {row['planned_weeks']} weeks, actual {row['actual_weeks']} weeks "
                    f"(variance {row['variance_pct']}%). Notes: {row['notes']}.")
            meta = {"source_type": "project_timeline", "doc_id": row["project_id"], "domain": row["domain"],
                    "complexity": int(row["complexity"]), "pattern": row["pattern"], "req_count": int(row["req_count"]),
                    "integrations": int(row["integrations"]), "team_size": int(row["team_size"]),
                    "planned_weeks": float(row["planned_weeks"]), "actual_weeks": float(row["actual_weeks"]),
                    "variance_pct": float(row["variance_pct"])}
            out.append(Chunk(f"timeline:{row['project_id']}", text, meta))
    return out


def chunk_decisions(path: Path) -> list[Chunk]:
    out = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            text = (f"Tech decision {row['decision_id']} ({row['date']}, project {row['project_id']}, category {row['category']}): "
                    f"chose {row['decision']} over {row['alternatives']}. Rationale: {row['rationale']}. "
                    f"Outcome: {row['outcome']} (rating {row['outcome_rating']}/5).")
            meta = {"source_type": "tech_decision", "doc_id": row["decision_id"], "category": row["category"],
                    "project_id": row["project_id"], "outcome_rating": int(row["outcome_rating"]),
                    "decision": row["decision"]}
            out.append(Chunk(f"decision:{row['decision_id']}", text, meta))
    return out


def chunk_knowledge_base(kb_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for p in sorted(kb_dir.rglob("*")):
        if p.suffix == ".md":
            chunks += chunk_markdown(p)
        elif p.name == "project_timelines.csv":
            chunks += chunk_timelines(p)
        elif p.name == "tech_decision_log.csv":
            chunks += chunk_decisions(p)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids)), "duplicate chunk ids"
    return chunks
