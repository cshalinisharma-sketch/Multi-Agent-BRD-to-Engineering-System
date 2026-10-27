# 11. Strategy, Plan & Leadership Asks

*Capstone Week 1, Exercise 2 (strategy, forward-looking plan, leadership asks) and the Week 1 leadership and readiness concepts. Figures marked "proposed" are planning estimates to confirm with finance and the sponsor.*

## 11.1 Business case

| | Today | With BRD → Engineering |
|---|---|---|
| Time from BRD to first engineering plan | 2–5 days of EM + tech-lead time | < 5 minutes to a reviewed draft, then EM review |
| Consistency | Depends on the author | Same templates, rubric and standards every time |
| When problems surface | Sprint planning or later | At intake: contradictions, missing NFRs and infeasible deadlines are escalated automatically |
| Traceability | Rarely | Every claim → BRD requirement + knowledge-base source |

Organisational priorities served: faster planning (cost), fewer late-discovered scope and schedule surprises (delivery risk), consistent quality across teams.

## 11.2 Goals and success criteria

| Goal | Success criterion | Measured by |
|---|---|---|
| Decision-ready drafts | ≥ 80% of packs approved at the HITL gate, mean EM rating ≥ 4 / 5 | `hitl` records |
| Grounded output | ≥ 75% of claims cited per artifact; 0 cross-agent contradictions delivered | Critic |
| Early risk detection | 100% of BRD contradictions and infeasible deadlines escalated before planning | escalation tickets vs eval expectations |
| Cost and speed | < 5 min p95 per BRD, cost per BRD within budget | per-agent latency and token logs |

Full criteria, failure modes and pre-release gates: `06_operationalization.md`.

## 11.3 Forward-looking plan

| Milestone | Duration | Exit criteria |
|---|---|---|
| M0 · Prototype (done) | — | 7 agents on LangGraph, offline engine, RAG, Critic loop, HITL gate, eval suite 44/44, 9 tests |
| M1 · Live LLM validation | 2 weeks | Eval suite run with OpenAI; fallback rate < 5%; groundedness and badges no worse than offline; cost per BRD measured |
| M2 · Pilot in shadow mode | 4 weeks | 3 EMs run it next to their normal process on real (approved) BRDs; ≥ 10 packs rated; top 3 failure patterns fixed |
| M3 · Staged rollout | 4 weeks | One org (≈ 10 EMs); approval ≥ 80%, rating ≥ 4; monitoring and alerts live; real Jira integration |
| M4 · Scale | ongoing | 50+ BRDs / week on queue + workers with a managed vector DB (`01_architecture.md §1.7`); approved packs fed back into the knowledge base |

## 11.4 Leadership asks (proposed)

| Ask | Proposed | Why |
|---|---|---|
| Headcount | 1 engineer full time + 0.5 platform/MLOps engineer for M1–M3 (≈ 10 weeks) | Live LLM integration, monitoring, Jira and SSO integration, hardening |
| Knowledge owners | 0.25 FTE across PMO and architecture | Own and curate past BRDs, templates, patterns, timelines and the decision log |
| Pilot users | 3 Engineering Managers, ~2 hours / week for 4 weeks | Shadow-mode comparison and ratings |
| LLM budget | ≈ $100 / month during pilot (≈ $1 per BRD estimated from ~35 calls per run at indicative prices in `src/config.py`) | Model API usage; to be re-measured in M1 |
| Tooling | LangSmith (or Langfuse) workspace; existing hosting | Tracing, monitoring, online evaluation |
| Approvals | Security / legal review of the LLM provider's data terms | Required before any real BRD leaves the network |

## 11.5 Stakeholder matrix (power × interest)

| Quadrant | Stakeholders | Engagement |
|---|---|---|
| Manage closely (high power, high interest) | VP Engineering (sponsor), Director of PMO | Milestone reviews, approve leadership asks, own adoption targets |
| Keep satisfied (high power, lower interest) | Security, Legal / Privacy, Finance | Data-boundary review before M2, monthly cost report |
| Keep informed (lower power, high interest) | Engineering Managers, tech leads, product managers | Pilot, demos, feedback channel, release notes |
| Monitor (low power, low interest) | Wider engineering org | Internal post at rollout |

**Governance (RACI for agent behaviour).** Responsible: platform engineer (prompts, models, thresholds). Accountable: sponsoring Director. Consulted: Security, knowledge owners. Informed: pilot EMs. Any change to prompts, models, knowledge base or thresholds passes the pre-release gates in `06 §6.3`.

## 11.6 Organisational and technical readiness

| Area | Status | Next step |
|---|---|---|
| Business alignment | Tied to planning speed and delivery risk | Confirm KPIs with the sponsor in M1 |
| Systems and data | Synthetic knowledge base; mock Jira; MCP server exposes parsing and search | Curate real past BRDs and timelines with owners; real Jira API |
| Talent and skills | Agents, prompts and evals built in Python with LangGraph / LangChain | Brown-bag on the Critic rubric and prompt template for pilot EMs |
| Culture and adoption | Draft-plus-approval model keeps EMs in control | Shadow mode before replacing any step |
| Data quality and governance | Versioned index (`kb_version`), validated inputs, hashed logs | Owner and freshness SLA per source type (`06 §6.6`) |
| Explainability | Citations, Critic scores, decisions and tool choices logged per agent | Show decision traces in LangSmith |
| Security and privacy | Opt-in data boundary, PII and secret redaction, injection quarantine | NER-based PII detection, zero-retention provider terms |
| Scalability | Offline < 1 s per BRD; LLM target < 5 min | Queue + workers, managed vector DB (M4) |

## 11.7 Managing expectations, ethics and cost

- **Hype vs reality.** The system drafts and flags; it does not decide. Badges and the approval gate make that visible to every stakeholder.
- **Ethics.** Recommends roles, never named people; contradictions are escalated, not resolved silently; every claim is traceable. See `05_guardrails_safety.md`.
- **Cost drivers.** Calls per run (~35 with revisions), prompt size (BRD + retrieved chunks + schema), model tier. Controls: model routing (small vs large), capped retrieval (top-k 5, 900 characters per chunk), revision cap of 2, opt-in response cache.
