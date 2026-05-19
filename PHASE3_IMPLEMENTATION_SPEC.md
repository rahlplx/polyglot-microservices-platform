# Phase 3: Implementation & Vibe Coding Specification

> **Status:** IN PROGRESS
> **Gate:** Code implemented, /qa pass completed, /review approved
> **Design prerequisite:** Phase 2 COMPLETE (10/10 PASS)
> **Canonical spec:** `/home/z/my-project/SPECIFICATION.md`
> **Design spec:** `/home/z/my-project/PHASE2_DESIGN_SPEC.md`

---

## Phase 3 Overview

Phase 3 transforms the Phase 2 design artifacts into executable, testable code across the polyglot service topology. The core mission is to implement the 9-service architecture (Gateway, Identity, Catalog, Order, Payment, Notification, Analytics, CDC Relay, Schema Registry) following hexagonal architecture principles, contract-driven communication, SPIFFE/SPIRE identity, OTel observability, and the AI/ML Intelligence Layer patterns defined in the design-variants-analysis.md. Every implementation must pass /qa and /review before merging to develop.

### Core Implementation Principles

1. **Boil the Lake** — Do the complete thing, not the 90% shortcut. Every service gets full port/adapter scaffolding, not stubs.
2. **Contract-First** — Protobuf schemas and OpenAPI specs are written BEFORE service code. Generated stubs are the source of truth.
3. **Hexagonal Enforcement** — Domain core has ZERO external dependencies. All I/O flows through ports and adapters.
4. **Zero Trust by Default** — Every service integrates SPIFFE Workload API from Day 1. No plaintext communication.
5. **Observability Native** — Every service ships with OTel instrumentation. No retrofitting.
6. **ACL Everywhere** — Every external system communication routes through an Anti-Corruption Layer sidecar.

---

## Spec-Driven Requirements

| ID | Requirement | Verification | Status |
|----|-------------|-------------|--------|
| 3.1 | Code follows design specification | Implementation matches Phase 2 design | PENDING |
| 3.2 | All spec items implemented (Boil the Lake) | No 90% shortcuts, complete implementation | PENDING |
| 3.3 | Type system enforced (TypeScript where applicable) | No `any` types without justification | PENDING |
| 3.4 | Error handling comprehensive | All error paths have handlers | PENDING |
| 3.5 | /qa pass completed with zero open bugs | /qa -> fix -> /qa -> zero bugs | PENDING |
| 3.6 | /review approved (code quality) | /review passes without blocking issues | PENDING |
| 3.7 | Token efficiency maintained | No unnecessary file reads, lazy skill loading | PENDING |
| 3.8 | Worklog updated after each subtask | Every agent appends to worklog.md | PENDING |
| 3.9 | Security scan passed (if applicable) | /cso audit completed for web-facing code | PENDING |
| 3.10 | Performance benchmarks met | /benchmark shows no regression | PENDING |

---

## 3A: Implementation Tracks (6 Parallel Tracks)

### Track 1: Schema & Contract Foundation

**Owner:** Schema Agent
**Spec Items:** 3.1, 3.2 (partial)
**Branch Pattern:** `schema/P3-<service>-<version>`

| Task | Service | Language | Deliverable |
|------|---------|----------|-------------|
| Define common types (Money, Address, Events, Errors) | common | Protobuf | `schemas/proto/common/v1/*.proto` |
| Define Gateway proto + OpenAPI | gateway | Protobuf | `schemas/proto/gateway/v1/*.proto` |
| Define Identity proto (SPIFFE workload API) | identity | Protobuf | `schemas/proto/identity/v1/*.proto` |
| Define Catalog proto + OpenAPI | catalog | Protobuf | `schemas/proto/catalog/v1/*.proto` |
| Define Order proto (saga events) | order | Protobuf | `schemas/proto/order/v1/*.proto` |
| Define Payment proto (circuit breaker state) | payment | Protobuf | `schemas/proto/payment/v1/*.proto` |
| Define Notification proto | notification | Protobuf | `schemas/proto/notification/v1/*.proto` |
| Define Analytics proto | analytics | Protobuf | `schemas/proto/analytics/v1/*.proto` |
| Generate code stubs for all 5 languages | all | Multi | `schemas/generated/{go,java,python,rust,typescript}/` |
| Generate OpenAPI 3.1 specs from proto | gateway, catalog, order, payment | YAML | `schemas/openapi/*/v1.yaml` |
| Define Pact contracts for consumer pairs | all | JSON | `schemas/contracts/*/` |
| Configure Buf breaking change detection in CI | infra | YAML | `.github/workflows/schema-ci.yml` |

