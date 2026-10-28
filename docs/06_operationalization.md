# 6. Operationalization & Monitoring

Success and failure were defined **before** building (quality-first development); thresholds live in `src/config.py`.

## 6.1 Success criteria (measurable)

| # | Criterion | Target | Current (offline, tuned) | Measured by |
|---|---|---|---|---|
| S1 | Completeness: every routed BRD requirement addressed | 100% on every eval BRD | 100% (final) | Critic coverage + rule checks |
| S2 | Groundedness: claims citing a retrieved source | ≥ 75% per artifact | 92–100% per run (final) | Critic |
| S3 | Cross-agent contradictions in delivered packs | 0 | 0 | Critic cross-checks |
| S4 | Actionability | ≥ 4.0 / 5 per artifact | 4.83–5.0 | Critic judge (LLM when keyed) |
| S5 | Schema parse rate at hand-offs | 100% (after retries) | 100% | execution metrics |
| S6 | End-to-end pipeline time | < 5 min per BRD (LLM mode) | 0.2–0.5 s offline | `latency_ms` per agent |
| S7 | Guardrail test suite | 100% of G-cases behave as expected | 3/3 | `run_evals.py` expected checks |
| S8 | EM acceptance at HITL | ≥ 80% approved, mean rating ≥ 4 | not yet measured (needs pilot EMs) | `hitl` records |

## 6.2 Failure modes and mitigations

| # | Failure mode | Detection | Mitigation |
|---|---|---|---|
| F1 | LLM returns malformed JSON / schema-invalid output | pydantic validation; `malformed_json`, `schema_violation` triggers | re-prompt with errors (×2) → heuristic fallback + `llm_fallback_to_heuristic` flag |
| F2 | No RAG hits for an agent | provenance registry empty | proceed with disclaimer in assumptions; groundedness fails so badge ≤ AMBER; alert if > 5% of runs |
| F3 | Critic loop doesn't converge | round counter | hard cap at 2 revisions → `escalate`; AMBER/RED shown to EM |
| F4 | BRD is malformed / injected / contains PII | input guardrails | reject with reasons / quarantine + escalate / redact |
| F5 | BRD contradicts itself or deadline is infeasible | parser + schedule flags | conservative default + automatic EM escalation ticket |
| F6 | External tool (Jira) unavailable | `tool_call ok=false` | exponential-backoff retry (×2); on persistent failure the pack is still saved locally and the error recorded |
| F7 | Agent crash (bug) | `agent_error` events | retry ×2; then run stops with `failed:<agent>` — no partial pack exported |
| F8 | Silent quality drift (prompt/model/KB change) | nightly `run_evals.py` | pre-release gates below block deployment |

## 6.3 Pre-release gates (run `python run_evals.py` + `python tests/test_pipeline.py`)

A change to prompts, models, knowledge base, thresholds or code ships only if:
1. All tests pass (contract, guardrail, LLM-retry/fallback, confidentiality-in-logs).
2. All expected-outcome checks pass on the eval set (currently 44/44 for tuned, 44/44 for baseline).
3. Final badge GREEN or AMBER on E1–E5 and G2; G1/G3 rejected.
4. No regression vs the last release on: mean round-0 groundedness, mean Critic issues at round 0, rule pass rate, ROUGE-L (tolerance −2%).
5. Critic calibration verdict agreement ≥ 90% (currently 94%).
6. In LLM mode: p95 pipeline latency < 5 min and mean cost per BRD within budget.

## 6.4 Logging (every agent execution)

`outputs/<run>/run_log.jsonl`, one JSON object per event:

| Event | Fields |
|---|---|
| `run_start` / `run_end` | provider, profile, file extension, **file hash**, status, metrics |
| `agent_execution` | agent, step (generate / revise / review / route), revision, **input_hash**, **prompt_hash**, **output_hash**, `rag_chunks [{id, score}]`, `output_summary` (counts / ids only), `critic_scores` (Critic), `decisions` (template, pattern ranking, analogs, tool selection, routing), `revision_fixes`, `guardrail_triggers`, model, mode (offline-heuristic / llm(attempt=n) / fallback-heuristic), tokens in/out, cost USD, `latency_ms`, status / error |
| `tool_call` | tool, agent, ok, attempt, latency, filters / chunk ids for `kb_search` |
| `guardrail` | stage (input / rag / critic), type, item, detail (ids only) |
| `contract_violation`, `agent_error` | producer/consumer, attempt, truncated validation error |
| `brd_parsed` | BRD id, **content hash**, counts, sections, flag counts, classification |
| `decision`, `hitl` | export decision; HITL decision, EM rating, hashed note |

