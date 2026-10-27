# 3. RAG Design

## 3.1 Knowledge base (self-built, synthetic but realistic)

| Source type | Files | Chunks | Content |
|---|---|---|---|
| `past_brd` | `knowledge_base/past_brds/*.md` | 12 | 3 past BRDs of varying complexity (invoice approval cx3, real-time shipment tracking cx5, clinic booking cx2) **with delivery retrospectives** (actual duration, variance drivers, lessons) |
| `plan_template` | `knowledge_base/plan_templates/*.md` | 23 | T1 standard product delivery (5 phases), T2 platform/data-intensive (6 phases incl. PoC and performance), T3 lean MVP (3 phases); each with effort shares, deliverables, exit criteria, milestones and a risk catalogue |
| `architecture_pattern` | `knowledge_base/patterns/architecture_pattern_library.md` | 9 | Modular monolith, microservices, event-driven, CQRS, serverless, API gateway + BFF, layered, batch/ETL, search-centric — each with signals, complexity, typical components and trade-offs |
| `project_timeline` | `knowledge_base/history/project_timelines.csv` | 12 | Past projects: domain, complexity, pattern, requirement count, integrations, team size, planned vs actual weeks, variance, notes |
| `standards` | `knowledge_base/standards/engineering_standards.md` | 8 | Approved stack, **team familiarity matrix**, CI/CD and coding standards, security & privacy, default SLOs, observability, ARB review criteria, retention |
| `tech_decision` | `knowledge_base/history/tech_decision_log.csv` | 14 | Past stack decisions with alternatives, rationale, outcome and a 1–5 outcome rating (incl. a failed Flink adoption) |
| **Total** | | **78** | |

The content was written so that retrieval has to discriminate: e.g. two streaming references (PB-002 succeeded with a PoC; TD-05 Flink failed on familiarity), two search-adjacent sources (P-12 and the search pattern), and generic vs specific risks.

## 3.2 Chunking strategy (per source type)

| Source | Strategy | Why |
|---|---|---|
| Narrative markdown (past BRDs, templates, standards) | Split on `##`/`###` headings; each chunk = **heading path + section body** (e.g. `Platform Template > Phases > Phase 2: Technical PoC`). Sections > 1,400 chars split on paragraph boundaries with one-paragraph overlap. | BRD and template sections are self-contained semantic units ("Non-Functional Requirements", "Phase 3"). The heading path gives the embedder context a bare paragraph lacks, and lets agents parse structured lines (phase %, exit criteria, risk catalogue). |
| Architecture patterns | **One chunk per pattern**, never split. | Signals, complexity and trade-offs must stay together; splitting would let a query match "signals" without the trade-offs that justify the choice. |
| CSV tables (timelines, decision log) | **One chunk per row**, rendered as a sentence, with every column also stored as typed metadata. | Rows are the natural unit for analog search; typed metadata enables filters (`complexity ∈ {3,4,5}`, `category = messaging`) and lets the Schedule Estimator compute from numbers rather than text. |

Chunk IDs are stable and human-readable (`pattern:event-driven`, `timeline:P-07`, `tmpl:T2#3`, `std:STD#2`), so citations in artifacts are meaningful to an EM.

## 3.3 Metadata schema

| Field | Present on | Used for |
|---|---|---|
| `source_type` | all | per-agent source filters |
| `doc_id`, `title`, `section` | all | traceability; loading a whole template (`where doc_id = T2`) |
| `domain`, `complexity`, `pattern` | past BRDs, timelines, patterns | analog selection; pattern ranking |
| `req_count`, `integrations`, `team_size`, `planned_weeks`, `actual_weeks`, `variance_pct` | timelines | effort-per-requirement and p80 maths |
| `category`, `decision`, `outcome_rating`, `project_id` | decision log | stack risk scoring (`category` filter chosen by the agent) |
| `pattern_id` | patterns | pattern choice + citation |