### Track 2: Go Services (Gateway, Payment, Schema Registry)

**Owner:** Go Agent
**Spec Items:** 3.1, 3.2, 3.4
**Branch Pattern:** `feature/P3-3.1-<service>-<desc>`

#### Gateway Service (Go)

| Task | Deliverable | Hex Layer |
|------|-------------|-----------|
| Domain core: routing use cases | `domain/services/router.go` | domain |
| Inbound port: RouteRequest, HealthCheck | `domain/ports/inbound/routing.go` | domain |
| Outbound port: ServiceDiscovery, RateLimiter | `domain/ports/outbound/discovery.go` | domain |
| gRPC adapter (from generated stubs) | `adapters/inbound/grpc/` | adapter |
| REST adapter (OpenAPI-generated) | `adapters/inbound/rest/` | adapter |
| Service discovery adapter (K8s API) | `adapters/outbound/discovery/` | adapter |
| Rate limiter adapter (Redis/token bucket) | `adapters/outbound/ratelimit/` | adapter |
| OTel observability adapter | `adapters/outbound/observability/` | adapter |
| SPIFFE Workload API integration | `infrastructure/identity/spiffe.go` | infra |
| DI wiring + server setup | `infrastructure/di/`, `infrastructure/server/` | infra |
| Dockerfile (multi-stage OCI) | `Dockerfile` | build |
| Makefile (build, test, lint, generate) | `Makefile` | build |
| Unit + contract tests | `tests/` | test |

#### Payment Service (Go)

| Task | Deliverable | Hex Layer |
|------|-------------|-----------|
| Domain core: payment processing, refund | `domain/services/processor.go` | domain |
| Inbound port: ProcessPayment, RefundPayment | `domain/ports/inbound/payment.go` | domain |
| Outbound port: PaymentGateway, TransactionLog | `domain/ports/outbound/gateway.go` | domain |
| gRPC adapter | `adapters/inbound/grpc/` | adapter |
| Payment gateway adapter (behind ACL) | `adapters/outbound/external/` | adapter |
| ACL sidecar integration | `adapters/outbound/acl/` | adapter |
| Circuit breaker (go-resilience) | `adapters/outbound/resilience/` | adapter |
| OTel observability adapter | `adapters/outbound/observability/` | adapter |
| SPIFFE integration | `infrastructure/identity/spiffe.go` | infra |
| Dockerfile + Makefile | `Dockerfile`, `Makefile` | build |
| Unit + contract + property tests | `tests/` | test |

#### Schema Registry Service (Go)

| Task | Deliverable | Hex Layer |
|------|-------------|-----------|
| Domain core: schema validation, compilation | `domain/services/registry.go` | domain |
| Inbound port: RegisterSchema, ValidateSchema, GetSchema | `domain/ports/inbound/registry.go` | domain |
| Outbound port: SchemaStore, CompilationEngine | `domain/ports/outbound/store.go` | domain |
| gRPC + REST adapters | `adapters/inbound/` | adapter |
| Buf compilation adapter | `adapters/outbound/compilation/` | adapter |
| Schema storage adapter (PostgreSQL) | `adapters/outbound/persistence/` | adapter |
| OTel + SPIFFE integration | `adapters/outbound/`, `infrastructure/` | adapter/infra |
| Dockerfile + Makefile | `Dockerfile`, `Makefile` | build |
| Unit + contract tests | `tests/` | test |

### Track 3: Rust Service (Identity)

**Owner:** Rust Agent
**Spec Items:** 3.1, 3.2, 3.4, 3.9
**Branch Pattern:** `feature/P3-3.1-identity-<desc>`

