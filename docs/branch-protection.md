# Branch Protection Rules

This document defines the branch protection rules enforced on this repository to ensure code quality, traceability, and production stability. These rules are configured in the GitHub repository settings and are complemented by pre-commit hooks, CI gate checks, and gstack skill validations. No contributor, including administrators and CI service accounts, may bypass these rules without following the documented exception process.

---

## main Branch Protection

The `main` branch is the most heavily protected branch in the repository because it represents the production-ready state of the system. Every change that reaches `main` has been reviewed, tested, and validated through multiple automated and manual gates. The following protection rules are enforced without exception, and administrators are explicitly included in the enforcement scope to prevent any bypass through elevated privileges.

### Require Pull Request Before Merging

Every change to `main` must be submitted through a pull request. Direct pushes to `main` are prohibited regardless of the contributor's role or permissions. The pull request must receive a minimum of 1 approving review before it can be merged. This requirement ensures that at least one other person or agent has examined the change, verified its correctness, and confirmed that it aligns with the design specification and architectural standards defined in the PHASE2_DESIGN_SPEC.md document.

### Required Status Checks

Three mandatory status checks must pass before a pull request targeting `main` can be merged. The CI lint check validates that all code conforms to the style and formatting rules defined for each language in the polyglot service registry. The CI test check executes the full test suite including unit tests, integration tests, and contract tests for all modified services. The Buf breaking check verifies that no backward-incompatible schema changes have been introduced, protecting downstream consumers from breaking changes. All three checks must pass simultaneously; if any check fails, the merge button remains disabled.

### Require Conversation Resolution

All conversations on a pull request must be resolved before the merge is permitted. This rule ensures that reviewer comments, questions, and suggestions are addressed by the contributor, and that no open issues or unresolved feedback remain when the change is merged. Resolving a conversation means either making the requested change, providing a satisfactory explanation for why the change is not needed, or explicitly marking the conversation as resolved after reaching agreement with the reviewer.

### Require Signed Commits

All commits on a pull request targeting `main` must be cryptographically signed using GPG or SSH signing keys. This requirement provides a strong provenance guarantee that each commit was authored by the claimed identity, which is essential for audit trails and compliance in production systems. Unsigned commits will cause the PR to fail the status checks and block merging. Contributors must configure their local git client to sign commits by default using `git config commit.gpgsign true` or equivalent SSH signing configuration.

### Include Administrators

Branch protection rules apply equally to repository administrators. No administrator may bypass the pull request requirement, the status check requirement, or any other protection rule on the `main` branch. This rule prevents the common anti-pattern where elevated privileges allow unreviewed code to reach production, which undermines the entire review and validation process. If an emergency truly requires expedited handling, the correct procedure is to use a hotfix branch with an expedited review rather than bypassing protection rules.

### Restrict Push Access

Push access to the `main` branch is restricted to the CI service account only. No human user, administrator, or worker agent has direct push access. The CI service account is permitted to push only in the context of automated merge operations that have passed all required status checks and review approvals. This restriction is implemented through GitHub's branch protection settings and is further reinforced by the repository's access control configuration.

### No Force Pushes

Force pushes to the `main` branch are strictly prohibited. Force pushes rewrite git history, which can cause data loss, break cloned repositories, and destroy the audit trail that branch protection is designed to preserve. If a problematic commit reaches `main`, the correct remediation is to revert the commit or merge a hotfix branch rather than rewriting history. This rule is enforced at the repository level and cannot be overridden by any user or service account.

### No Deletions

The `main` branch cannot be deleted by any user or service account. This rule protects the branch from accidental or malicious deletion, which would result in the loss of the entire production history and potentially catastrophic consequences for deployment pipelines and release tracking. Branch deletion protection is a fundamental safeguard that ensures the continuity and integrity of the production codebase.

---

## develop Branch Protection

The `develop` branch serves as the integration point for all feature work and is protected to maintain build quality and test coverage. However, the protection rules for `develop` are slightly less restrictive than those for `main`, reflecting its role as a working integration branch rather than a production branch. The following rules are enforced on the develop branch.

### Require Pull Request Before Merging

All changes to the `develop` branch must be submitted through a pull request, and the PR must receive at least 1 approving review before merging. This requirement ensures that every integrated change has been examined by at least one reviewer who can verify that the implementation follows the hexagonal architecture pattern, respects the schema-first development approach, and aligns with the relevant spec item. The review requirement applies to all branch types that merge into develop, including feature branches, design branches, schema branches, and infrastructure branches.

### Required Status Checks

Two mandatory status checks must pass before a pull request targeting `develop` can be merged. The CI lint check validates code style and formatting across all affected services. The CI test check runs the relevant test suites for the modified components. Unlike the `main` branch, the Buf breaking check is not required for merges into `develop` because the develop branch is the appropriate place for schema changes to accumulate before a release is cut. However, contributors are strongly encouraged to run Buf checks locally before pushing to catch issues early.

### Allow Force Pushes by Administrators Only

Administrators are permitted to force-push to the `develop` branch for cleanup purposes only. This is a narrowly scoped exception that allows administrators to rebase a large batch of merged features, fix a problematic merge commit, or recover from an integration error without going through the full PR process. Force pushes by non-administrators are prohibited. This privilege must be used judiciously, and any force push to `develop` must be communicated to the team immediately to prevent others from working on a stale branch tip.

### No Deletions

The `develop` branch cannot be deleted by any user or service account. Like the `main` branch, `develop` is a long-lived branch that serves as the foundation for all feature branches and release cuts. Deleting it would disrupt every active contributor and potentially cause data loss. This protection rule ensures the continued availability and integrity of the integration branch throughout the project lifecycle.

---

## Feature Branch Rules

Feature branches are short-lived, disposable branches that exist for the duration of a single feature implementation. The rules governing feature branches are intentionally lightweight to allow worker agents and developers to work freely without unnecessary bureaucratic overhead, while still maintaining enough structure to ensure clean integration with the develop branch.

### Auto-Delete After Merge to Develop

Feature branches are automatically deleted after they are successfully merged into the develop branch. This housekeeping rule prevents the repository from accumulating stale branches that clutter the branch listing and create confusion about which branches are active. Auto-deletion is configured in the GitHub repository settings and applies to all branch types that match the feature branch naming pattern. After a branch is deleted, its commits remain accessible through the merge commit on develop, so no work is lost.

### No Protection Rules

Feature branches have no branch protection rules applied. Worker agents and developers can push freely, force-push to rewrite history, and manage the branch as needed without any approval requirements or status check gates. This freedom is appropriate because feature branches are isolated from the protected branches and their changes are validated when the PR to develop is created. The lack of protection rules allows for rapid iteration, experimentation, and course correction during development.

### Must Be Rebased on Develop Before Merge

Before a feature branch can be merged into develop, it must be rebased on the latest develop branch tip. This requirement ensures a clean, linear history on develop without unnecessary merge commits that would create visual noise and complicate bisect operations. The rebase also helps identify integration conflicts early, before the merge is attempted, so the contributor can resolve them in the context of their feature branch rather than during the merge itself. The CI pipeline verifies that the branch is up to date with develop before allowing the merge to proceed.
