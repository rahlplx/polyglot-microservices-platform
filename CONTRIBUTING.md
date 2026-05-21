# Contributing Guide

This document defines the contribution workflow, branching strategy, commit conventions, merge rules, code review process, and development setup for this project. All contributors, including worker agents and human developers, must follow these rules without exception. Violations will be caught by pre-commit hooks and CI checks, and non-compliant pull requests will be rejected automatically.

---

## Branching Strategy

This project uses a Git-Flow branching model adapted for a polyglot microservices architecture with automated worker agent contributions. The branching model provides clear separation between production-ready code, integration work, and isolated feature development, ensuring that the `main` branch always reflects a deployable state while allowing concurrent development across multiple services and teams. Each branch type has a specific naming convention, lifecycle, and merge target that must be respected.

### main (protected)

The `main` branch contains production-ready code only. No direct pushes are permitted under any circumstances, including by administrators or CI service accounts performing manual overrides. All changes must arrive in `main` through merge commits from release branches or hotfix branches, and every merge must pass all CI checks including lint, test, schema validation, and Buf breaking checks. This branch represents the single source of truth for what is currently deployed or deployable, and its integrity is paramount to the reliability of the entire system.

### develop (integration)

The `develop` branch serves as the integration branch for all feature work across every service in the polyglot architecture. All worker agents and human developers merge their completed feature branches here after the required review approval. This branch accumulates integrated changes from multiple features and is the source branch for release cuts. While it is protected, administrators may force-push for cleanup purposes when necessary, such as rebasing a large batch of merged features to maintain a clean history. The develop branch should always be in a buildable, testable state.

### feature/P2-\<spec-id\>-\<service\>-\<desc\>

Feature branches are created from `develop` and named after Phase 2 spec items to maintain full traceability between the design specification and the implementation. The `<spec-id>` maps directly to a numbered item in the PHASE2_DESIGN_SPEC.md, the `<service>` identifies which microservice the change targets, and `<desc>` provides a brief hyphenated description of the feature. For example, `feature/P2-2.4-catalog-hexagonal-ports` clearly indicates this branch implements spec item 2.4 for the catalog service, specifically the hexagonal port definitions. Feature branches are short-lived and must be rebased on develop before merging.

### design/P2-\<spec-id\>-\<artifact\>

Design artifact branches are used for design-phase deliverables such as architecture diagrams, sequence diagrams, and technical specification documents that are produced before implementation begins. These branches capture the design thinking and visual artifacts that inform implementation decisions. The `<artifact>` segment describes the type of design output, for example `design/P2-2.3-gateway-grpc-proxy-diagram` for the API Gateway gRPC proxy architecture diagram. Design branches are merged to develop with the same review requirements as feature branches, and they serve as the source of truth for how a system should be built.

### schema/P2-\<service\>-\<version\>

Schema definition branches are dedicated to Protobuf and OpenAPI schema changes for each service. Because this project follows a schema-first development approach, schema branches are created before any implementation code is written. The `<version>` segment follows semantic versioning and indicates the schema version being introduced or modified, for example `schema/P2-order-v1` for the initial order service Protobuf definitions. All schema changes must pass Buf breaking checks in CI to ensure backward compatibility, and no schema-breaking changes are allowed without an explicit migration plan documented in the PR description.

### infra/P2-\<component\>-\<desc\>

Infrastructure configuration branches handle changes to Terraform modules, Kubernetes manifests, GitOps configurations, and observability stack definitions. The `<component>` identifies the infrastructure layer being modified, and `<desc>` provides a brief summary of the change. For example, `infra/P2-otel-collector-fanout` would contain the OpenTelemetry Collector fan-out configuration for the observability pipeline. Infrastructure changes require the same review and CI gate process as application code, and they are subject to additional validation through Terraform plan checks and K8s dry-run applies in CI.

### release/v\<semver\>-\<milestone\>

Release branches are cut from `develop` when a set of features is ready to be stabilized for production deployment. The branch name includes the semantic version and a milestone identifier, for example `release/v0.1.0-phase2-design` for the Phase 2 design milestone release. Release branches allow the team to freeze feature scope, perform final QA validation, and apply any release-specific fixes without blocking ongoing development on the develop branch. Once a release branch passes all quality gates, it is merged into `main` via a merge commit, and the tag is created on `main`.

### hotfix/\<desc\>

