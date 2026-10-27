"""Self-contained HTML dashboard per run (EM view): badges, score-per-revision,
cross-agent checks, escalations, guardrail triggers and per-agent cost/latency."""
from __future__ import annotations

import html
import json

BADGE = {"GREEN": "#1f9d55", "AMBER": "#d69e2e", "RED": "#e53e3e"}


def _b(badge):
    return f'<span class="badge" style="background:{BADGE.get(badge, "#888")}">{badge}</span>'


def write_html_report(state, summary, path):
    reps = state.critic_reports
    final = reps[-1]
    arts = [s.artifact for s in final.artifact_scores]
    rows = ""
    for s in final.artifact_scores:
        hist = " → ".join(f"{r.artifact_scores[i].overall}" for r in reps for i, x in enumerate(r.artifact_scores) if x.artifact == s.artifact)
        rows += (f"<tr><td>{s.artifact}</td><td>{_b(s.badge)}</td><td>{s.overall}</td><td>{s.groundedness_ratio:.0%}</td>"
                 f"<td>{s.coverage_ratio:.0%}</td><td>{s.contradictions}</td><td>{s.actionability}</td>"
                 f"<td class='mono'>{hist}</td></tr>")
    checks = "".join(f"<li>{'✅' if ok else '❌'} {html.escape(k)}</li>" for k, ok in final.cross_agent_checks.items())
    issues_by_round = ""
    for r in reps:
        items = "".join(f"<li><b>{i.target_agent}</b> · {i.code} · {html.escape(i.message)}</li>" for i in r.issues) or "<li>none</li>"
        issues_by_round += f"<details {'open' if r.revision_round == 0 else ''}><summary>Round {r.revision_round}: {_b(r.overall_badge)} {r.overall_score} — {len(r.issues)} issue(s) → {r.decision}</summary><ul>{items}</ul></details>"
    esc = "".join(f"<li><b>{f.id}</b> ({f.kind}): {html.escape(f.message)}<br><small>Default: {html.escape(f.resolution or '')}</small></li>"
                  for f in state.escalations) or "<li>none</li>"
    guards = "".join(f"<li>{html.escape(json.dumps(g))}</li>" for g in state.guardrail_events) or "<li>none at input</li>"
    m = summary["metrics"]
    agent_rows = "".join(f"<tr><td>{a}</td><td>{v['executions']}</td><td>{v['errors']}</td><td>{v['latency_ms']:.0f}</td>"
                         f"<td>{v['tokens_in']}</td><td>{v['tokens_out']}</td><td>${v['cost_usd']:.4f}</td></tr>"
                         for a, v in m["by_agent"].items())
    chart_data = json.dumps({"labels": [f"R{r.revision_round}" for r in reps],
                             "series": {a: [next(x.overall for x in r.artifact_scores if x.artifact == a) for r in reps] for a in arts}})
    arch = state.artifacts.get("solution_architect")
    mermaid = html.escape(arch.mermaid) if arch else ""
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BRD2Eng Run Dashboard</title>
<style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1f;--mute:#6b6b70;--line:#e3e3e0;--acc:#2b6cb0}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#141416;--card:#1d1d20;--ink:#ececee;--mute:#9a9aa2;--line:#2e2e33;--acc:#63b3ed}}}}
:root[data-theme=dark]{{--bg:#141416;--card:#1d1d20;--ink:#ececee;--mute:#9a9aa2;--line:#2e2e33;--acc:#63b3ed}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px}} h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:0 0 10px}}
.sub{{color:var(--mute)}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-top:14px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left}}
.badge{{color:#fff;border-radius:6px;padding:1px 8px;font-size:12px;font-weight:600}} .mono{{font-family:ui-monospace,monospace}}
.kpi{{font-size:28px;font-weight:700}} ul{{padding-left:18px;margin:6px 0}} details{{margin:6px 0}} pre{{white-space:pre-wrap;font-size:12px}}
</style></head><body><main>
<h1>{html.escape(state.brd.title)}</h1>
<div class="sub">Run {state.run_id} · {summary['provider']} · profile {summary['profile']} · HITL: {html.escape(str(state.hitl.get('decision')))}</div>
<div class="grid">
 <div class="card"><h2>Final quality</h2><div class="kpi">{_b(final.overall_badge)} {final.overall_score}/5</div>
   <div class="sub">{len(reps) - 1} revision round(s) · first round {reps[0].overall_score} ({reps[0].overall_badge})</div></div>
 <div class="card"><h2>EM decisions needed</h2><ul>{esc}</ul></div>
 <div class="card"><h2>Pipeline health</h2><div class="sub">agent executions {m['agent_executions']} · errors {m['agent_errors']} ·
   tool calls {m['tool_calls']} (success {m['tool_call_success_rate']}) · guardrail triggers {m['guardrail_triggers']} ·
   contract violations {m['contract_violations']}</div></div>
</div>
<div class="card" style="margin-top:14px"><h2>Artifact scores (final) and score per revision</h2>
<table><tr><th>Artifact</th><th>Badge</th><th>Overall</th><th>Cited</th><th>Coverage</th><th>Contradictions</th><th>Actionability</th><th>Overall by round</th></tr>{rows}</table>
<canvas id="c" height="140" style="width:100%;margin-top:10px"></canvas></div>
<div class="grid">
 <div class="card"><h2>Cross-agent consistency</h2><ul>{checks}</ul></div>
 <div class="card"><h2>Critic feedback by round</h2>{issues_by_round}</div>
</div>
<div class="grid">
 <div class="card"><h2>Input guardrails</h2><ul>{guards}</ul></div>
 <div class="card"><h2>Architecture</h2><pre class="mermaid">{mermaid}</pre></div>
</div>
<div class="card" style="margin-top:14px"><h2>Per-agent cost & latency</h2>
<table><tr><th>Agent</th><th>Runs</th><th>Errors</th><th>Latency ms</th><th>Tokens in</th><th>Tokens out</th><th>Cost</th></tr>{agent_rows}</table></div>
</main>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>try{{mermaid.initialize({{startOnLoad:true,theme:matchMedia('(prefers-color-scheme: dark)').matches?'dark':'default'}})}}catch(e){{}}</script>
<script>
const d={chart_data};const c=document.getElementById('c');const x=c.getContext('2d');
const W=c.width=c.clientWidth*devicePixelRatio,H=c.height=140*devicePixelRatio;x.scale(devicePixelRatio,devicePixelRatio);
const w=W/devicePixelRatio,h=140,pad=30,cols=['#2b6cb0','#38a169','#d69e2e','#805ad5','#e53e3e'];
const css=getComputedStyle(document.documentElement);x.strokeStyle=css.getPropertyValue('--line');x.fillStyle=css.getPropertyValue('--mute');x.font='11px system-ui';
for(let v=3;v<=5;v+=0.5){{const y=h-pad-(v-3)/2*(h-2*pad);x.beginPath();x.moveTo(pad,y);x.lineTo(w-10,y);x.stroke();x.fillText(v,8,y+4)}}
const n=d.labels.length,sx=i=>pad+(n<2?0:i*(w-pad-20)/(n-1));d.labels.forEach((l,i)=>x.fillText(l,sx(i)-6,h-8));
Object.entries(d.series).forEach(([k,s],j)=>{{x.strokeStyle=cols[j%5];x.lineWidth=2;x.beginPath();s.forEach((v,i)=>{{const y=h-pad-(Math.max(v,3)-3)/2*(h-2*pad);i?x.lineTo(sx(i),y):x.moveTo(sx(i),y)}});x.stroke();x.fillStyle=cols[j%5];x.fillText(k.split('_')[0],w-80,14+j*12)}});
</script></body></html>"""
    path.write_text(doc, encoding="utf-8")