| Task | Deliverable | Hex Layer |
|------|-------------|-----------|
| Domain core: workload attestation, SVID management | `src/domain/services/` | domain |
| Inbound port: AttestWorkload, IssueSVID, RevokeSVID | `src/domain/ports/inbound/` | domain |
| Outbound port: CertificateAuthority, WorkloadStore | `src/domain/ports/outbound/` | domain |
| gRPC adapter (tonic) | `src/adapters/inbound/grpc/` | adapter |
| SPIRE Agent client adapter | `src/adapters/outbound/spire/` | adapter |
| Certificate storage adapter | `src/adapters/outbound/persistence/` | adapter |
| mTLS certificate rotation handler | `src/adapters/outbound/rotation/` | adapter |
| OTel adapter (opentelemetry-rust) | `src/adapters/outbound/observability/` | adapter |
| Cryptographic operations (ring/openssl) | `src/infrastructure/crypto/` | infra |
| Dockerfile (multi-stage, musl static) | `Dockerfile` | build |
| Cargo.toml with workspace | `Cargo.toml` | build |
| Unit + property tests (proptest) | `tests/` | test |

### Track 4: Node.js/TypeScript Service (Catalog)

**Owner:** Node Agent
**Spec Items:** 3.1, 3.2, 3.3, 3.4
**Branch Pattern:** `feature/P3-3.1-catalog-<desc>`

| Task | Deliverable | Hex Layer |
|------|-------------|-----------|
| Domain core: product/inventory CRUD, search | `src/domain/services/` | domain |
| Inbound port: CreateProduct, SearchCatalog, DeleteProduct | `src/domain/ports/inbound/` | domain |
| Outbound port: ProductRepository, SearchIndex | `src/domain/ports/outbound/` | domain |
| gRPC adapter (@grpc/grpc-js) | `src/adapters/inbound/grpc/` | adapter |
| REST adapter (Express/Fastify + OpenAPI) | `src/adapters/inbound/rest/` | adapter |
| PostgreSQL adapter (pg/typeorm) | `src/adapters/outbound/persistence/` | adapter |
| Elasticsearch/Meilisearch adapter | `src/adapters/outbound/search/` | adapter |
| OTel adapter (@opentelemetry/api) | `src/adapters/outbound/observability/` | adapter |
| SPIFFE integration (spiffe-sdk) | `src/infrastructure/identity/` | infra |
| Dockerfile + package.json + tsconfig.json | build files | build |
| Unit + contract tests (Jest + Pact) | `tests/` | test |

### Track 5: Java/Kotlin Service (Order, CDC Relay)

**Owner:** JVM Agent
**Spec Items:** 3.1, 3.2, 3.4
**Branch Pattern:** `feature/P3-3.1-<service>-<desc>`

#### Order Service (Java/Kotlin)

| Task | Deliverable | Hex Layer |
|------|-------------|-----------|
| Domain core: order lifecycle, saga orchestration | `src/main/kotlin/domain/services/` | domain |
| Inbound port: CreateOrder, CompleteOrder, ListOrders | `src/main/kotlin/domain/ports/inbound/` | domain |
| Outbound port: OrderRepository, EventPublisher, NotificationClient | `src/main/kotlin/domain/ports/outbound/` | domain |
| gRPC adapter (generated from proto) | `src/main/kotlin/adapters/inbound/grpc/` | adapter |
| Kafka event publisher adapter | `src/main/kotlin/adapters/outbound/messaging/` | adapter |
| PostgreSQL adapter (jOOK/Hibernate) | `src/main/kotlin/adapters/outbound/persistence/` | adapter |
| Transactional Outbox writer | `src/main/kotlin/adapters/outbound/outbox/` | adapter |
| Saga orchestrator (choreography + orchestration) | `src/main/kotlin/domain/saga/` | domain |
| Resilience4j circuit breaker | `src/main/kotlin/adapters/outbound/resilience/` | adapter |
| OTel + SPIFFE integration | `src/main/kotlin/adapters/outbound/`, `src/main/kotlin/infrastructure/` | adapter/infra |
| Dockerfile + build.gradle.kts | build files | build |
| Unit + contract + property tests (JUnit5 + Pact + jqwik) | `src/test/` | test |

