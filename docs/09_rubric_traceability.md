# 9. Rubric Traceability (Capstone 1 rubric → evidence)

| Rubric area (weight) | Sub-criterion | Evidence |
|---|---|---|
| **Agent architecture & orchestration (20)** | Decomposition & role clarity | 7 agents, one contract each — `src/agents/`, `docs/02_agent_contracts.md` |
| | Orchestration design & justification | Hub-and-spoke + bounded revision edge; alternatives; 50+ BRDs/week — `docs/01_architecture.md §1.3, §1.7` |
| | Workflow correctness & state | `PipelineState`, routing safety net, fix memory, dependency cascade — `src/agents/orchestrator.py`; 8/8 eval inputs behave as expected |
| | Error handling & fallback | retries, LLM re-prompt → fallback, tool backoff, no-RAG disclaimer, revision cap — `docs/01 §1.5`, `tests/test_pipeline.py` |
| **RAG implementation & grounding (15)** | KB quality & coverage | 6 source types, 78 chunks — `knowledge_base/`, `docs/03 §3.1` |
| | Chunking, embeddings, retrieval design | `docs/03 §3.2–3.6`, `src/rag/` |
| | Grounding & citation quality | every claim has `brd_refs` + `citations`; provenance registry; targeted re-grounding; Sources list in pack; 92–100% claims cited (final) |
| **Critic & revision loop (15)** | Rubric design | 4 dimensions + thresholds + badges — `src/agents/critic.py` docstring |
| | Feedback quality | item-level issues with codes and suggested fixes — `docs/02` issue-code table; `artifacts/critic.round0.json` |
| | Revision loop with measurable gains | AMBER→GREEN on all completed BRDs; E3 23→36.5 wks; E2 PoC actionability 3.5→5.0 — `docs/04 §4.4` |
| **Evaluation framework & badges (10)** | ≥ 2 methods | 5: rule-based, LLM-as-Judge (+proxy), execution, ROUGE-L reference, human (HITL rating) — `src/evals/metrics.py` |
| | Dataset & coverage | 5 BRDs (simple → complex + 2 edge) + 3 guardrail inputs + expected outcomes + calibration set — `eval_dataset/` |
| | Badges & tracking | per-artifact and overall badges each round; dashboard; `summary.json → critic_history` |
| **Structured output contracts & tooling (10)** | Schema design & validation | pydantic models + cross-field validators; `docs/schemas/*.json` |
| | Enforcement at every hand-off | `validate_handoff` in the Orchestrator; LLM-side validation with re-prompt; 100% parse rate |
| | Tool calling & integrations | `kb_search`, `brd_parser`, mock Jira REST (epics/stories/escalation, retried), Markdown/PDF/HTML exports, MCP server |
| **Guardrails, safety & reliability (10)** | Input validation & schema | `docs/05`; G1/G3 rejected |
| | Hallucination & scope control | fabricated-citation, unknown-requirement, weak-support, scope-creep checks; injection watch terms; deferral of out-of-scope requirements |
| | Cross-agent consistency | 10 Critic cross-checks — `Critic.cross_checks` |
| **Output quality (10)** | Plan & schedule | template-based phases with exit criteria, owned risks, analog-based p50/p80, deadline feasibility + Must-only option — `outputs/sample_run_E2/engineering_pack.md` |
| | Architecture & PoC | pattern vs alternatives, component↔requirement trace, NFR mechanisms, Mermaid; measurable PoC criteria |
| | Tech stack | 2–3 options, explicit weights, familiarity matrix + decision-log outcomes, approved-list check |
| **Operationalization & monitoring (5)** | Success/failure criteria | `docs/06 §6.1–6.3` |
| | Logging & monitoring | `run_log.jsonl` fields, `summary.json`, dashboard, alert table — `docs/06 §6.4–6.5` |
| **Documentation & demo (5)** | Documentation completeness | `docs/01`–`11` (incl. PRFAQ and strategy / leadership asks), README |
| | Demo | `docs/08_demo_script.md`: 5-minute presentation + extended walkthrough (video to be recorded by the learner) |
| **Stretch (+10)** | MCP architecture | `mcp_server.py` (initialize, tools/list, tools/call) |
| | Jira export | epics per phase, stories per requirement, PoC epic — `src/tools/exporters.py::to_jira` |
| | EM dashboard | `dashboard.html` per run |

