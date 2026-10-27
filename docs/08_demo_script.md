# 8. Demo Script

## Capstone presentation (5 minutes + Q&A)

The Week 2 format: summary and architecture (1 min), demo (3 min), learnings (1 min), Q&A (1–2 min). Before presenting, run once so the outputs exist, and keep `docs/01_architecture.md` and a terminal open.

| Time | Segment | Show | Say |
|---|---|---|---|
| 0:00–1:00 | Summary & architecture | `python run_pipeline.py --show-graph` or the diagram in `01_architecture.md` | BRD → plan takes 2–5 days and problems surface late. 7 agents, one job each, on a LangGraph hub-and-spoke graph; RAG over our own history; Critic loop capped at 2 rounds; EM approval before anything is exported. |
| 1:00–2:00 | Run it live | `python run_pipeline.py eval_dataset/brds/E2_merchant_dispute_portal.md --provider openai --allow-external` (offline: drop the two flags) | Parsing, routing, Planning and Design agents, Critic round 0 AMBER → round 1 GREEN. The graph pauses at the approval step: press `a`. |
| 2:00–3:00 | The pack and the Critic | `outputs/<run>/dashboard.html`, then `engineering_pack.md` | Badges and score per revision, cross-agent checks, citations on every claim. E3: schedule 23 → 36.5 weeks after the Critic caught the complexity mismatch, escalated automatically. |
| 3:00–4:00 | Safety and evaluation | `python run_pipeline.py eval_dataset/brds/G2_prompt_injection_pii.md --auto-approve`; `eval_results/eval_report.md` | PII redacted, injection quarantined, malformed input rejected. 44/44 expected checks, 5 eval methods, retrieval tuning 82.5% → 93.3% groundedness, Critic calibration (precision 1.0, recall 0.71). |
| 4:00–5:00 | Learnings & challenges | `docs/06_operationalization.md §6.6`, `docs/11_strategy_and_plan.md` | Deterministic checks beat LLM judging for what is checkable; contracts at every hand-off made LLM output usable; the hard part is operationalising (data boundary, monitoring, calibration). Next: live-LLM eval, shadow-mode pilot with 3 EMs. |
| 5:00–7:00 | Q&A | — | Likely questions: cost per BRD (~$1, `11 §11.4`), why not fine-tune (`07`), what if the BRD is wrong (escalation), how to trust it (citations, badges, HITL). |

Record this as the demo video for submission (PRFAQ `10_prfaq.md` + architecture `01_architecture.md` + recording).

## Extended walkthrough (≈ 9 minutes)

Record your terminal + browser. Commands assume the repo root and a fresh `outputs/` folder.

| Time | Segment (brief §10) | What to show | Say |
|---|---|---|---|
| 0:00–1:15 | Architecture walkthrough | `docs/01_architecture.md` Mermaid diagram | Problem (BRD → plan takes days, inconsistent). 4 layers, 7 agents, hub-and-spoke, 3 workflows, Critic loop capped at 2, HITL gate. Why hub-and-spoke. |
| 1:15–2:15 | BRD upload & parsing | `eval_dataset/brds/E2_merchant_dispute_portal.md`; run `python run_pipeline.py eval_dataset/brds/E2_merchant_dispute_portal.md` (interactive) and pause at the HITL prompt; open `outputs/<run>/parsed_brd.json` | 22 requirements with IDs, priorities, categories; NFR-06 flagged as ambiguous; classification Confidential detected. |
| 2:15–3:15 | RAG retrieval | `run_log.jsonl` → `tool_call kb_search` lines (filters, chunk ids); `.index/manifest.json`; optionally `mcp_server.py` `search_knowledge_base` call | 6 source types, 78 chunks, per-agent filters; Schedule pulls timeline rows P-05/P-06/P-11 (fintech, complexity 4). |
| 3:15–4:30 | Agent outputs with citations | `engineering_pack.md` (or PDF): plan phases with `[tmpl:T1#4]`, risks citing `pbrd:PB-001#4`, schedule basis citing analogs, architecture table, stack options, Sources list | Every claim carries BRD refs + chunk ids; schedule p50 23.5 / p80 28 weeks with 7 engineers. |
| 4:30–5:45 | Critic review cycle, before/after | `artifacts/critic.round0.json` vs `round1`; `poc_planner.rev0.json` vs `rev1.json` (SC-NFR-06); dashboard "Critic feedback by round" | Round 0 AMBER 4.87: PoC criterion "easy to use" unmeasurable → hard gate. Round 1 GREEN 4.95: quantified as ≥ 90% task success, assumption recorded. Then show E3 in `eval_results/eval_report.md`: schedule 23 → 36.5 weeks once the Critic caught the complexity/template mismatch. |
| 5:45–6:45 | Guardrails firing | `python run_pipeline.py eval_dataset/brds/G2_prompt_injection_pii.md --auto-approve` and `… G1_malformed_meeting_notes.txt`; show `guardrail` events, `INJ-1`, rejected reasons | PII + API key redacted, FR-04 injection quarantined, no "crypto" in any artifact; malformed input rejected. |
| 6:45–7:45 | Evaluation scores & badges | `python run_evals.py`; `eval_results/eval_report.md` tables; dashboard badges | 5 methods; 44/44 expected checks; baseline vs tuned (groundedness 82.5% → 93.3% at round 0, issues −45%); calibration MAE 0.44. |
| 7:45–8:30 | Operationalization | `docs/06_operationalization.md`, `summary.json` metrics, dashboard health card; demo of `BRD2ENG_SIMULATE_TOOL_FAILURE=1` showing a Jira 503 retried | Success criteria, failure modes, pre-release gates, logging with hashes only. |
| 8:30–9:15 | Stretch features + close | `jira_export.json` (epics/stories with requirement traceability), `mcp_server.py` tools/list, HITL approval → exports | MCP server, Jira export, EM dashboard. Close on the escalation: "the system told me the date is wrong before my team did." |

Tip: run the interactive HITL once on camera (`a` to approve, rating `4`) so the human evaluation method is visible.
