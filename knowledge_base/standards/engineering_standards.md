---
doc_id: STD
title: Org Engineering Standards
source_type: standards
domain: general
version: 2026.1
---

# Org Engineering Standards (v2026.1)

## Approved Technology Stack
Backend: Java 21 with Spring Boot 3 (default) or Python 3.12 with FastAPI (data and ML-adjacent services). Go is permitted only with architecture review board approval.
Frontend: React 18 with TypeScript and the org design system.
Databases: PostgreSQL 16 on Amazon RDS (default OLTP); Amazon DynamoDB only for key-value access patterns at very high scale.
Caching: Redis (Amazon ElastiCache).
Messaging and streaming: Amazon SQS/SNS for simple queues; Apache Kafka on AWS MSK for event streaming above 500 events per second or when replay is required. Kafka Streams is the approved stream-processing library; Flink requires ARB approval.
Search: Amazon OpenSearch.
Cloud and infrastructure: AWS (primary). Containers on Amazon EKS or ECS Fargate. Infrastructure as Code with Terraform. AWS Lambda for event-triggered or spiky workloads.
On-premises: only by CISO exception; serverless and managed AWS services are unavailable on-premises.

## Team Familiarity Matrix
Scores are 1 (no experience) to 5 (deep expertise), surveyed across delivery teams in 2026.
Java/Spring Boot 5; Python/FastAPI 4; React/TypeScript 5; PostgreSQL 5; Redis 4; SQS/SNS 4; Kafka/MSK 3; Kafka Streams 3; Flink 1; DynamoDB 2; OpenSearch 3; AWS Lambda 3; EKS 3; ECS Fargate 4; Terraform 4; Go 1.

## CI/CD and Coding Standards
All services use the golden-path repository template with GitHub Actions: build, unit tests, SAST (Semgrep), dependency scanning, container scanning, and deployment to dev, stage and prod with manual approval for prod. Trunk-based development with short-lived branches; every change reviewed by at least one other engineer. Minimum 80% unit-test coverage on domain logic; contract tests for every external integration. Feature flags for incomplete features.

## Security and Privacy Standards
Authentication via corporate SSO (OIDC) for employees and OAuth2 for partners; RBAC enforced in the service layer. PII and payment data encrypted at rest (KMS) and in transit (TLS 1.2+); PII masked in logs. Secrets in AWS Secrets Manager only. Applications handling card data follow PCI DSS scope-minimisation (tokenise card numbers via the payments vault). Threat model required in the design phase; AppSec review before production. Target OWASP ASVS Level 2.

## Default Service Level Objectives
When a BRD does not specify NFRs, use these defaults and record them as assumptions: API latency p95 under 300 ms and p99 under 800 ms; availability 99.9% monthly for customer-facing services and 99.5% for internal tools; RPO 15 minutes and RTO 1 hour; audit logs retained 7 years for financial records and 1 year otherwise.

## Observability Standards
OpenTelemetry tracing and metrics on every service; dashboards and alerts in Grafana; structured JSON logs without PII; SLO burn-rate alerts paged to the owning team.

## Architecture Review Criteria
The architecture review board (ARB) checks: (1) every Must requirement maps to a component; (2) NFRs map to concrete mechanisms; (3) the chosen pattern is justified against at least one alternative; (4) data classification and PII flows are documented; (5) failure modes and fallbacks are documented for each external integration; (6) the stack is on the approved list or has an exception; (7) cost estimate for expected volume.

## Data Retention and Compliance
Financial transaction and dispute records: retain 7 years. Customer communications: retain 2 years. Access logs: 1 year. Data subject deletion requests honoured within 30 days except where legal retention applies.
