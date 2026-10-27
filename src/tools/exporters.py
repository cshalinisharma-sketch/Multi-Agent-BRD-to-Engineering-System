"""Export tools: Markdown engineering pack, PDF, Jira (epics/stories via mock
Jira client), and the escalation ticket action."""
from __future__ import annotations

import json
import re
from pathlib import Path

BADGE_ICON = {"GREEN": "🟢", "AMBER": "🟡", "RED": "🔴"}


def _c(cites) -> str:
    return " " + " ".join(f"`[{c}]`" for c in cites) if cites else ""


def _r(refs) -> str:
    return f" _(BRD: {', '.join(refs)})_" if refs else ""


def to_markdown(state, store) -> str:
    b, a, rep = state.brd, state.artifacts, state.critic_reports[-1]
    plan, sch, arch, poc, stk = (a[k] for k in ["plan_generator", "schedule_estimator", "solution_architect",
                                                 "poc_planner", "tech_stack_recommender"])
    L = [f"# Engineering Pack — {b.title}", "",
         f"Run `{state.run_id}` · BRD `{b.brd_id}` · classification **{b.classification}** · "
         f"overall {BADGE_ICON[rep.overall_badge]} **{rep.overall_badge}** ({rep.overall_score}/5) after "
         f"{rep.revision_round} revision round(s) · HITL: **{state.hitl.get('decision', 'pending')}**", ""]
    L += ["## Quality badges", "", "| Artifact | Badge | Overall | Grounded (cited) | Coverage | Contradictions | Actionability |",
          "|---|---|---|---|---|---|---|"]
    for s in rep.artifact_scores:
        L.append(f"| {s.artifact} | {BADGE_ICON[s.badge]} {s.badge} | {s.overall} | {s.groundedness_ratio:.0%} | "
                 f"{s.coverage_ratio:.0%} | {s.contradictions} | {s.actionability} |")
    esc = state.escalations
    if esc:
        L += ["", "## ⚠️ Decisions needed from the EM", ""]
        for f in esc:
            L.append(f"- **{f.id}** ({f.kind}, {f.severity}): {f.message}" + (f" — *Default applied:* {f.resolution}" if f.resolution else ""))
    L += ["", "## 1. Engineering plan", "", f"Template: `{plan.template_used}` · Team: {plan.headcount} engineers", ""]
    for p in plan.phases:
        L.append(f"### {p.id} {p.name} ({p.effort_share_pct:g}% effort){_c(p.citations)}")
        L.append(f"*Objective:* {p.objective}{_r(p.brd_refs)}")
        L += [f"- {d}" for d in p.deliverables]
        L.append("*Exit criteria:* " + "; ".join(p.exit_criteria))
        L.append("")
    end_wk = {e.phase_id: e.end_week for e in sch.phase_estimates}
    L += ["**Milestones**", "", "| ID | Milestone | Phase | Target (p50) | Acceptance |", "|---|---|---|---|---|"]
    L += [f"| {m.id} | {m.name}{_c(m.citations)} | {m.phase_id} | end of week {end_wk.get(m.phase_id, 0):g} | {m.acceptance} |"
          for m in plan.milestones]
    L += ["", "**Risks**", "", "| ID | Risk | L/I | Mitigation | Owner |", "|---|---|---|---|---|"]
    L += [f"| {r.id} | {r.description}{_r(r.brd_refs)}{_c(r.citations)} | {r.likelihood}/{r.impact} | {r.mitigation} | {r.owner_role} |"
          for r in plan.risks]
    L += ["", "**Team**", ""] + [f"- {t.count} × {t.role} — {t.justification}{_c(t.citations)}" for t in plan.team]
    if plan.reflection:
        L += ["", f"*Reflection self-review:* {len(plan.reflection.issues_found)} issue(s) found; "
                  + ("; ".join(plan.reflection.changes_made) or "no changes needed")]
    L += ["", "## 2. Schedule", "",
          f"p50 **{sch.total_duration_weeks:g} weeks**, p80 **{sch.p80_duration_weeks:g} weeks**, "
          f"{sch.total_effort_person_weeks:g} person-weeks, complexity basis {sch.complexity_basis}"
          + (f", deadline {sch.deadline_weeks:g} weeks → {'fits' if sch.fits_deadline else 'DOES NOT FIT'}" if sch.deadline_weeks else ""),
          "", "| Phase | Weeks | Start–End | Effort (pw) | Roles | Basis |", "|---|---|---|---|---|---|"]
    names = {p.id: p.name for p in plan.phases}
    L += [f"| {e.phase_id} {names.get(e.phase_id, '')} | {e.duration_weeks:g} | w{e.start_week:g}–w{e.end_week:g} | "
          f"{e.effort_person_weeks:g} | {', '.join(e.roles)} | {e.basis}{_c(e.citations)} |" for e in sch.phase_estimates]
    L += ["", "Analogs: " + ", ".join(f"{x.project_id} (cx {x.complexity}, {x.actual_weeks:g} wks, team {x.team_size}, "
                                       f"+{x.variance_pct:g}%)" for x in sch.analogs)]
    L += ["", "## 3. Solution architecture", "",
          f"**Pattern:** {arch.pattern.name}{_c(arch.pattern.citations)} — {arch.pattern.rationale}", "",
          "Alternatives considered: " + "; ".join(arch.pattern.alternatives_considered), "",
          f"Complexity: {arch.complexity_score}/5", "", "```mermaid", arch.mermaid, "```", "",
          "| ID | Component | Category | Responsibility | BRD |", "|---|---|---|---|---|"]
    L += [f"| {c.id} | {c.name}{_c(c.citations)} | {c.category} ({c.kind}) | {c.responsibility} | {', '.join(c.brd_refs)} |"
          for c in arch.components]
    L += ["", "**NFR mapping**", "", "| NFR | Mechanism | Components |", "|---|---|---|"]
    L += [f"| {m.nfr_id} | {m.mechanism}{_c(m.citations)} | {', '.join(m.component_ids)} |" for m in arch.nfr_mapping]
    L += ["", "## 4. Proof of concept", "", f"**Objective:** {poc.objective}", "",
          f"Duration: {poc.duration_weeks:g} weeks · Components: {', '.join(poc.in_scope_component_ids)}", "",
          "| ID | Metric | Target | Measurement | Measurable |", "|---|---|---|---|---|"]
    L += [f"| {s.id} | {s.metric}{_c(s.citations)} | {s.target} | {s.measurement} | {'✅' if s.measurable else '❌'} |"
          for s in poc.success_criteria]
    L += ["", f"**Go / no-go:** {poc.go_no_go}", "", "## 5. Tech stack options", "",
          f"Weights: {stk.weights}", "", "| Option | Scal. | Familiarity | Integr. risk | Cost | Score | Approved |",
          "|---|---|---|---|---|---|---|"]
    L += [f"| {'⭐ ' if o.id == stk.recommended_option_id else ''}{o.id} {o.name} | {o.scalability} | {o.team_familiarity} | "
          f"{o.integration_risk} | {o.cost} | {o.weighted_score} | {'yes' if o.on_approved_list else 'no'} |" for o in stk.options]
    for o in stk.options:
        L += ["", f"**{o.id} {o.name}**{_c(o.citations)} — " + ", ".join(f"{k}: {v}" for k, v in o.components.items()),
              "Pros: " + "; ".join(o.pros), "Cons: " + "; ".join(o.cons)]
    L += ["", f"**Recommendation:** {stk.rationale}", "", "Tools the agent chose: " +
          "; ".join(f"{d.tool}({d.query}) — {d.reason}" for d in stk.tool_decisions)]
    assumptions = [x for k in a for x in getattr(a[k], "assumptions", [])]
    if assumptions:
        L += ["", "## Assumptions", ""] + [f"- {x}" for x in dict.fromkeys(assumptions)]
    cited = sorted({c for k in a for c in re.findall(r'"citations":\s*\[([^\]]*)\]', a[k].model_dump_json())
                    for c in re.findall(r'"([^"]+)"', c)})
    L += ["", "## Sources (retrieved knowledge-base chunks)", ""]
    for cid in cited:
        ch = store.get(cid)
        if ch:
            L.append(f"- `{cid}` — {ch.metadata.get('title') or ch.metadata.get('doc_id')}: {ch.text.splitlines()[0][:110]}")
    return "\n".join(L) + "\n"