Hotfix branches are created from `main` to address critical production issues that cannot wait for the next regular release cycle. The `<desc>` segment provides a concise description of the emergency fix, for example `hotfix/payment-circuit-breaker-threshold` for correcting a misconfigured circuit breaker in the payment service. Hotfix branches follow an expedited review process but still require at least one approving review and all CI checks to pass. After merging into `main`, the hotfix must also be merged back into `develop` to ensure the fix is not lost in the next release.

---

## Commit Message Convention

All commit messages must follow a structured format that enables automated changelog generation, traceability to spec items, and efficient history searching. The convention applies to every commit, whether made by a human developer or an automated worker agent. Commits that do not conform to this format will be rejected by the pre-commit hook.

### Format

```
<type>(<scope>): <description> [P2-<spec-id>]
```

The `<type>` indicates the category of change, `<scope>` identifies the service or component affected, `<description>` is a concise imperative-mood summary of the change, and `[P2-<spec-id>]` links the commit to the specific Phase 2 specification item that motivated the change. The square brackets around the spec ID are mandatory and allow automated tools to extract spec references from the git log.

### Types

| Type | Purpose |
|------|---------|
| feat | New feature or capability added to a service |
| fix | Bug fix or correction to existing behavior |
| docs | Documentation changes including README, CONTRIBUTING, and inline docs |
| refactor | Code restructuring without changing external behavior |
| test | New tests, test fixes, or test infrastructure changes |
| chore | Maintenance tasks, dependency updates, tooling changes |
| schema | Protobuf or OpenAPI schema definitions and modifications |
| design | Architecture diagrams, design documents, specification artifacts |
| infra | Infrastructure configuration, Terraform, Kubernetes, GitOps changes |

### Examples

```
feat(catalog): add hexagonal port/adapter template [P2-2.4]
schema(order): define order.proto v1 with create/complete RPCs [P2-2.9]
design(gateway): add gRPC proxy architecture diagram [P2-2.3]
test(identity): add Pact contract tests for SPIFFE workload API [P2-2.4]
infra(otel): add OTel Collector fan-out configuration [P2-2.4]
fix(payment): correct circuit breaker threshold configuration [P2-2.4]
```

These examples demonstrate the full range of commit types and scopes used in this project. Notice how each commit unambiguously identifies both the affected component and the spec item driving the change, making it straightforward to reconstruct the rationale for any modification by cross-referencing the PHASE2_DESIGN_SPEC.md document.

---

## Merge Rules

The merge rules in this project exist to enforce a clean, linear history on protected branches while ensuring that no unreviewed or untested code reaches production. These rules are enforced by branch protection settings, CI gate checks, and pre-commit hooks, so violations are caught automatically regardless of whether the contributor is a human or an automated worker agent.

1. **Feature to develop**: Requires 1 approving review via the `/review` gstack skill. The reviewer must verify that the implementation matches the spec item referenced in the PR title and commit messages, that all tests pass, and that no proprietary imports are present. Squash merge is used to keep the develop branch history clean and linear.

2. **Develop to main**: Requires a Phase gate PASS from the PROJECT_PLAN.md gate assessment, one approving review via `/review`, and a QA pass via `/qa`. Merge commits are used for develop-to-main merges to preserve the complete integration history and enable easy rollback by reverting the merge commit. This is the most stringent merge path in the project because it represents the boundary between integration and production.

3. **No direct commits to main**: This rule is absolute and enforced by branch protection. No user, administrator, or service account may push directly to main. All changes must flow through the prescribed branch hierarchy. If an emergency requires bypassing this rule, the correct procedure is to create a hotfix branch and follow the expedited review process.

4. **Squash merge for feature branches**: When a feature branch is merged into develop, all commits on the feature branch are squashed into a single commit. This prevents feature branch implementation details from cluttering the develop branch history and ensures that each merge commit on develop represents one logical change with a clear spec reference.

5. **Merge commit for develop to main**: When develop is merged into main for a release, a merge commit is used rather than a squash or rebase. This preserves the full set of integrated features as a single atomic unit on main, making it easy to identify exactly which features were included in each release and to roll back an entire release if necessary.

6. **Rebase before merge (no merge bubbles)**: All feature branches must be rebased on the latest develop before the merge is performed. This ensures a clean, linear history without unnecessary merge commits that would create visual noise in the git log. The rebase requirement also helps catch integration conflicts early, before the merge is attempted.

---

## Code Review Process

The code review process is designed to ensure quality, consistency, and compliance with the project's architectural standards without creating unnecessary bottlenecks. Every pull request must pass through a standardized review pipeline that combines automated checks with human or agent-based review, and no code may be merged until all gates are satisfied.

