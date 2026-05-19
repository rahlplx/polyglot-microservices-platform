# Phase 2: Design & Polyglot Architecture Mapping

> **Status:** IN PROGRESS
> **Gate:** All 10 spec items (2.1-2.10) must PASS before advancing to Phase 3
> **Canonical spec:** `/home/z/my-project/SPECIFICATION.md`
> **Phase 1 prerequisite:** COMPLETE (8/8 PASS — Review Gauntlet cleared)

---

## Phase 2 Overview

Phase 2 transforms the approved Phase 1 specification into concrete, implementable design artifacts. The core mission is to map the "Best of Both Worlds" architecture to a polyglot service topology with precise port/adapter contracts, dual API schema definitions (gRPC + OpenAPI), and the repository/branching strategy that worker agents will follow during implementation.

### Core Design Principles

1. **Reversibility First** — Every design decision must be reversible within 1 sprint (SC-1). If a component cannot be swapped without cascade changes, the design is wrong.
2. **Contract-Driven** — All inter-service communication is defined by schemas (Protobuf + OpenAPI), not by shared code. Services communicate through generated stubs only.
3. **Zero Trust by Default** — Every service-to-service call authenticates via SPIFFE/SPIRE mTLS. No service assumes network perimeter security.
4. **Observability Native** — Every service ships with OTel instrumentation from Day 1. No retrofitting.

---

## Spec-Driven Requirements (Extended)

| ID | Requirement | Verification | Status |
|----|-------------|-------------|--------|
| 2.1 | Design system created or referenced | /design-consultation output documented | PENDING |
| 2.2 | Multiple design variants explored | /design-shotgun produced 3+ variants | PENDING |
| 2.3 | Architecture diagram(s) created | Visual architecture in download/ | PENDING |
| 2.4 | Component inventory with interfaces | Each component has defined I/O | PENDING |
| 2.5 | Design review passed | /design-review completed with fix loop | PENDING |
| 2.6 | Accessibility requirements defined | A11y criteria in specification | PENDING |
| 2.7 | Performance budget established | Core Web Vitals targets set | PENDING |
| 2.8 | Security considerations documented | /cso security audit if applicable | PENDING |
| 2.9 | Git-Flow branching strategy defined | Branching model documented + enforced | PENDING |
| 2.10 | Worker agent instructions generated | AGENTS.md Phase 2 section complete | PENDING |

---

## 2A: Polyglot Service Topology

### Service Registry

The following services constitute the polyglot architecture. Each service is independently deployable, independently replaceable, and communicates exclusively through defined contracts.

| Service | Primary Language | Rationale | Communication Pattern |
|---------|-----------------|-----------|----------------------|
| **Gateway** | Go | High-throughput ingress, low-latency routing, mature net/http + gRPC ecosystem | gRPC proxy + REST pass-through |
| **Identity** | Rust | SPIFFE/SPIRE integration, memory-safe crypto operations, zero-cost abstractions | gRPC server + mTLS |
| **Catalog** | Node.js/TypeScript | Rich ecosystem for product/inventory schemas, fast iteration for business logic | gRPC server + REST (OpenAPI) |
| **Order** | Java/Kotlin | Enterprise transaction patterns, Saga orchestration, mature JVM tooling | gRPC server + Outbox |
| **Payment** | Go | High-concurrency payment processing, Circuit Breaker patterns, PCI-DSS tooling | gRPC server + ACL sidecar |
| **Notification** | Python | ML-driven delivery optimization, async processing, rich template libraries | Event consumer (CloudEvents) |
| **Analytics** | Python | Data pipeline orchestration, OTel processing, Jupyter/Pandas ecosystem | Event consumer + gRPC query |
| **CDC Relay** | Java | Debezium native, Kafka Connect ecosystem, proven CDC tooling | Kafka producer |
| **Schema Registry** | Go | Buf registry, proto compilation, schema validation API | gRPC + REST |

### Port/Adapter Template Architecture

Each service follows the Hexagonal Architecture pattern with these standardized layers:

