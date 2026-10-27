---
doc_id: PB-002
title: Real-time Shipment Tracking Platform
source_type: past_brd
domain: logistics
complexity: 5
pattern: event-driven
year: 2025
---

# Real-time Shipment Tracking Platform (Past BRD)

## Overview
Customers and support agents had no live visibility of parcel location. Carrier status arrived in nightly batch files. The platform ingests carrier events in real time, computes ETAs and pushes updates to customers and the support console.

## Functional Requirements
- FR-01 [Must] Ingest status events from 12 carrier APIs and webhooks, normalising them into a canonical shipment event.
- FR-02 [Must] Compute and update estimated time of arrival on every event.
- FR-03 [Must] Push notifications (SMS, email, app push) on delay or exception events.
- FR-04 [Must] Support console shows the full event timeline for a shipment within 2 seconds.
- FR-05 [Should] Exception queue for lost or damaged parcels with case assignment.

## Non-Functional Requirements
- NFR-01 [Must] Sustain 3,000 events per second with p99 end-to-end latency under 5 seconds.
- NFR-02 [Must] 99.95% availability for event ingestion; no event loss (at-least-once delivery, idempotent consumers).
- NFR-03 [Must] Customer contact data (PII) encrypted at rest and masked in logs.
- NFR-04 [Should] Horizontal scaling to 3x peak during holiday season.

## Delivery Retrospective
Built event-driven on Kafka (AWS MSK) with Java consumers, PostgreSQL for shipment state and Redis for hot reads. Team of 9 delivered in 26 weeks against a 20-week plan (+30% variance). Variance drivers: carrier API heterogeneity (normalisation took 2x estimate), and the team's low prior familiarity with Kafka consumer-group tuning. A 3-week PoC of the ingestion path de-risked throughput early and was cited as the best decision of the project. Lesson: when the team's familiarity with the core streaming technology is low, add 20-30% to schedule or pick a managed alternative.