#### CDC Relay Service (Java)

| Task | Deliverable | Hex Layer |
|------|-------------|-----------|
| Domain core: CDC pipeline, offset management | `src/main/kotlin/domain/services/` | domain |
| Inbound port: StartReplication, PauseReplication, ResumeReplication | `src/main/kotlin/domain/ports/inbound/` | domain |
| Outbound port: KafkaProducer, OffsetStore | `src/main/kotlin/domain/ports/outbound/` | domain |
| Debezium Engine adapter | `src/main/kotlin/adapters/outbound/debezium/` | adapter |
| Kafka producer adapter | `src/main/kotlin/adapters/outbound/messaging/` | adapter |
| Offset storage adapter | `src/main/kotlin/adapters/outbound/persistence/` | adapter |
| Checksum validation | `src/main/kotlin/domain/validation/` | domain |
| OTel + SPIFFE integration | adapter/infra | adapter/infra |
| Dockerfile + build.gradle.kts | build files | build |
| Unit + integration tests | `src/test/` | test |

### Track 6: Python Services (Notification, Analytics) + AI/ML Intelligence Layer

**Owner:** Python Agent
**Spec Items:** 3.1, 3.2, 3.4
**Branch Pattern:** `feature/P3-3.1-<service>-<desc>`

#### Notification Service (Python)

| Task | Deliverable | Hex Layer |
|------|-------------|-----------|
| Domain core: delivery optimization, channel routing | `src/domain/services/` | domain |
| Inbound port: SendNotification, GetPreferences | `src/domain/ports/inbound/` | domain |
| Outbound port: NotificationChannel, TemplateEngine, PreferenceStore | `src/domain/ports/outbound/` | domain |
| CloudEvent consumer adapter (cloudevents-python) | `src/adapters/inbound/events/` | adapter |
| Email/SMS/Push adapters | `src/adapters/outbound/channels/` | adapter |
| Template engine adapter (Jinja2) | `src/adapters/outbound/template/` | adapter |
| Preference storage adapter | `src/adapters/outbound/persistence/` | adapter |
| ML delivery optimization module | `src/adapters/outbound/ml/` | adapter |
| OTel + SPIFFE integration | `src/infrastructure/` | infra |
| Dockerfile + pyproject.toml | build files | build |
| Unit + contract tests (pytest + Pact) | `tests/` | test |

#### Analytics Service (Python)

| Task | Deliverable | Hex Layer |
|------|-------------|-----------|
| Domain core: report generation, metric aggregation | `src/domain/services/` | domain |
| Inbound port: GetReport, QueryMetrics | `src/domain/ports/inbound/` | domain |
| Outbound port: MetricStore, ReportStore | `src/domain/ports/outbound/` | domain |
| CloudEvent consumer + gRPC query adapter | `src/adapters/inbound/` | adapter |
| ClickHouse/TimescaleDB adapter | `src/adapters/outbound/persistence/` | adapter |
| Pandas/Jupyter pipeline adapter | `src/adapters/outbound/analysis/` | adapter |
| OTel + SPIFFE integration | `src/infrastructure/` | infra |
| Dockerfile + pyproject.toml | build files | build |
| Unit + contract tests | `tests/` | test |

#### AI/ML Intelligence Layer (Python)

| Task | Pattern | Deliverable | Hex Layer |
|------|---------|-------------|-----------|
| RL Engine core | Reinforcement Learning | `src/intelligence/rl/engine.py` | adapter |
| RL policy export (ONNX) | RL | `src/intelligence/rl/export.py` | adapter |
| Meta-Learning framework | Meta-Learning | `src/intelligence/meta/learner.py` | adapter |
| Online learning drift detector | Online Learning | `src/intelligence/online/drift.py` | adapter |
| Federated learning coordinator | Federated Learning | `src/intelligence/federated/coordinator.py` | adapter |
| Causal inference RCA engine | Causal Inference | `src/intelligence/causal/rca.py` | adapter |
| Self-supervised log encoder | Self-Supervised | `src/intelligence/ssl/encoder.py` | adapter |
| Neuro-symbolic rule engine | Neuro-Symbolic | `src/intelligence/neurosym/engine.py` | adapter |
| LLM agent operations bridge | LLM Agents | `src/intelligence/llm/agent.py` | adapter |
| Curriculum learning scheduler | Curriculum Learning | `src/intelligence/curriculum/scheduler.py` | adapter |
| Multi-task representation trainer | Multi-Task Learning | `src/intelligence/mtl/trainer.py` | adapter |
| RAG operational knowledge base | RAG | `src/intelligence/rag/retriever.py` | adapter |
| Diffusion model incident generator | Diffusion Models | `src/intelligence/diffusion/generator.py` | adapter |
| GNN dependency predictor | Graph Neural Networks | `src/intelligence/gnn/predictor.py` | adapter |

