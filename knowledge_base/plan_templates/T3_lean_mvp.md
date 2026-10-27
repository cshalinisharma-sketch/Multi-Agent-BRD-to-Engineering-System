---
doc_id: T3
title: Lean MVP Plan Template
source_type: plan_template
domain: general
complexity: 1
applies_to: complexity 1-2, internal tools, at most 1 integration, team of 2-4
---

# Lean MVP Plan Template (T3)

## When to use
Use for simple internal tools or MVPs (complexity 1-2) with at most one integration and a team of 2-4 engineers. Three phases, two-week sprints, ship to a pilot group first.

## Phases
### Phase 1: Shape & Setup (20% of effort)
Deliverables: prioritised backlog, lightweight design doc, repository and CI/CD from the golden-path template, SSO configured.
Exit criteria: design doc reviewed by tech lead; pipeline deploys to stage.

### Phase 2: Build MVP (60% of effort)
Deliverables: Must-have requirements implemented and tested; pilot feedback form.
Exit criteria: all Must requirements accepted by product owner; no open high-severity bugs.

### Phase 3: Pilot & Launch (20% of effort)
Deliverables: pilot with one team, fixes from pilot feedback, general availability release, runbook.
Exit criteria: pilot satisfaction at least 4 of 5; production go-live approved by EM.

## Standard Milestones
- M1 Design reviewed and pipeline live
- M2 MVP feature complete
- M3 Pilot complete
- M4 General availability

## Risk Catalogue
- RISK: Scope grows during the build | Mitigation: freeze Must list at M1; new asks go to a later release via change request | Owner: Product Manager
- RISK: Low adoption after launch | Mitigation: pilot with a champion team; in-app feedback; adoption metric reviewed weekly | Owner: Product Manager
- RISK: Single engineer knowledge silo | Mitigation: code reviews by a second engineer; runbook before GA | Owner: Engineering Manager
