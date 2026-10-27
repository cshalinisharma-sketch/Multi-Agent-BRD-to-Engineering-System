---
doc_id: PB-003
title: Clinic Appointment Booking
source_type: past_brd
domain: healthcare
complexity: 2
pattern: layered
year: 2023
---

# Clinic Appointment Booking (Past BRD)

## Overview
A network of 40 outpatient clinics booked appointments by phone. The project delivered online self-service booking, reminders and a front-desk schedule view.

## Functional Requirements
- FR-01 [Must] Patients search available slots by clinic, specialty and date and book an appointment.
- FR-02 [Must] Patients cancel or reschedule up to 24 hours before the appointment.
- FR-03 [Must] SMS and email reminders 48 and 2 hours before the appointment.
- FR-04 [Should] Front-desk staff view and override the daily schedule.

## Non-Functional Requirements
- NFR-01 [Must] HIPAA-compliant handling of patient data; encryption in transit and at rest.
- NFR-02 [Must] 99.9% availability during clinic hours.
- NFR-03 [Should] Booking flow completes in under 3 seconds at p95.

## Delivery Retrospective
Delivered as a layered web application (Python/FastAPI + PostgreSQL + React) by a team of 4 in 10 weeks against a 9-week plan (+11% variance). The SMS vendor contract was delayed by procurement, which pushed reminders to a fast-follow release. Lesson: start vendor procurement in the discovery phase; keep notification channels behind an adapter so vendors can be swapped.