`summary.json` aggregates per-agent executions, errors, latency, tokens and cost, tool success rate, guardrail triggers, contract violations, and the Critic score history.

## 6.5 Monitoring (production)

| Signal | Source | Alert |
|---|---|---|
| Pipeline success rate | `run_end.status` | < 95% completed (excl. rejected inputs) over 24 h |
| Fallback rate | `mode = fallback-heuristic` | > 5% of agent executions |
| Badge mix | `final_badge` | RED > 10% or AMBER > 40% weekly |
| Revision load | `revision_rounds`, issue codes | mean rounds > 1.5 or a single issue code > 30% (prompt/KB gap) |
| Grounding | `groundedness_ratio` | weekly mean < 80% |
| Cost & latency | per-agent tokens / latency | p95 latency > 5 min; cost per BRD > budget |
| Guardrails | `guardrail` events | any injection quarantine → security channel |
| HITL | `hitl.decision`, `em_rating` | approval < 80% or rating < 4 over 2 weeks |

The per-run HTML dashboard (`dashboard.html`) shows badges, score per revision, cross-agent checks, Critic feedback by round, guardrail events and per-agent cost/latency for the EM.

## 6.6 Productionization plan 

**Data strategy**

| Practice | How it applies here |
|---|---|
| Explicit data ownership | One owner per knowledge-base source type: past BRDs + templates (PMO), patterns + standards (architecture guild), timelines (delivery), decision log (tech leads) |
| Data as a product with SLAs | Freshness: templates and standards reviewed quarterly; timelines and decision log appended within 2 weeks of a project closing. Completeness: every past project has effort, duration and complexity |
| Versioned pipelines | The index manifest carries `kb_version`, a content hash of every chunk; each run logs it in `run_start`, so any pack can be traced to the exact knowledge base it used |
| Data validation | Inputs: file / text / parsed-BRD validation. Hand-offs: pydantic contracts. Knowledge base: chunk counts per source type in the manifest; a drop or a new `kb_version` triggers the eval suite before release |

**Deployment strategy**

| Practice | How it applies here |
|---|---|
| Modular workflows | Each agent is a LangGraph node with its own contract and prompt; agents can be changed, tested and released independently |
| Shadow mode → staged rollout | Pilot runs next to the EM's normal process (outputs not acted on) → one org → company-wide (`11 §11.3`) |
| Evaluation pipeline, offline + online | Offline: `run_evals.py` + tests as pre-release gates (§6.3). Online: HITL approval and EM ratings, LangSmith traces, and the badge mix per week |
| Rollback | Prompts, thresholds, model names and the knowledge base are versioned in git (`kb_version`, `src/prompts.py`, `src/config.py`); rollback = redeploy the previous tag. The offline engine is always available as a fallback |
| One deployment path | `pip install -e .` from pinned `pyproject.toml`, the same CLI in CI and production; no notebook-to-production path |
| Cost and latency | Model routing (small / large), capped retrieval, revision cap, opt-in response cache (`BRD2ENG_LLM_CACHE=1`); per-agent tokens, cost and latency logged |

**Monitoring and maintenance**

- Alerts: the table in §6.5, computed from `run_log.jsonl` / `summary.json`.
- Tooling: LangSmith tracing for LangChain and LangGraph runs (`LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, plus the data-boundary opt-in); logs can also be shipped to Prometheus / Grafana or Datadog.
- Privacy, bias and compliance monitoring: run the LLM-as-Judge (`EVAL_JUDGE`) on a weekly sample of approved packs; injection quarantines alert the security channel.
- Contracts over assumptions: every hand-off is validated; contract violations are counted and alerted on.
- Incident management: a failed run stops without exporting; persistent failures are escalated to the platform engineer (responsible in the RACI) and the EM keeps the offline pack.
- Iteration: approved packs and EM ratings feed back into the knowledge base and the calibration set; prompt and threshold changes ship only through the gates in §6.3.
