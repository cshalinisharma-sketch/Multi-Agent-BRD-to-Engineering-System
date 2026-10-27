---
doc_id: APL
title: Architecture Pattern Library
source_type: architecture_pattern
domain: general
---

# Architecture Pattern Library

## Modular Monolith
pattern_id: modular-monolith
Complexity: 2
Signals: workflow, approval, crud, forms, internal tool, small team, single database, moderate scale, portal, case management
When to use: one deployable with strictly separated domain modules; team of 3-8; fewer than 1,000 requests per second; strong transactional consistency needed.
Typical components: web frontend, application service with domain modules, relational database, background job worker, notification adapter, auth integration
Trade-offs: simplest to build, test and operate; one deploy pipeline. Weaker independent scaling and fault isolation; modules must be policed to avoid a big ball of mud. Can later be split along module boundaries (strangler).

## Microservices
pattern_id: microservices
Complexity: 4
Signals: multiple teams, independent deployment, many bounded contexts, different scaling profiles, polyglot, large organisation
When to use: several teams own separate bounded contexts and need independent release cadence and scaling.
Typical components: API gateway, multiple domain services each with own datastore, service discovery, message broker, centralized observability, auth service
Trade-offs: independent scaling and deployment; fault isolation. High operational overhead (distributed tracing, network failures, data consistency via sagas). Usually overkill for a single team.

## Event-Driven Architecture
pattern_id: event-driven
Complexity: 5
Signals: real-time, streaming, events, high throughput, events per second, asynchronous, alerts, notifications at scale, fan-out, decoupled consumers, ingestion
When to use: producers and consumers must be decoupled; high-volume asynchronous processing; real-time reactions to events; multiple downstream consumers of the same event.
Typical components: event broker (Kafka or managed equivalent), producers/ingestion adapters, stream processors or consumers, schema registry, dead-letter queue, state store, notification service
Trade-offs: excellent throughput and decoupling; natural audit log of events. Eventual consistency, harder debugging, requires idempotent consumers and schema governance; steep learning curve for teams new to streaming.

## CQRS (Command Query Responsibility Segregation)
pattern_id: cqrs
Complexity: 4
Signals: read-heavy, reporting, dashboards, analytics, different read and write models, search, audit history
When to use: read and write workloads differ sharply; complex queries or dashboards must not slow down transactional writes.
Typical components: command service, write database, projection builder, read store or search index, query API
Trade-offs: optimised reads and writes independently. Extra moving parts, eventual consistency between write and read models, projection rebuild tooling needed.

## Serverless (Function-as-a-Service)
pattern_id: serverless
Complexity: 3
Signals: spiky traffic, low steady volume, event triggers, scheduled jobs, small team, pay per use, file processing
When to use: unpredictable or low-volume workloads; event-triggered processing; minimal ops capacity.
Typical components: API gateway, functions, managed queue, managed NoSQL or relational database, object storage
Trade-offs: no servers to manage; cost scales to zero. Cold starts, vendor lock-in, execution time limits, harder local testing; not allowed for on-premises deployments.

## API Gateway with Backend-for-Frontend (BFF)
pattern_id: api-gateway-bff
Complexity: 3
Signals: multiple client channels, mobile and web, external partners, third-party integrations, rate limiting, partner api
When to use: several client types or external partners consume the same backend capabilities with different shapes and security needs.
Typical components: API gateway, BFF per channel, backend services, rate limiter, partner auth (OAuth2 client credentials)
Trade-offs: tailored APIs per client and central security policies. Extra hop and duplication across BFFs.

## Layered (N-tier)
pattern_id: layered
Complexity: 2
Signals: simple, booking, crud, small scope, single team, standard web application, low integration
When to use: straightforward request/response applications with limited integrations.
Typical components: web frontend, REST API layer, service layer, relational database
Trade-offs: well understood and quick to deliver. Can become rigid; layers leak if domain logic grows.

## Batch / ETL Pipeline
pattern_id: batch-etl
Complexity: 3
Signals: nightly, batch, reconciliation, reports, data warehouse, files, bulk import, settlement
When to use: large periodic data movements and transformations where latency of hours is acceptable.
Typical components: scheduler/orchestrator, extract jobs, transformation jobs, data warehouse, data-quality checks
Trade-offs: simple and cost-efficient for periodic loads. Not suitable for real-time needs; failures surface late without data-quality checks.

## Search-Centric (Index + Retrieval)
pattern_id: search-centric
Complexity: 3
Signals: search, knowledge base, documents, full-text, semantic search, retrieval, indexing, enterprise search
When to use: the core user value is finding information across many documents or records.
Typical components: ingestion connectors, indexing pipeline, search index (OpenSearch), query API, access-control filter, web frontend
Trade-offs: fast relevant retrieval. Index freshness and document-level permissions are the hard parts; relevance tuning needs evaluation data.
