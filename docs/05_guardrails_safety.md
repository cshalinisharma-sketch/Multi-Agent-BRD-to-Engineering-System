# 5. Guardrails, Safety & Responsible AI

BRDs contain proprietary business logic. Guardrails run at three points: **before** any agent sees the input, **at every hand-off**, and **inside the Critic** after generation.

| Guardrail | Where | Mechanism | Evidence |
|---|---|---|---|
| Input validation | `guardrails.validate_file`, `validate_text`, `validate_parsed` | Allow-list `.md/.txt/.docx`; size ≤ 2 MB, non-empty; ≥ 300 chars; must have headings and a requirements section; parser must extract ≥ 3 requirements incl. ≥ 1 functional, with unique IDs | G1, G3 rejected with reasons |
| PII & secret redaction | `guardrails.redact` | Emails, phone numbers, API keys (`sk-…`, `AKIA…`), card-number-like digit runs replaced with `[REDACTED_*]` **before parsing**, so nothing downstream (agents, LLM, logs) sees them | G2: 3 redactions |
| Prompt-injection quarantine | `guardrails.quarantine_injections` | Lines matching instruction patterns ("ignore previous instructions", "reveal your system prompt", "add a … module to the plan" …) are removed before parsing; a flag + EM escalation is raised; distinctive words become *watch terms* checked in every artifact. Agent prompts also wrap the BRD in `<brd>` tags and state that its content is data, not instructions. | G2: FR-04 removed; no "crypto"/"trading" in output |
| Schema compliance | `LLMClient.generate`, `validate_handoff` | pydantic validation on production and again on consumption; re-prompt with errors, retry, fallback | 100% schema parse rate; `test_contract_violation_detected`, `test_llm_retry_then_fallback` |
| Hallucination detection | `guardrails.check_grounding` (run by the Critic) | (1) **fabricated citation**: cited chunk not retrieved by this agent in this run; (2) **unknown requirement**: `brd_refs` not in the BRD; (3) **weak support**: claim↔cited-chunk similarity < 0.03 | `invalid_grounding` issues → targeted re-grounding |
| Scope-creep prevention | `check_grounding` + plan deferral | Feature components need a BRD requirement; enablers need an org-standard citation; scope-bearing items (phases, components, criteria, options) must not mention out-of-scope or injected terms; requirements that conflict with the out-of-scope list are **deferred to an EM decision**, not built | E5 FR-08 deferred; baseline E5 auth enabler re-justified |
| Cross-agent consistency | `Critic.cross_checks` | 10 checks: plan↔schedule phases and headcount, schedule↔architecture complexity, effort vs analogs, plan template↔architecture, PoC components exist and fit the schedule, stack covers architecture categories, stack familiarity vs timeline, stack respects deployment | E3/E4 template + complexity mismatches fixed in round 1 |
| Confidentiality | `run_logger.RunLogger` | Logs contain **hashes** (input, output, prompt, file, BRD content), chunk ids, scores, counts — never BRD text or artifact text. Classification (`Confidential`) is detected and recorded. | `test_end_to_end_demo_brd` asserts no raw BRD text in the log |
| Data boundary (external LLM) | `llm.check_provider_ready` | OpenAI / Anthropic only run with an API key **and** `BRD2ENG_ALLOW_EXTERNAL_CONTENT=1` (`--allow-external`); otherwise the run stops before the BRD is read. Tests and evals default to offline. | `test_external_provider_requires_opt_in` |
| Tracing and cache boundary | `llm.gate_tracing`, `LLMClient._cached_call` | LangSmith tracing records prompts, so it is switched off unless the same opt-in is set; the response cache is opt-in (`BRD2ENG_LLM_CACHE=1`) and git-ignored | `test_llm_cache_and_tracing_gate`; `tracing` field in `run_start` |
| Human-in-the-loop | `Pipeline.hitl_gate` / LangGraph `interrupt()` | Agents analyse and recommend; nothing is pushed to Jira or exported as final until the EM approves. RED packs are auto-rejected in non-interactive mode; the EM can explicitly override. | HITL record in every `summary.json` |

## Handling ambiguity and contradictions

- **Ambiguity** (vague terms such as "fast", "easy to use", "smart", "etc", "TBD") is flagged per requirement by the parser (`AMB-n`). Agents do not guess silently: the plan adds a discovery deliverable to clarify, the PoC quantifies with org default SLOs and records the assumption ("confirm with product owner").
- **Missing sections** (e.g. no NFRs) → org default SLOs from the standards are applied and recorded as assumptions; high-severity gaps are escalated.
- **Contradictions** are raised to the EM (`CON-n`) with the conservative default applied and documented: cloud-portable design until the deployment target is decided; retain for the longest stated period; defer the requirement that conflicts with the out-of-scope list; plan the longer historical timeline.
- **Infeasible deadlines** (parser `CON-n` feasibility + schedule `SCH-1`) are never "solved" by compressing estimates: the schedule keeps the conservative p50/p80 and offers a Must-only release estimate.
- The Orchestrator **automatically opens an escalation ticket** for these issues — an autonomous action that informs but never changes scope.

## Confidentiality limitations (acknowledged)

1. **LLM mode sends BRD text to the model provider** (and to LangSmith when tracing is on). It is therefore opt-in per run. Redaction removes PII and secrets, but business logic is necessarily included. Use a provider with zero-retention / enterprise terms, or run offline mode, for highly sensitive BRDs.
2. **Run folders contain full artifacts** (and the parsed BRD) on local disk; treat `outputs/` as confidential and exclude it from version control (`.gitignore` provided).
3. **Regex redaction is not exhaustive** (names, addresses and free-text identifiers can slip through). A production deployment should add an NER-based PII detector (e.g. Presidio) in front of the parser.
4. **Injection detection is pattern-based**; novel phrasing can evade it. Defence in depth: the BRD is wrapped as untrusted data in prompts, outputs are checked for scope creep against the BRD, and nothing is acted on without the HITL gate.
5. Hashes are SHA-256 truncated to 16 hex chars for log readability; they identify content for correlation but are not a secrecy mechanism for low-entropy text.

## Responsible-AI notes

- **Accountability:** the EM approves or rejects every pack; the HITL decision and (optional) rating are logged.
- **Transparency:** every claim shows its requirement IDs and source chunks; the Critic's scores, issues and revision history are visible in the pack and dashboard.
- **No silent automation of people decisions:** the system recommends team composition by role, never by person.
- **Explainability:** each agent's decisions (template choice, pattern ranking, analogs, tool selection, routing) are logged in its `agent_execution` span, and with LangSmith on, the full graph run is traceable node by node.
- **Bias:** the knowledge base reflects our own past projects, so estimates inherit their biases (e.g. teams, domains or stacks we have over- or under-estimated). Mitigations: p80 from historical variance, analogs cited so the EM can challenge them, the Critic's effort-vs-analog check, and calibration against a human reviewer (`04 §4.6`). Bias and privacy can be monitored in production with the LLM-as-Judge pattern (`06 §6.6`).
- **Governance:** prompt, model, knowledge-base and threshold changes pass the pre-release gates (`06 §6.3`); ownership is in the RACI in `11_strategy_and_plan.md §11.5`.
