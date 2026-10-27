# BRD: Merchant Dispute Resolution Portal

Classification: Confidential
Business owner: Head of Merchant Operations
Version: 1.2

## 1. Overview
Merchants currently dispute card chargebacks by emailing evidence to our operations team, who re-key it into the card network portals. Average dispute handling time is 11 days and 18% of disputes are lost because evidence misses the card network deadline. We will build a self-service Merchant Dispute Resolution Portal that lets merchants view chargebacks, submit evidence and track outcomes, and gives operations analysts a case-management workspace.

## 2. Business Objectives
- Reduce average dispute handling time from 11 days to 4 days.
- Reduce disputes lost due to missed deadlines from 18% to under 5%.
- Cut operations analyst effort per dispute by 40%.

## 3. Scope
### In Scope
- Merchant-facing web portal for disputes.
- Operations analyst case-management workspace.
- Integration with the card network dispute APIs (Visa and Mastercard) and the internal payments ledger.

### Out of Scope
- Mobile app.
- Automated dispute decisioning using machine learning.
- Consumer (cardholder) facing features.

## 4. Functional Requirements
- FR-01 [Must] Merchants sign in and see a list of their open and closed chargebacks with amount, reason code, deadline and status.
- FR-02 [Must] Merchants upload evidence documents (PDF, JPG, PNG up to 20 MB each) against a chargeback before the network deadline.
- FR-03 [Must] The system submits the evidence package to the card network dispute API and records the submission receipt.
- FR-04 [Must] Chargeback notifications from the card networks are ingested and create or update dispute cases automatically.
- FR-05 [Must] Operations analysts work a case queue, assign cases, add internal notes and change case status.
- FR-06 [Must] Email notifications to merchants when a chargeback is created, 3 days before the evidence deadline, and when an outcome is received.
- FR-07 [Should] Analysts see a dashboard of disputes by status, reason code, win rate and deadline risk.
- FR-08 [Should] Merchants can accept liability for a chargeback with one click, closing the case.
- FR-09 [Must] Dispute outcomes (won or lost) are posted to the internal payments ledger to adjust merchant balances.
- FR-10 [Could] Bulk evidence upload for merchants with many disputes.

## 5. Non-Functional Requirements
- NFR-01 [Must] Portal pages load in under 2 seconds at p95 for 500 concurrent merchants.
- NFR-02 [Must] 99.9% monthly availability for the merchant portal.
- NFR-03 [Must] Merchant SSO via OAuth2; analysts via corporate SSO; role-based access so merchants only see their own disputes.
- NFR-04 [Must] Evidence documents and card data encrypted at rest and in transit; card numbers must never be stored in clear text.
- NFR-05 [Must] Full audit trail of every case action retained for 7 years.
- NFR-06 [Should] The system should be easy to use for merchants.

## 6. Integrations
- INT-01 Visa and Mastercard dispute APIs (REST, certification required).
- INT-02 Internal payments ledger API.
- INT-03 Corporate email service.

## 7. Constraints
- Target go-live within 20 weeks of kickoff.
- Team of 7 engineers available.
- Must run on the org AWS platform.

## 8. Stakeholders
- Head of Merchant Operations (sponsor), Merchant Operations analysts, Risk and Compliance, Payments Platform team.

## 9. Success Metrics
- Average dispute handling time of 4 days or less within 3 months of launch.
- Missed-deadline loss rate under 5%.

## 10. Open Questions
- Do we need to support Amex disputes in phase 1?
