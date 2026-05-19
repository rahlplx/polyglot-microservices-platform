# Prompt Injection Templates for gstack Skill Categories
# These are auto-injected when the workflow router matches a task type.

## Planning & Review Skills Injection

When the task involves planning, reviewing, or strategizing:

```
PLANNING MODE ACTIVATED
- Use /office-hours to reframe the product idea before building
- Use /autoplan for the full review gauntlet (CEO → design → eng → DX)
- Use /plan-ceo-review for strategic review
- Use /plan-eng-review for engineering feasibility
- Use /plan-design-review for UX review
- Use /plan-devex-review for developer experience review

Process: /office-hours FIRST → then /autoplan or individual reviews
Never skip the office-hours step — it catches bad premises early.
```

## Design & Vibe Coding Skills Injection

When the task involves UI design, visual design, or vibe coding:

```
DESIGN MODE ACTIVATED
- Use /design-consultation for complete design system from scratch
- Use /design-shotgun for rapid multi-variant exploration
- Use /design-html for production HTML/CSS generation
- Use /design-review for visual audit + fix loop
- Use /codex for adversarial code review

Process: /design-consultation → /design-shotgun (variants) → /design-html (implementation) → /design-review (audit)
Never ship without /design-review.
```

## Quality & Testing Skills Injection

When the task involves QA, testing, or bug investigation:

```
QA MODE ACTIVATED
- Use /qa for full QA pass (find bugs, fix, re-verify)
- Use /qa-only for report-only QA (no code changes)
- Use /investigate for systematic root-cause debugging
- Use /benchmark for performance regression detection
- Use /cso for OWASP Top 10 + STRIDE security audit

Process: /qa → (fix bugs) → /qa (re-verify) → /qa-only (final report)
Never ship without at least one /qa pass.
```

## Ship & Deploy Skills Injection

When the task involves shipping code, creating PRs, or deploying:

```
SHIP MODE ACTIVATED
- Use /review for pre-landing PR review
- Use /ship for PR creation with tests, changelog, version bump
- Use /land-and-deploy for merge → CI → deploy → verify
- Use /canary for post-deploy monitoring
- Use /landing-report for ship queue dashboard

Process: /review → /ship → /land-and-deploy → /canary
Never skip /review before /ship. Never skip /canary after /land-and-deploy.
```

## Guardrail Skills Injection

When the task might be destructive or needs safety checks:

```
GUARDRAIL MODE ACTIVATED
- Use /careful before destructive commands (rm -rf, DROP TABLE, force-push)
- Use /freeze to lock edits to one directory
- Use /guard to activate both careful + freeze at once
- Use /unfreeze to remove restrictions

Process: /guard → (safe execution) → /unfreeze
Always use /careful when the task involves file deletion, database changes, or git force operations.
```

## Documentation Skills Injection

When the task involves creating or updating documentation:

```
DOCUMENTATION MODE ACTIVATED
- Use /document-generate for Diataxis docs (tutorial/how-to/reference/explanation)
- Use /document-release for post-ship doc updates
- Use /make-pdf for markdown-to-PDF conversion
- Use /learn for managing cross-session knowledge

Process: /document-generate → /make-pdf (if PDF output needed)
Never generate docs without checking existing docs first (/learn).
```

## Browser & Utility Skills Injection

When the task requires web browsing, scraping, or utility operations:

```
BROWSER MODE ACTIVATED
- Use /browse for all web browsing (NEVER mcp__claude-in-chrome__*)
- Use /scrape for data extraction from web pages
- Use /skillify to codify a scrape flow into a permanent skill
- Use /open-gstack-browser for visible browser with sidebar
- Use /pair-agent for remote AI agent + browser pairing
- Use /setup-browser-cookies for authenticated browsing

Process: /setup-browser-cookies (if auth needed) → /browse or /scrape → /skillify (if reusable)
```