```
service/
├── domain/                    # Core business logic (NO external dependencies)
│   ├── ports/
│   │   ├── inbound/           # Use case interfaces (driving ports)
│   │   │   └── <usecase>.go   # e.g., CreateOrder, GetCatalog
│   │   └── outbound/          # Infrastructure interfaces (driven ports)
│   │       └── <port>.go      # e.g., OrderRepository, EventPublisher
│   ├── models/                # Domain entities and value objects
│   └── services/              # Domain services implementing use cases
├── adapters/
│   ├── inbound/               # Driving adapters (controllers, consumers)
│   │   ├── grpc/              # gRPC handlers (generated from Protobuf)
│   │   ├── rest/              # REST controllers (generated from OpenAPI)
│   │   └── events/            # CloudEvent consumers
│   └── outbound/              # Driven adapters (repositories, clients)
│       ├── persistence/       # Database adapters (SQL/NoSQL)
│       ├── messaging/         # Kafka/pubsub adapters
│       ├── external/          # Third-party service clients (behind ACL)
│       └── observability/     # OTel instrumentation adapters
├── infrastructure/
│   ├── config/                # Configuration (env, feature flags)
│   ├── di/                    # Dependency injection wiring
│   └── server/                # Server setup (gRPC, HTTP, lifecycle)
├── api/
│   ├── proto/                 # Protobuf definitions (source of truth)
│   └── openapi/               # OpenAPI 3.1 specs (derived from proto)
├── tests/
│   ├── unit/                  # Domain unit tests
│   ├── contract/              # Pact contract tests
│   ├── property/              # Property-based tests (Hypothesis/proptest)
│   └── integration/           # Adapter integration tests
├── Dockerfile                 # Multi-stage OCI build
├── buf.yaml                   # Buf configuration
└── Makefile                   # Build, test, lint, generate commands
```

### Anti-Corruption Layer (ACL) Specification

Every adapter that communicates with external systems (third-party APIs, legacy services, vendor-specific SDKs) MUST go through an ACL sidecar:

```
Service Domain ←→ ACL Port ←→ ACL Adapter ←→ External System
                                       ↕
                               ACL Sidecar Container
                               - Schema validation
                               - Circuit breaker
                               - Proprietary import blocking
                               - Request/response transformation
```

**ACL enforcement rules:**
1. No proprietary SDK imports in the `domain/` or `adapters/inbound/` directories
2. Pre-commit hooks scan for vendor-specific package imports in forbidden directories
3. All external communication routes through the ACL sidecar
4. ACL sidecar runs as a separate container with its own resource quotas (bulkhead)

---

## 2B: API Schema Repository Structure

### Dual-Contract Strategy

```
schemas/
├── buf.yaml                          # Root Buf configuration
├── buf.gen.yaml                      # Code generation configuration
├── proto/                            # Protobuf source of truth
│   ├── gateway/
│   │   └── v1/
│   │       ├── gateway.proto         # Gateway routing + health
│   │       └── rate_limit.proto      # Rate limiting definitions
│   ├── identity/
│   │   └── v1/
│   │       ├── identity.proto        # SPIFFE/SPIRE workload API
│   │       └── mtls.proto            # mTLS certificate rotation
│   ├── catalog/
│   │   └── v1/
│   │       ├── catalog.proto         # Product/inventory CRUD
│   │       └── search.proto          # Catalog search + filtering
│   ├── order/
│   │   └── v1/
│   │       ├── order.proto           # Order lifecycle (create → complete)
│   │       └── saga.proto            # Saga orchestration events
│   ├── payment/
│   │   └── v1/
│   │       ├── payment.proto         # Payment processing
│   │       └── circuit.proto         # Circuit breaker state
│   ├── notification/
│   │   └── v1/
│   │       └── notification.proto    # Notification delivery
│   ├── analytics/
│   │   └── v1/
│   │       └── analytics.proto       # Analytics query API
│   └── common/
│       └── v1/
│           ├── types.proto           # Shared types (Money, Address, etc.)
│           ├── events.proto          # CloudEvent envelope definitions
│           └── errors.proto          # Standardized error codes
├── openapi/                          # OpenAPI 3.1 specs (derived)
│   ├── gateway/
│   │   └── v1.yaml
│   ├── catalog/
│   │   └── v1.yaml
│   ├── order/
│   │   └── v1.yaml
│   └── payment/
│       └── v1.yaml
├── generated/                        # Generated code (git-ignored)
│   ├── go/
│   ├── java/
│   ├── python/
│   ├── rust/
│   └── typescript/
└── contracts/                        # Pact contract definitions
    ├── gateway-order/
    ├── catalog-order/
    ├── order-payment/
    └── order-notification/
```