def to_pdf(markdown: str, path: Path) -> Path:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle
    styles = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=styles["BodyText"], fontSize=7.5, leading=9)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold")
    emoji = {"🟢": "GREEN:", "🟡": "AMBER:", "🔴": "RED:", "⚠️": "", "⭐": "(rec) ", "✅": "yes", "❌": "no", "→": "->",
             "–": "-", "—": "-", "×": "x", "…": "..."}
    page_w = landscape(A4)[0] - 30 * mm

    def inline(t: str) -> str:
        t = escape(t).replace("`", "")
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)\*(?!\w)", r"<i>\1</i>", t)
        return re.sub(r"(?<!\w)_\((.+?)\)_", r"<i>(\1)</i>", t)

    flow, code, rows, in_code = [], [], [], False

    def flush_table():
        if not rows:
            return
        n = max(len(r) for r in rows)
        data = [[Paragraph(inline(c), head if i == 0 else cell) for c in r + [""] * (n - len(r))] for i, r in enumerate(rows)]
        t = Table(data, colWidths=[page_w / n] * n, repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef6")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        flow.extend([t, Spacer(1, 6)])
        rows.clear()

    for line in markdown.splitlines():
        for k, v in emoji.items():
            line = line.replace(k, v)
        if line.startswith("```"):
            if in_code:
                flow.append(Preformatted("\n".join(code), styles["Code"]))
                code = []
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
            continue
        if line.startswith("|"):
            if not line.startswith("|---"):
                rows.append([c.strip() for c in line.strip().strip("|").split(" | ")])
            continue
        flush_table()
        if line.startswith("# "):
            flow.append(Paragraph(inline(line[2:]), styles["Title"]))
        elif line.startswith("## "):
            flow.append(Paragraph(inline(line[3:]), styles["Heading2"]))
        elif line.startswith("### "):
            flow.append(Paragraph(inline(line[4:]), styles["Heading3"]))
        elif line.startswith("- "):
            flow.append(Paragraph("&bull; " + inline(line[2:]), styles["BodyText"]))
        elif line.strip():
            flow.append(Paragraph(inline(line), styles["BodyText"]))
        else:
            flow.append(Spacer(1, 4))
    flush_table()
    SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm,
                      topMargin=12 * mm, bottomMargin=12 * mm, title="Engineering Pack").build(flow)
    return path