---

## 3B: Infrastructure Implementation

### Kubernetes Manifests

| Task | Component | Deliverable |
|------|-----------|-------------|
| Base namespace + SA + NetworkPolicy | Platform | `infra/kubernetes/base/` |
| OTel Collector DaemonSet | Observability | `infra/kubernetes/platform/otel-collector.yaml` |
| OTel Collector Gateway (HA) | Observability | `infra/kubernetes/platform/otel-gateway.yaml` |
| SPIRE Server (3 replicas) | Identity | `infra/kubernetes/platform/spire-server.yaml` |
| SPIRE Agent (DaemonSet) | Identity | `infra/kubernetes/platform/spire-agent.yaml` |
| Kafka + Debezium Connect | CDC | `infra/kubernetes/platform/kafka.yaml`, `debezium.yaml` |
| ArgoCD App-of-Apps | GitOps | `infra/kubernetes/apps/` |
| Per-service K8s manifests | Services | `infra/kubernetes/apps/<service>.yaml` |
| Environment overlays (dev/staging/prod) | IaC | `infra/kubernetes/overlays/` |

### Terraform Modules

| Task | Module | Deliverable |
|------|--------|-------------|
| K8s cluster provisioning | kubernetes | `infra/terraform/modules/kubernetes/` |
| VPC + networking | networking | `infra/terraform/modules/networking/` |
| OTel stack | observability | `infra/terraform/modules/observability/` |
| SPIRE identity | identity | `infra/terraform/modules/identity/` |
| CDC pipeline | cdc | `infra/terraform/modules/cdc/` |

### CI/CD Pipeline

| Task | Workflow | Deliverable |
|------|----------|-------------|
| Schema CI (Buf lint + breaking) | Schema validation | `.github/workflows/schema-ci.yml` |
| Service CI (lint + test + build) | Per-service pipeline | `.github/workflows/<service>-ci.yml` |
| Pact contract verification | Consumer-driven | `.github/workflows/pact-verify.yml` |
| Security scan (Trivy + SLSA) | Supply chain | `.github/workflows/security-scan.yml` |
| Mutation testing (Stryker/PIT) | Quality gate | `.github/workflows/mutation-test.yml` |
| OTel coverage audit | Observability gate | `.github/workflows/otel-coverage.yml` |

---

## 3C: Implementation Execution Protocol

```
SESSION START
  |
[READ] session-state.json -> current_phase == 3? -> YES: continue
  |
[READ] PHASE3_IMPLEMENTATION_SPEC.md -> understand current spec items
  |
[READ] worklog.md -> check previous agent progress
  |
[READ] PHASE2_DESIGN_SPEC.md -> reference design for implementation
  |
[ASSIGN] Pick unassigned spec item from PROJECT_PLAN.md Phase 3
  |
[BRANCH] Create feature branch: feature/P3-<spec-id>-<service>-<desc>
  |
[SCHEMA] Write proto + OpenAPI BEFORE service code (contract-first)
  |
[IMPLEMENT] Follow hexagonal architecture template per service
  |
[TEST] Write unit + contract + property tests alongside code
  |
[INSTRUMENT] Add OTel spans + SPIFFE Workload API integration
  |
[COMMIT] git commit -m "<type>(<scope>): <desc> [P3-<spec-id>]"
  |
[QA] Invoke /qa for full QA pass
  |
[REVIEW] Invoke /review for code quality check
  |
[FIX] Address QA + review findings, re-verify
  |
[MERGE] Merge to develop if QA + review pass
  |
[UPDATE] Update worklog.md with spec item verification
  |
[HANDOFF] Report results, identify next unassigned spec item
```