## 3.4 Embeddings

**Default: local LSA hybrid.** TF-IDF (unigrams + bigrams, sublinear TF, English stop words) → Truncated SVD to 77 dims (LSA), L2-normalised. In the tuned profile the dense cosine is fused 50/50 with the sparse TF-IDF cosine.

- *Cost/quality reasoning:* the corpus is 78 chunks of domain-specific engineering text. LSA captures enough co-occurrence semantics ("real-time" ↔ "events per second" ↔ "streaming") while the sparse half keeps exact-token precision for IDs and technology names (`Kafka`, `PCI`, `OAuth2`) where neural embeddings often blur. It costs $0, is deterministic (important for reproducible evals) and needs no network.
- *Upgrade path:* `OpenAIEmbedder` (`text-embedding-3-small`, ~$0.02 / 1M tokens) is included for larger or more varied corpora; keep the hybrid sparse component.

## 3.5 Vector store

`NumpyVectorStore` (in-process cosine similarity + metadata filters supporting equality and `$in`, persisted to `.index/`). Its `add` / `query(where=…)` interface mirrors Chroma's, so swapping to Chroma/Qdrant/pgvector is a one-class change. Rationale: < 1k chunks, zero infrastructure, fully reproducible. Index rebuilds automatically when any knowledge-base file is newer than the index.

## 3.6 Retrieval parameters

| Parameter | `baseline` profile | `tuned` profile | Why tuned |
|---|---|---|---|
| `top_k` | 2 | 5 (agents override where needed, e.g. 9 for patterns, 20 to load a full template) | Plans and architectures need several complementary sources |
| Metadata filters | off | per-agent `source_type` allow-lists (below) + agent-specific filters | Stops, e.g., a timeline row crowding out a pattern for the Architect |
| Similarity | dense only | hybrid dense + sparse | Exact tech/ID terms matter |
| `sim_threshold` (keep chunk) | 0.05 | 0.08 | Drop noise |
| `cite_threshold` (attach citation) | 0.20 | 0.12 | Hybrid scores are on a different scale; tuned on the eval set |

Per-agent source filters (tuned): Plan → templates, past BRDs, timelines, standards · Schedule → timelines, templates, past BRDs · Architect → patterns, standards, past BRDs, decision log · PoC → past BRDs, templates, patterns, standards · Tech stack → decision log, standards, past BRDs.

**Pattern library exception:** the Architect scores *every* pattern (threshold 0) and ranks them with retrieval score + explicit signal matching + hard constraints (on-prem excludes serverless; a single small team penalises microservices). An early bug showed why: with a threshold, only 2 of 9 patterns survived and a dispute portal was classified as "search-centric".

## 3.7 Citations and provenance

1. Each agent retrieves; every hit is recorded in a **per-run provenance registry** (agent → chunk ids).
2. A claim gets a citation if its similarity to a retrieved chunk ≥ `cite_threshold` (max 2–3 per claim).
3. On Critic feedback (`uncited_claims`, `invalid_grounding`), the agent runs a **targeted retrieval with the claim text as the query**; if nothing relevant is found the claim is explicitly marked as an assumption rather than given a weak citation.
4. The Critic's hallucination check rejects citations to chunks the citing agent never retrieved, requirement IDs not in the BRD, and claims whose cited source barely relates to the text.
5. The Markdown pack ends with a **Sources** list resolving every cited chunk id to its document and section.

## 3.8 Effect of the tuning (from `eval_results/eval_report.md`)

| Mean over 6 completed eval BRDs | baseline | tuned |
|---|---|---|
| Claims cited at round 0 | 82.5% | 93.3% |
| Critic issues at round 0 | 3.67 | 2.0 |
| RED artifacts at round 0 | 4 of 6 runs RED | 0 of 6 runs RED |

Both profiles converge after one revision round because the Critic's targeted re-retrieval repairs grounding — the tuned profile simply gets there with less rework.
