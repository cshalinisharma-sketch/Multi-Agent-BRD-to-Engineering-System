# BRD: Real-time Card Fraud Alert Platform

Classification: Confidential
Business owner: VP Fraud Risk

## Overview
Card fraud is detected by nightly batch rules, so fraudulent transactions continue for up to 24 hours before cards are blocked. Fraud losses were $14M last year. We will build a real-time platform that scores every card authorization, raises alerts to fraud analysts and notifies cardholders within seconds.

## Business Objectives
- Reduce fraud losses by 35% within 12 months.
- Reduce time from fraudulent transaction to card block from 24 hours to under 60 seconds.
- Keep false-positive alert rate under 3%.

## Scope
### In Scope
- Streaming ingestion of card authorization events.
- Real-time rule evaluation and model score consumption.
- Analyst alert console and cardholder notifications.
### Out of Scope
- Training new machine learning models (an existing model service is consumed).
- Chargeback handling.

## Functional Requirements
- FR-01 [Must] Ingest every card authorization event from the authorization switch in real time.
- FR-02 [Must] Enrich events with cardholder profile, device and merchant data.
- FR-03 [Must] Evaluate configurable fraud rules (velocity, geo-mismatch, high-risk merchant category) on each event.
- FR-04 [Must] Call the existing fraud model scoring service and combine the model score with rule results.
- FR-05 [Must] Raise an alert when the combined risk score exceeds a configurable threshold.
- FR-06 [Must] Fraud analysts review alerts in a console, confirm or dismiss fraud, and block the card.
- FR-07 [Must] Send SMS and push notifications to cardholders to confirm suspicious transactions.
- FR-08 [Must] Cardholder replies (yes or no) are ingested and automatically close or escalate the alert.
- FR-09 [Should] Rule authors create and back-test rules against the last 30 days of events before activating them.
- FR-10 [Should] Dashboard of alert volume, false-positive rate, and analyst handling time.
- FR-11 [Should] Analyst case notes and full alert history per card.
- FR-12 [Could] Automatic card block when the risk score exceeds a critical threshold.

## Non-Functional Requirements
- NFR-01 [Must] Sustain 4,000 authorization events per second at peak with p99 decision latency under 250 ms.
- NFR-02 [Must] 99.99% availability for the scoring path; no event loss.
- NFR-03 [Must] PCI DSS compliance: card numbers tokenised; no clear-text card data in logs or analytics.
- NFR-04 [Must] Every alert decision is explainable: store the rules fired and model score.
- NFR-05 [Must] Audit trail of analyst actions retained for 7 years.
- NFR-06 [Should] Scale horizontally to 3x peak during holiday season.

## Integrations
- INT-01 Authorization switch event stream.
- INT-02 Existing fraud model scoring service (REST, p99 40 ms).
- INT-03 SMS gateway and push notification service.
- INT-04 Card management system API to block cards.

## Constraints
- Target go-live within 24 weeks.
- Team of 10 engineers.
- Must run on the org AWS platform.

## Success Metrics
- Median time to card block under 60 seconds.
- False-positive rate under 3%.
