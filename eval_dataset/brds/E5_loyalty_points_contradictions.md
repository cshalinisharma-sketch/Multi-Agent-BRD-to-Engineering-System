# BRD: Store Loyalty Points Program

Business owner: Head of Retail Marketing

## Overview
We will launch a loyalty points program across 120 stores and the e-commerce site. Customers earn points on purchases and redeem them for discounts.

## Business Objectives
- Increase repeat purchase rate by 10% in 6 months.
- Enrol 200,000 members in the first quarter.

## Scope
### In Scope
- Member enrolment, points earning and redemption in stores and online.
- Marketing campaign targeting of members.
### Out of Scope
- Partner (coalition) loyalty programs.
- Mobile app.

## Functional Requirements
- FR-01 [Must] Customers enrol in the program online and in store with email and phone.
- FR-02 [Must] Points are earned on every purchase from the point-of-sale and e-commerce order events.
- FR-03 [Must] Customers redeem points for discounts at checkout in store and online.
- FR-04 [Must] Members see their points balance and history in the website.
- FR-05 [Must] Marketing creates campaigns that award bonus points to member segments.
- FR-06 [Must] Points expire after 12 months of inactivity.
- FR-07 [Must] Store staff can adjust points for customer service cases.
- FR-08 [Must] Members receive a mobile app push notification when points are about to expire.
- FR-09 [Must] Fraud controls prevent points from being earned on returned purchases.

## Non-Functional Requirements
- NFR-01 [Must] The system must run entirely on-premises in our data centre; no public cloud.
- NFR-02 [Must] Points earning is processed by AWS Lambda functions triggered by order events.
- NFR-03 [Must] Points balance lookups at checkout respond in under 200 ms at p95.
- NFR-04 [Must] Member transaction history is retained for 2 years.
- NFR-05 [Must] Member transaction history is retained for 7 years for audit.

## Integrations
- INT-01 Point-of-sale system in 120 stores.
- INT-02 E-commerce order service.
- INT-03 Marketing campaign tool.

## Constraints
- Go-live within 6 weeks.
- Team of 4 engineers.