### Schema Evolution Rules

1. **Protobuf** — Only additive changes (new fields, new services). Never remove or rename existing fields. Use `reserved` for deprecated fields.
2. **OpenAPI** — Generated from Protobuf via `buf generate`. Manual edits are overwritten on next generation.
3. **Pact** — Consumer-driven. Provider verifies against consumer contracts in CI.
4. **Breaking change detection** — `buf breaking` runs in CI on every PR. No merge allowed if breaking changes detected.

---

## 2C: Git-Flow Branching Strategy for Worker Agents

### Branching Model

```
main (protected)
  │
  ├── develop (integration branch — worker agents merge here)
  │     │
  │     ├── feature/P2-<spec-id>-<service>-<description>
  │     │   e.g., feature/P2-2.4-catalog-port-adapter-template
  │     │   e.g., feature/P2-2.3-gateway-grpc-proto
  │     │
  │     ├── feature/P2-<spec-id>-<component>-<description>
  │     │   e.g., feature/P2-2.9-schemas-proto-definitions
  │     │   e.g., feature/P2-2.4-acl-sidecar-template
  │     │
  │     └── feature/P2-<spec-id>-infra-<description>
  │         e.g., feature/P2-2.9-otel-collector-config
  │         e.g., feature/P2-2.4-gitops-argocd-apps
  │
  ├── release/v<semver> (release branches — cut from develop, merged to main)
  │     e.g., release/v0.1.0-phase2-design
  │
  └── hotfix/<description> (emergency fixes — branched from main)
        e.g., hotfix/schema-breaking-change-fix
```

### Branch Naming Convention

| Branch Type | Format | Example | Allowed Authors |
|-------------|--------|---------|----------------|
| Feature | `feature/P2-<spec-id>-<service>-<short-desc>` | `feature/P2-2.4-catalog-ports` | Worker agents |
| Design | `design/P2-<spec-id>-<artifact>` | `design/P2-2.3-architecture-diagram` | Design agents |
| Schema | `schema/P2-<service>-<version>` | `schema/P2-catalog-v1` | Schema agents |
| Infra | `infra/P2-<component>-<desc>` | `infra/P2-otel-collector-config` | Infra agents |
| Release | `release/v<semver>-<milestone>` | `release/v0.2.0-phase2` | Lead agent |
| Hotfix | `hotfix/<desc>` | `hotfix/proto-breaking-fix` | Any agent |

### Merge Rules

1. **Feature → develop:** Requires 1 approving review (automated via /review gstack skill)
2. **Develop → main:** Requires Phase gate PASS (all spec items verified) + /review + /qa
3. **No direct commits to `main`** — Protected branch, CI-only merges
4. **Squash merge** for feature branches (clean history)
5. **Merge commit** for develop → main (preserve integration history)
6. **Rebase** before merge (no merge bubbles in feature branches)

### Worker Agent Git Protocol

Each worker agent MUST follow this protocol when making changes:

```
1. READ current branch: git branch --show-current
2. CHECK branch is NOT main: if main, STOP and create feature branch
3. CREATE feature branch (if not on one):
   git checkout -b feature/P2-<spec-id>-<service>-<desc> develop
4. IMPLEMENT changes (see AGENTS.md Phase 2 instructions)
5. LINT + TEST: make lint test
6. COMMIT: git commit -m "feat(<service>): <description> [P2-<spec-id>]"
7. PUSH: git push origin feature/P2-<spec-id>-<service>-<desc>
8. REVIEW: invoke /review gstack skill
9. MERGE: if review passes, merge to develop
10. UPDATE worklog.md with spec item status
```

### Commit Message Convention

```
<type>(<scope>): <description> [P2-<spec-id>]

Types: feat, fix, docs, refactor, test, chore, schema, design
Scope: service name or component name
Spec ID: maps to PROJECT_PLAN.md Phase 2 spec item

Examples:
feat(catalog): add hexagonal port/adapter template [P2-2.4]
schema(order): define order.proto v1 with create/complete RPCs [P2-2.9]
design(gateway): add gRPC proxy architecture diagram [P2-2.3]
test(identity): add Pact contract tests for SPIFFE workload API [P2-2.4]
infra(otel): add OTel Collector fan-out configuration [P2-2.4]
```

---

## 2D: IaC Repository Structure

```
infra/
├── terraform/                        # Cloud-agnostic IaC (Terraform + Crossplane)
│   ├── modules/
│   │   ├── kubernetes/               # Vanilla K8s cluster provisioning
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── networking/               # VPC, subnets, security groups
│   │   ├── observability/            # OTel Collector, Prometheus, Grafana
│   │   ├── identity/                 # SPIRE server, entry creation
│   │   └── cdc/                      # Debezium, Kafka Connect
│   ├── environments/
│   │   ├── dev/
│   │   ├── staging/
│   │   └── production/
│   └── backend.tf                    # Remote state configuration
├── kubernetes/                       # Vanilla K8s manifests
│   ├── base/                         # Base manifests (shared)
│   │   ├── namespace.yaml
│   │   ├── serviceaccount.yaml
│   │   └── networkpolicy.yaml
│   ├── overlays/                     # Environment-specific overlays
│   │   ├── dev/
│   │   ├── staging/
│   │   └── production/
│   ├── apps/                         # ArgoCD Application manifests
│   │   ├── gateway.yaml
│   │   ├── identity.yaml
│   │   ├── catalog.yaml
│   │   └── ...
│   └── platform/                     # Platform components
│       ├── otel-collector.yaml
│       ├── spire-server.yaml
│       ├── spire-agent.yaml
│       ├── kafka.yaml
│       └── debezium.yaml
├── gitops/                           # ArgoCD/Flux configuration
│   ├── argocd/
│   │   ├── app-of-apps.yaml
│   │   ├── projects.yaml
│   │   └── rbac.yaml
│   └── flux/                         # Flux alternative (optional)
│       ├── kustomization.yaml
│       └── helm-releases/
└── scripts/
    ├── migrate-cloud.sh              # CDC migration orchestrator
    ├── canary-shift.sh               # DNS canary traffic shifting
    └── chaos-game-day.sh             # Game Day validation runner
```

---

## 2E: Observability Stack Design

### OTel Collector Fan-Out Architecture

```
Services (instrumented)
  │  W3C Trace Context propagation
  ↓
OTel Collector (DaemonSet — 1 per node)
  │  Receivers: OTLP/gRPC + OTLP/HTTP
  │  Processors: tail_sampling, batch, resource, filter
  ↓
OTel Collector (Gateway — 2 replicas, HA)
  │  Fan-out to backends:
  ├──→ Prometheus (metrics — RED: Rate, Errors, Duration)
  ├──→ Grafana Tempo (traces — tail-sampled, 30-day retention)
  ├──→ Grafana Loki (logs — structured JSON, 14-day retention)
  └──→ PagerDuty (alerts — SLO-driven, error budget depletion)
```

### Tail-Based Sampling Rules