All PRs must pass CI checks before they are eligible for review. The CI pipeline runs lint checks for each service's language, executes the full test suite, performs Buf breaking checks on any modified Protobuf schemas, and validates that no schema-breaking changes are introduced. If any of these checks fail, the PR is automatically blocked from merging and the contributor must address the failures before review can proceed. The CI checks serve as a first-pass filter that catches obvious issues before human or agent reviewer time is consumed.

The `/review` gstack skill provides an automated review that checks for adherence to the hexagonal architecture, proper use of the port/adapter pattern, compliance with the schema-first development approach, and correct commit message formatting. The review skill also verifies that the PR description references the appropriate spec item and that the implementation aligns with the design specification. This automated review is required for all PRs targeting develop and main, and its output is posted as a comment on the PR for transparency.

The `/qa` gstack skill provides a quality assurance pass that is required in addition to the review for all PRs targeting main. The QA pass validates that the change meets the acceptance criteria defined in the spec item, verifies that integration tests pass, checks SLO compliance for affected services, and confirms that no regression has been introduced. This additional gate ensures that only thoroughly validated code reaches the production branch.

ACL enforcement via pre-commit hooks blocks any proprietary imports that would violate the technology-neutral mandate of this project. The hooks scan import statements and dependency declarations for references to vendor-specific SDKs, proprietary libraries, and cloud-provider-specific packages that would create lock-in. This enforcement happens at commit time, providing immediate feedback to the contributor and preventing non-compliant code from entering the repository. The pre-commit hooks are mandatory and cannot be bypassed without disabling the hooks entirely, which would itself be flagged in CI.

Buf breaking checks are a critical component of the schema-first development approach. No schema-breaking changes are allowed in this project, and the Buf tooling enforces this rule in CI by comparing the modified Protobuf definitions against the existing schema and reporting any incompatible changes. If a change is truly necessary and cannot be expressed in a backward-compatible way, the contributor must document a migration plan in the PR description and obtain explicit approval from the Architecture Lead before the PR can be merged.

---

## Development Setup

Setting up the development environment for this project requires a sequence of steps that install the necessary tools, clone the repository, and configure the local workspace for compliance with the project's commit hooks and CI requirements. The setup process is designed to be repeatable and idempotent, so running it multiple times will not cause issues.

1. **Clone the repository**: Begin by cloning the repository to your local machine. Use `git clone <repo-url>` to obtain the full repository history. If you are working with a large repository and only need the most recent history, you may use `git clone --depth 1` for a shallow clone, but be aware that some operations such as rebasing may require fetching additional history.

2. **Install gstack**: The gstack tool provides the automated review, QA, and deployment capabilities that are required for all contributions to this project. Install it by running the following command, which clones the gstack repository and runs the team setup script:

   ```bash
   git clone --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup --team
   ```

   The `--team` flag enables team mode, which registers enforcement hooks that verify gstack is available before each session and before tool use. This ensures that all contributors have the required tooling and that automated checks are consistently applied.

3. **Create a feature branch from develop**: Before making any changes, create a feature branch from the latest develop branch. Use the naming convention defined in the Branching Strategy section above, ensuring that the branch name includes the spec item ID and a descriptive suffix. For example: `git checkout develop && git pull && git checkout -b feature/P2-2.4-catalog-hexagonal-ports`.

4. **Implement changes**: Write your code following the hexagonal architecture pattern, schema-first development approach, and technology-neutral mandate defined in the PHASE2_DESIGN_SPEC.md. Ensure that all new code includes appropriate tests, that Protobuf schemas are defined before implementation, and that no proprietary imports are introduced.

5. **Run make lint test**: Before committing, run `make lint test` to execute the full lint and test suite locally. This catches issues early and reduces the likelihood of CI failures after pushing. Fix any issues reported by the linter or test suite before proceeding to the commit step.

6. **Commit with proper message format**: Use the commit message convention defined in this document. Every commit must follow the `<type>(<scope>): <description> [P2-<spec-id>]` format. The pre-commit hooks will validate the format and check for proprietary imports. If the hooks reject your commit, fix the reported issues and try again.

7. **Push and create PR**: Push your feature branch to the remote repository and create a pull request targeting the develop branch. The PR title should match the branch name convention, and the description should reference the spec item being implemented, describe the changes made, and include any migration plans if applicable. The CI pipeline and automated review will begin running immediately.
