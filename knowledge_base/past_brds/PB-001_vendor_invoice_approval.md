---
doc_id: PB-001
title: Vendor Invoice Approval Workflow
source_type: past_brd
domain: internal-tools
complexity: 3
pattern: modular-monolith
year: 2024
---

# Vendor Invoice Approval Workflow (Past BRD)

## Overview
Finance operations processed ~4,000 vendor invoices per month by email and spreadsheets. Approvals took 9 days on average and 6% of invoices were paid late, incurring penalties. The project replaced the manual flow with a web-based approval workflow integrated with the ERP.

## Functional Requirements
- FR-01 [Must] Accounts payable clerks upload invoices (PDF) and the system extracts vendor, amount, due date using OCR.
- FR-02 [Must] Invoices route to approvers based on amount thresholds and cost center (multi-level approval chain).
- FR-03 [Must] Approvers approve, reject or request changes with mandatory comments.
- FR-04 [Should] Email and in-app notifications for pending approvals and SLA breaches.
- FR-05 [Must] Approved invoices are posted to the ERP (SAP) for payment.
- FR-06 [Should] Dashboard of invoice ageing, approval cycle time and late-payment risk.

## Non-Functional Requirements
- NFR-01 [Must] SSO via corporate identity provider (OIDC); role-based access control.
- NFR-02 [Must] Complete audit trail of every approval decision retained for 7 years (SOX).
- NFR-03 [Should] Page load under 2 seconds at p95 for 300 concurrent users.

## Delivery Retrospective
Delivered as a modular monolith (Java/Spring Boot + PostgreSQL + React) by a team of 6 in 16 weeks against a 14-week plan (+14% variance). The ERP integration consumed 35% more effort than estimated because the SAP sandbox was available only in week 7. Lesson: secure integration sandbox access during discovery and treat ERP posting as the top PoC risk. OCR accuracy (92%) required a human-review queue that was not in the original scope; it was added as a change request with EM approval.
