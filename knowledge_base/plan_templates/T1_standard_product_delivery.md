---
doc_id: T1
title: Standard Product Delivery Plan Template
source_type: plan_template
domain: general
complexity: 3
applies_to: complexity 2-4, customer or internal web products with 1-4 integrations
---

# Standard Product Delivery Plan Template (T1)

## When to use
Use for web products of moderate complexity (complexity 2-4) with a small number of integrations and a team of 4-8 engineers. Five phases; effort percentages are calibrated on 9 past projects.

## Phases
### Phase 1: Discovery & Design (15% of effort)
Deliverables: refined backlog with acceptance criteria, architecture decision records, UX flows, integration sandbox access confirmed.
Exit criteria: architecture review board sign-off; every Must requirement has acceptance criteria; integration credentials obtained.

### Phase 2: Foundation & Platform Setup (15% of effort)
Deliverables: repositories, CI/CD pipeline, environments (dev/stage/prod), IaC, authentication skeleton, observability baseline.
Exit criteria: a hello-world service deploys to stage through the pipeline with SSO login and dashboards.

### Phase 3: Core Build (40% of effort)
Deliverables: Must-have functional requirements implemented behind feature flags with unit and contract tests.
Exit criteria: all Must stories accepted by product owner in stage; test coverage at least 80% on domain logic.

### Phase 4: Integration & Hardening (20% of effort)
Deliverables: end-to-end integration with external systems, performance and security testing, NFR verification.
Exit criteria: NFR targets met in a performance test; no open critical or high security findings; UAT sign-off.

### Phase 5: Launch & Hypercare (10% of effort)
Deliverables: production rollout plan, runbooks, on-call rota, two weeks of hypercare.
Exit criteria: go-live checklist complete; error budget healthy for 14 days; handover to operations.

## Standard Milestones
- M1 Architecture approved (end of Phase 1)
- M2 Walking skeleton in stage (end of Phase 2)
- M3 Feature complete (end of Phase 3)
- M4 UAT sign-off and NFRs verified (end of Phase 4)
- M5 Production go-live (Phase 5)

## Risk Catalogue
- RISK: Third-party or ERP integration sandbox unavailable or late | Mitigation: request sandbox in week 1, build contract-test stubs, make integration the first PoC slice | Owner: Engineering Manager
- RISK: Requirements ambiguity causes rework | Mitigation: acceptance criteria for every Must requirement before build; weekly backlog refinement with product owner | Owner: Product Manager
- RISK: Performance NFRs missed late in the project | Mitigation: load-test the walking skeleton in Phase 2 and every sprint thereafter | Owner: Tech Lead
- RISK: Security review blocks launch | Mitigation: threat model in Phase 1, SAST/DAST in CI, early AppSec review | Owner: Security Champion
- RISK: Key-person dependency | Mitigation: pair programming and documented runbooks | Owner: Engineering Manager