```yaml
tail_sampling:
  decision_wait: 10s
  num_traces: 100000
  expected_new_traces_per_sec: 100
  policies:
    - name: errors
      type: status_code
      status_code: { status_codes: [ERROR] }
    - name: slow-traces
      type: latency
      latency: { threshold_ms: 2000 }
    - name: critical-paths
      type: string_attribute
      string_attribute: { key: "service.namespace", values: ["gateway", "order", "payment"] }
    - name: sample-10-percent
      type: probabilistic
      probabilistic: { sampling_percentage: 10 }
```

### SLO Definitions

| Service | SLO | Error Budget (30d) | Alert Threshold |
|---------|-----|---------------------|-----------------|
| Gateway | 99.99% availability | 4.32 min | Alert at 50% budget consumed |
| Order | 99.95% success rate | 21.6 min | Alert at 50% budget consumed |
| Payment | 99.99% success rate | 4.32 min | Alert at 50% budget consumed |
| Catalog | 99.9% availability | 43.2 min | Alert at 30% budget consumed |
| Notification | 99.5% delivery rate | 216 min | Alert at 30% budget consumed |

---

## 2F: Design Variants (3+ Required by Spec 2.2)

### Variant A: Centralized Gateway + Mesh

- Single API Gateway handles all routing, rate limiting, and auth
- Service mesh (Istio/Linkerd) provides mTLS and observability
- Pros: Simple operational model, single point of policy
- Cons: Vendor dependency on mesh, gateway becomes bottleneck

### Variant B: Gateway + SPIFFE/SPIRE (SELECTED)

- API Gateway handles ingress routing and rate limiting
- SPIFFE/SPIRE provides mTLS identity (no mesh required)
- OTel provides observability (no mesh sidecar required)
- Pros: Zero mesh dependency, lighter resource footprint, technology-neutral
- Cons: More initial configuration, no automatic traffic management

### Variant C: Federated Gateways + mTLS

- Per-domain gateways (e.g., order-gateway, catalog-gateway)
- Direct mTLS between services using cert-manager
- Pros: Domain autonomy, no single point of failure
- Cons: Complex routing, policy duplication, harder to enforce consistency

**Selection: Variant B** — aligns with Technology-Neutral mandate (no mesh dependency), supports SC-1 (language agility — no mesh sidecar coupling), and enables SC-3 (cloud portability — SPIFFE/SPIRE is cloud-agnostic).

---

## Phase 2 Auto-Trigger Mapping

```
pre_execution → check_freeze → verify_output_dir → inject_context(execution) →
  skill_invoke(/design-consultation) → /design-shotgun → /design-html → /design-review →
  post_execution → validate_output → update_worklog → cleanup
```

### Certified gstack Skills for Phase 2

- `/design-consultation` — Build complete design system (MANDATORY FIRST)
- `/design-shotgun` — Rapid multi-variant exploration
- `/design-html` — Production HTML/CSS from design description
- `/design-review` — Visual audit + fix loop
- `/cso` — OWASP Top 10 + STRIDE security audit

---

## Phase 2 Gate Assessment

| Spec Item | Status | Evidence Required |
|-----------|--------|-------------------|
| 2.1 Design system documented | PENDING | Design system document with tokens, components, patterns |
| 2.2 3+ design variants explored | PENDING | Variant A, B, C documented with trade-off analysis |
| 2.3 Architecture diagram(s) created | PENDING | Visual architecture in download/ directory |
| 2.4 Component inventory with I/O | PENDING | Each service has defined ports, adapters, contracts |
| 2.5 Design review passed | PENDING | /design-review completed with fix loop |
| 2.6 Accessibility requirements defined | PENDING | A11y criteria for any user-facing components |
| 2.7 Performance budget established | PENDING | Core Web Vitals + API latency targets |
| 2.8 Security considerations documented | PENDING | STRIDE threat model + SPIFFE/SPIRE design |
| 2.9 Git-Flow branching strategy defined | PENDING | Branching model documented (this document) |
| 2.10 Worker agent instructions generated | PENDING | AGENTS.md Phase 2 section complete |

**Gate Status: 0/10 PASS — Phase 2 just initialized**