---

## 3D: Phase 3 Worker Agent Roles

| Agent Role | Spec Items | Services | gstack Skills |
|------------|-----------|----------|--------------|
| **Schema Agent** | 3.1, 3.2 (partial) | All (proto/OpenAPI/Pact) | Direct execution |
| **Go Agent** | 3.1, 3.2, 3.4 | Gateway, Payment, Schema Registry | /qa, /review, /benchmark |
| **Rust Agent** | 3.1, 3.2, 3.4, 3.9 | Identity | /qa, /review, /cso |
| **Node Agent** | 3.1, 3.2, 3.3, 3.4 | Catalog | /qa, /review |
| **JVM Agent** | 3.1, 3.2, 3.4 | Order, CDC Relay | /qa, /review |
| **Python Agent** | 3.1, 3.2, 3.4 | Notification, Analytics, AI/ML | /qa, /review |
| **Infra Agent** | 3.1, 3.2 | K8s manifests, Terraform, CI/CD | /qa, /review, /benchmark |
| **QA Agent** | 3.5, 3.6, 3.9, 3.10 | Cross-cutting | /qa, /review, /cso, /benchmark |

---

## 3E: Phase 3 Parallelization Strategy

```
Parallel Track 1: Schema Agent -- proto + OpenAPI + Pact + code gen (BLOCKS all others)
  |
  v (after schema gen complete)
Parallel Track 2: Go Agent -- Gateway + Payment + Schema Registry
Parallel Track 3: Rust Agent -- Identity
Parallel Track 4: Node Agent -- Catalog
Parallel Track 5: JVM Agent -- Order + CDC Relay
Parallel Track 6: Python Agent -- Notification + Analytics + AI/ML
Parallel Track 7: Infra Agent -- K8s + Terraform + CI/CD
  |
  v (after all tracks complete)
Sequential: QA Agent -- /qa + /review + /cso + /benchmark on all code
  |
  v
Phase 3 Gate Assessment
```

**Critical Dependency:** Schema Track (Track 1) MUST complete before Tracks 2-6 can begin, because generated code stubs from proto are required by all service implementations. Track 7 (Infra) can start in parallel with Track 1.

---

## 3F: Phase 3 Auto-Trigger Mapping

```
pre_execution -> check_freeze -> verify_output_dir -> inject_context(execution) ->
  implement via certified workflow (Type-dependent) ->
  skill_invoke(/qa) -> /review -> /benchmark ->
  post_execution -> validate_output -> update_worklog -> cleanup -> update_reliability
```

### Certified gstack Skills for Phase 3

- **Type 1:** `pdf`, `docx`, `xlsx`, `ppt` (system skills)
- **Type 2:** `charts` (system skill)
- **Type 3:** `fullstack-dev` (system skill) + `/design-html`, `/qa`, `/review`, `/ship`
- **Type 4:** Python scripting + `/investigate`, `/benchmark`, `/health`
- **Cross-cutting:** `/qa`, `/qa-only`, `/review`, `/codex`, `/careful`, `/freeze`

---

## Phase 3 Gate Assessment Protocol

Before declaring Phase 3 COMPLETE:

1. Verify ALL 10 spec items (3.1-3.10) are PASS
2. Run `/qa` on all service implementations -- zero open bugs
3. Run `/review` on all service implementations -- no blocking issues
4. Run `/cso` security audit on Identity and Payment services
5. Run `/benchmark` on Gateway, Catalog, and Order services
6. Verify all Pact contract tests pass across all consumer pairs
7. Verify mutation testing score >= 80% (target 90% within 6 months)
8. Verify OTel instrumentation coverage >= 90% of service endpoints
9. Verify SPIFFE/SPIRE mTLS works across all service pairs
10. Update session-state.json: current_phase = 4
11. Append Phase 3 -> Phase 4 transition to worklog.md