## Course guideline compliance (Capstone Week 1 and Week 2 playbooks)

| Guideline | Status | Evidence |
|---|---|---|
| **Week 1 · Capstone requirements** | | |
| ≥ 2 workflows | Met | Planning, Design, Validation — `01 §1.6`, `src/graph.py` |
| ≥ 2 agents per workflow, agent-to-agent interaction | Met | Plan → Schedule; Architect → PoC → Tech Stack; Critic → originating agents |
| Agent → Tool | Met | `kb_search`, `brd_parser`, Jira client, exporters, MCP server |
| Agent → Action (independent) | Met | Orchestrator opens the escalation ticket before the HITL gate |
| Agent → Decision (choose among tools) | Met | Tech Stack Recommender picks `standards_lookup` / `decision_log_lookup` per component category (`tool_decisions`) |
| External frameworks for evaluation, fine-tuning & optimization | Met | scikit-learn metrics, LangSmith tracing, LangGraph / LangChain; optimisation by retrieval tuning and routing; fine-tuning rejected with reasons (`07`) |
| **Week 1 · Shared DNA** | | |
| One role = one job = one output contract | Met | `02_agent_contracts.md`, `src/contracts.py` |
| RAG grounds every output | Met | `03_rag_design.md`; citations on every claim |
| Structured, validated hand-offs | Met | `validate_handoff`, LLM re-prompt on schema errors |
| Quality-gate agent (Critic) with ≤ 2 revisions and cross-agent checks | Met | `src/agents/critic.py`, conditional edge in `src/graph.py` |
| ≥ 2 evaluation methods + golden set | Met | 5 methods; `eval_dataset/expected`, `critic_calibration.json` |
| Guardrails: confidentiality, PII, hallucination, scope creep | Met | `05_guardrails_safety.md` |
| Operationalization from day one | Met | `06 §6.1–6.5` |
| Measurable improvement loop | Met | Revision-over-revision and baseline → tuned tables in `04` |
| **Week 1 · Reference architecture and orchestration** | | |
| 4 layers + cross-cutting orchestration, guardrails, observability & cost, HITL | Met | `01 §1.1–1.2`; per-agent tokens / cost / latency; LangGraph `interrupt()` |
| Pattern choice justified; revision loop has an explicit cap | Met | `01 §1.3` |
| Model routing, prompt compression, context limits | Met | small / large tiers; top-k 5, 900 characters per chunk |
| Prompts tuned with care | Met | Agent Prompt Template in `src/prompts.py` |
| Exercise 1 · PRFAQ | Met | `10_prfaq.md` |
| Exercise 2 · Strategy, plan with milestones, leadership asks, architecture diagram (workflows → agents → tools → actions) | Met | `11_strategy_and_plan.md`, `01 §1.1` |
| Leadership concepts: stakeholder matrix, readiness, ethics, cost | Met | `11 §11.5–11.7`, `05` |
| **Week 2 · Productionization** | | |
| Data strategy: ownership, SLAs, versioned pipelines, validation | Met | `06 §6.6`; `kb_version` in manifest and run log |
| Deployment: modular workflows, shadow mode / staged rollout, rollback, offline + online evaluation, one deployment path | Met | `06 §6.6`, `11 §11.3`, pinned `pyproject.toml` |
| Monitoring: alerts, LLM-as-Judge for privacy / bias, contracts over assumptions, monitoring tool | Met | `06 §6.5–6.6`; LangSmith tracing |
| Evolving architecture: multi-agent, prompt template, multi-workflow, caching, prompt-injection testing, guardrails | Met | `src/prompts.py`, `BRD2ENG_LLM_CACHE`, G2 eval input |
| Enterprise: incident / escalation path, build vs buy | Met | `06 §6.6`, `07` |
| Precision / recall / F1, human feedback | Met | `04 §4.6`; HITL rating |
| **Week 2 · Submission** | | |
| Presentation: 1 min summary, 3 min demo, 1 min learnings, Q&A | Met | `08_demo_script.md` |
| Check the project into a GitHub repository | **To do (learner)** | Not yet a git repository |
| Submit PRFAQ + architecture doc + demo recording | **To do (learner)** | Docs ready; recording not yet made |
| Live-LLM run | **To do (learner)** | Path tested with mocked models; run once with your OpenAI key |