def to_jira(state, client) -> dict:
    """Epics = plan phases (+ PoC); stories = requirement-bearing deliverables."""
    plan, poc = state.artifacts["plan_generator"], state.artifacts["poc_planner"]
    created = {"epics": [], "stories": []}
    for p in plan.phases:
        epic = client.create_issue("Epic", f"{p.id} {p.name}", f"{p.objective}\nExit criteria: {'; '.join(p.exit_criteria)}",
                                   labels=["brd2eng", state.brd.brd_id])
        created["epics"].append({"phase": p.id, **epic})
        for d in p.deliverables:
            m = re.match(r"((?:FR|NFR|INT|CON|DR)-[\w]+) \((\w+)\): (.+)", d)
            if m:
                prio = {"must": "High", "should": "Medium", "could": "Low"}.get(m.group(2), "Medium")
                st = client.create_issue("Story", f"[{m.group(1)}] {m.group(3)}", f"Traceability: {m.group(1)}",
                                         labels=["brd2eng", m.group(1)], parent=epic["key"], priority=prio)
                created["stories"].append({"req": m.group(1), **st})
    pe = client.create_issue("Epic", "PoC: " + poc.objective[:120], poc.go_no_go, labels=["brd2eng", "poc"])
    created["epics"].append({"phase": "POC", **pe})
    for s in poc.success_criteria:
        st = client.create_issue("Story", f"[PoC] {s.metric}: {s.target}", s.measurement, labels=["poc"] + s.brd_refs, parent=pe["key"])
        created["stories"].append({"req": ",".join(s.brd_refs), **st})
    return created


def create_escalation(state, client) -> dict:
    """Autonomous action: the Orchestrator opens an EM escalation ticket for BRD
    contradictions/infeasibility without waiting for the human gate (it informs,
    it does not change scope)."""
    desc = "\n".join(f"{f.id} [{f.kind}/{f.severity}] {f.message} Default: {f.resolution}" for f in state.escalations)
    return client.create_issue("Task", f"EM decision needed: {len(state.escalations)} BRD issue(s) in {state.brd.title}",
                               desc, labels=["brd2eng", "escalation"], priority="High")
