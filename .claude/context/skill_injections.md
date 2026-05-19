# Prompt Injection Templates for gstack Skill Categories
# These are auto-injected when the workflow router matches a task type.
# Now includes phase-aware injection — each section notes which project phase it applies to.

## Planning & Review Skills Injection

**Applies to: Project Phase 1 (Discovery & Spec)**

When the task involves planning, reviewing, or strategizing:

```
PLANNING MODE ACTIVATED (Phase 1: Discovery & Spec)
- Use /office-hours to reframe the product idea before building (MANDATORY FIRST)
- Use /autoplan for the full review gauntlet (CEO → design → eng → DX)
- Use /plan-ceo-review for strategic review
- Use /plan-eng-review for engineering feasibility
- Use /plan-design-review for UX review
- Use /plan-devex-review for developer experience review

Process: /office-hours FIRST → then /autoplan or individual reviews
Never skip the office-hours step — it catches bad premises early.

Spec Items to verify:
- 1.1 Problem statement documented with premises
- 1.2 Alternatives analyzed (min 3 options)
- 1.3 Success criteria defined with measurable outcomes
- 1.8 Review gauntlet passed
```

## Design & Vibe Coding Skills Injection

**Applies to: Project Phase 2 (Design & Architecture)**

When the task involves UI design, visual design, or vibe coding:

```
DESIGN MODE ACTIVATED (Phase 2: Design & Architecture)
- Use /design-consultation for complete design system from scratch (MANDATORY FIRST)
- Use /design-shotgun for rapid multi-variant exploration
- Use /design-html for production HTML/CSS generation
- Use /design-review for visual audit + fix loop
- Use /codex for adversarial code review

Process: /design-consultation → /design-shotgun (variants) → /design-html (implementation) → /design-review (audit)
Never ship without /design-review.

Spec Items to verify:
- 2.1 Design system created or referenced
- 2.2 Multiple design variants explored (3+)
- 2.5 Design review passed
```

## Quality & Testing Skills Injection

**Applies to: Project Phase 4 (Testing & Validation), also used in Phase 3**

When the task involves QA, testing, or bug investigation:

```
QA MODE ACTIVATED (Phase 4: Testing & Validation)
- Use /qa for full QA pass (find bugs, fix, re-verify)
- Use /qa-only for report-only QA (no code changes)
- Use /investigate for systematic root-cause debugging
- Use /benchmark for performance regression detection
- Use /cso for OWASP Top 10 + STRIDE security audit

Process: /qa → (fix bugs) → /qa (re-verify) → /qa-only (final report)
Never ship without at least one /qa pass.

Spec Items to verify:
- 4.3 /qa full pass with zero open P0/P1 bugs
- 4.4 /benchmark performance regression check
- 4.5 /cso security audit clean
```

## Ship & Deploy Skills Injection

**Applies to: Project Phase 5 (Ship & Deploy)**

When the task involves shipping code, creating PRs, or deploying:

```
SHIP MODE ACTIVATED (Phase 5: Ship & Deploy)
- Use /review for pre-landing PR review (MANDATORY BEFORE SHIP)
- Use /ship for PR creation with tests, changelog, version bump
- Use /land-and-deploy for merge → CI → deploy → verify
- Use /canary for post-deploy monitoring
- Use /landing-report for ship queue dashboard

Process: /review → /ship → /land-and-deploy → /canary
Never skip /review before /ship. Never skip /canary after /land-and-deploy.

Spec Items to verify:
- 5.1 /review approved before merge
- 5.2 /ship creates PR with tests + changelog
- 5.4 /land-and-deploy completes
- 5.5 Production health verified
```

## Guardrail Skills Injection

**Applies to: All project phases (cross-cutting)**

When the task might be destructive or needs safety checks:

```
GUARDRAIL MODE ACTIVATED (Cross-Phase Safety)
- Use /careful before destructive commands (rm -rf, DROP TABLE, force-push)
- Use /freeze to lock edits to one directory
- Use /guard to activate both careful + freeze at once
- Use /unfreeze to remove restrictions

Process: /guard → (safe execution) → /unfreeze
Always use /careful when the task involves file deletion, database changes, or git force operations.
```

## Documentation Skills Injection

**Applies to: Project Phase 6 (Retrospective & Knowledge), also Phase 3 for inline docs**

When the task involves creating or updating documentation:

```
DOCUMENTATION MODE ACTIVATED (Phase 6: Retrospective & Knowledge)
- Use /document-generate for Diataxis docs (tutorial/how-to/reference/explanation)
- Use /document-release for post-ship doc updates
- Use /make-pdf for markdown-to-PDF conversion
- Use /learn for managing cross-session knowledge

Process: /document-generate → /make-pdf (if PDF output needed)
Never generate docs without checking existing docs first (/learn).

Spec Items to verify:
- 6.4 /learn captures cross-session knowledge
- 6.5 /context-save preserves working state
- 6.6 Reliability metrics reviewed
```

## Browser & Utility Skills Injection

**Applies to: All project phases (cross-cutting utility)**

When the task requires web browsing, scraping, or utility operations:

```
BROWSER MODE ACTIVATED (Cross-Phase Utility)
- Use /browse for all web browsing (NEVER mcp__claude-in-chrome__*)
- Use /scrape for data extraction from web pages
- Use /skillify to codify a scrape flow into a permanent skill
- Use /open-gstack-browser for visible browser with sidebar
- Use /pair-agent for remote AI agent + browser pairing
- Use /setup-browser-cookies for authenticated browsing

Process: /setup-browser-cookies (if auth needed) → /browse or /scrape → /skillify (if reusable)
```

## Implementation Skills Injection

**Applies to: Project Phase 3 (Implementation & Coding)**

When the task involves writing production code or creating deliverables:

```
IMPLEMENTATION MODE ACTIVATED (Phase 3: Implementation & Coding)
- Type 1 (Document): Use pdf/docx/xlsx/ppt skill → generate deliverable
- Type 2 (Visualization): Use charts skill → matplotlib/seaborn/ECharts/D3/Mermaid/Playwright+CSS
- Type 3 (Web Dev): Use fullstack-dev skill → Next.js 16 + React + Prisma
- Type 4 (Data): Use Python script → pandas/numpy
- Always run /qa after implementation
- Always run /review before considering complete
- Boil the Lake — complete implementation, no 90% shortcuts

Spec Items to verify:
- 3.1 Code follows design specification
- 3.2 All spec items implemented (Boil the Lake)
- 3.5 /qa pass completed with zero open bugs
- 3.6 /review approved
```
