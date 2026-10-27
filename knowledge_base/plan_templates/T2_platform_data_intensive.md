---
doc_id: T2
title: Platform & Data-Intensive Delivery Plan Template
source_type: plan_template
domain: general
complexity: 5
applies_to: complexity 4-5, real-time, high-throughput, event-driven or data platform work
---

# Platform & Data-Intensive Delivery Plan Template (T2)

## When to use
Use for complexity 4-5 systems: real-time or streaming, high throughput (more than 500 events or requests per second), many integrations, or strict availability targets. Adds an explicit PoC phase and a dedicated performance phase. Calibrated on 5 past platform projects; these ran 20-30% over plan on average, mostly from streaming-technology learning curves.

## Phases
### Phase 1: Discovery & Architecture (10% of effort)
Deliverables: event model and data contracts, architecture decision records, capacity model, integration inventory.
Exit criteria: architecture review board sign-off including capacity model; data contracts versioned.

### Phase 2: Technical PoC (15% of effort)
Deliverables: thin vertical slice of the riskiest path (usually ingestion or the highest-volume integration) under production-like load.
Exit criteria: PoC success criteria met or architecture revised; go/no-go recorded by EM.

### Phase 3: Platform Foundation (15% of effort)
Deliverables: streaming or messaging infrastructure, IaC, CI/CD, schema registry, observability with SLO dashboards.
Exit criteria: infrastructure provisioned in stage via IaC; synthetic traffic flows end to end.

### Phase 4: Core Build (35% of effort)
Deliverables: domain services and consumers implemented with idempotency, retries and dead-letter handling.
Exit criteria: all Must requirements accepted; replay and failure-injection tests pass.

### Phase 5: Performance & Resilience (15% of effort)
Deliverables: load tests at 2x expected peak, chaos and failover tests, security testing.
Exit criteria: throughput, latency and availability NFRs met at 2x peak; no critical findings.

### Phase 6: Rollout & Hypercare (10% of effort)
Deliverables: shadow-traffic or canary rollout, runbooks, on-call rota.
Exit criteria: canary metrics within SLO for 7 days; operations handover complete.

## Standard Milestones
- M1 Architecture and capacity model approved
- M2 PoC go/no-go decision
- M3 Platform ready in stage
- M4 Feature complete
- M5 NFRs verified at 2x peak
- M6 Production rollout complete

## Risk Catalogue
- RISK: Team unfamiliar with streaming technology (consumer tuning, partitioning) | Mitigation: PoC phase, external expert review, or managed service; add 20-30% schedule buffer | Owner: Engineering Manager
- RISK: Event loss or duplicate processing | Mitigation: at-least-once delivery with idempotent consumers, dead-letter queues, replay tooling | Owner: Tech Lead
- RISK: Throughput or latency NFRs not met | Mitigation: capacity model in Phase 1, load test PoC at production volume | Owner: Tech Lead
- RISK: Heterogeneous external data formats | Mitigation: canonical data model with per-source adapters and contract tests | Owner: Tech Lead
- RISK: Cloud cost overrun at scale | Mitigation: cost model per 1,000 events, budget alerts, right-sizing review at M5 | Owner: Engineering Manager
