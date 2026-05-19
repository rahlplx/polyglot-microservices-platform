# PROJECT_PLAN.md — Phased Execution Blueprint with Spec-Driven gstack Workflows

> This document is the master execution plan. Every AI session reads this alongside CLAUDE.md and AGENTS.md.
> Phases are sequential. Each phase has spec-driven gates. No phase starts until the previous phase passes its gate.
> All execution flows through the auto-trigger engine. No ad-hoc work.

---

## Phase 0: Foundation & Infrastructure

**Status:** COMPLETE
**Gate:** All infrastructure components verified and operational
**Duration target:** 1 session

### Spec-Driven Requirements

| ID | Requirement | Verification | Status |
|----|-------------|-------------|--------|
| 0.1 | gstack v1.40.0.0 installed with team mode | `ls ~/.claude/skills/gstack/setup && ./setup --team` | PASS |
| 0.2 | CLAUDE.md auto-loads with gstack rules | Read at session start, contains gstack section | PASS |
| 0.3 | AGENTS.md defines 7-phase agentic loop | File exists with all 7 phases documented | PASS |
| 0.4 | Auto-trigger engine operational | `bash .claude/engine/trigger-engine.sh session_start` exits 0 | PASS |
| 0.5 | Failover system with 16 failover actions | `bash .claude/engine/failover.sh halt_and_report test` exits 0 | PASS |
| 0.6 | Context auto-injection templates exist | 4 templates in `.claude/context/` | PASS |
| 0.7 | Token efficiency config loaded | `.claude/config/token-efficiency.json` readable | PASS |
| 0.8 | Hook scripts (session-init, pre-exec, post-exec) | All 3 scripts executable | PASS |
| 0.9 | gstack team mode enforcement hook | `.claude/hooks/check-gstack.sh` blocks without gstack | PASS |
| 0.10 | Reliability tracker initialized | `.claude/engine/reliability.json` exists | PASS |

### Auto-Trigger Mapping

```
session_start → check_core_files → verify_gstack → check_freeze → inject_context(session) → init_reliability
```

### Certified gstack Skills for Phase 0

- `/browse` — Verify web-accessible resources
- `/health` — Code quality dashboard
- `/careful` — Safe infrastructure changes
- `/freeze` / `/unfreeze` — Codebase locking

---

## Phase 1: Discovery & Specification

**Status:** COMPLETE (8/8 spec items PASS — Gate 1.8 Review Gauntlet PASSED)
**Gate:** Specification document generated and reviewed via /office-hours
**Duration target:** 1-2 sessions per feature
**Canonical spec:** `/home/z/my-project/SPECIFICATION.md`

### Spec-Driven Requirements

| ID | Requirement | Verification | Status |
|----|-------------|-------------|--------|
| 1.1 | Problem statement documented with premises | 4 premises in SPECIFICATION.md | PASS |
| 1.2 | Alternatives analyzed (min 3 options) | 3 options in SPECIFICATION.md, Option C selected | PASS |
| 1.3 | Success criteria defined with measurable outcomes | 9 criteria (SC-1 through SC-9) with targets | PASS |
| 1.4 | Task classification completed (Type 1-4) | All 4 types mapped across phases | PASS |
| 1.5 | Token budget estimated for implementation | 150K+ tokens across 6 phases | PASS |
| 1.6 | Dependencies identified and ordered | 6-phase timeline + dependency chain | PASS |
| 1.7 | Risk assessment with mitigation strategies | 8 risks with probability/impact/mitigation | PASS |
| 1.8 | Review gauntlet passed (CEO + Eng + Design + DX) | CEO(4/4)+Eng(6/6)+Sec(4/4)+DX(4/4) PASS | PASS |

### Auto-Trigger Mapping

```
task_receive → classify_task → create_todo → estimate_budget → inject_context(task) →
  → route_to_workflow → skill_invoke(/office-hours) → /plan-ceo-review → /plan-eng-review → /plan-design-review
```

### Spec-Driven Workflow

```
User Request
    ↓
[RECEIVE] Classify task type (Type 1-4)
    ↓
[PLAN] Break into spec items, create TODO
    ↓
[SEARCH] Check worklog, existing code, gstack skills
    ↓
[SPECIFY] Run /office-hours → produce problem statement + premises + alternatives
    ↓
[REVIEW] Run /autoplan or individual reviews (CEO → Eng → Design → DX)
    ↓
[GATE] All reviews pass? → YES: proceed to Phase 2
                           → NO: revise spec, re-review
```

### Certified gstack Skills for Phase 1

- `/office-hours` — Reframe product ideas, produce design doc (MANDATORY FIRST)
- `/autoplan` — Full review gauntlet
- `/plan-ceo-review` — Strategic review
- `/plan-eng-review` — Engineering feasibility
- `/plan-design-review` — UX/design review
- `/plan-devex-review` — Developer experience review
- `/plan-tune` — Adjust AskUserQuestion sensitivity
- `/design-consultation` — Design system from scratch

### Context Auto-Injection

At `task_receive` trigger:
- Inject `task_context.md` (classification tree, routing map, token budgets)
- Inject skill-specific context from `skill_injections.md` (Planning & Review section)
- Inject ETHOS preamble (Boil the Lake, Search Before Building, The Golden Age)

---

## Phase 2: Design & Polyglot Architecture Mapping

**Status:** IN PROGRESS (0/10 spec items PASS)
**Gate:** Design system documented, architecture reviewed via /design-review, all 10 spec items PASS
**Duration target:** 1-2 sessions per feature
**Design spec:** `/home/z/my-project/PHASE2_DESIGN_SPEC.md`
**Worker agent instructions:** `/home/z/my-project/AGENTS.md` (Phase 2 section)

### Spec-Driven Requirements

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
| 2.9 | Git-Flow branching strategy defined | Branching model documented + CONTRIBUTING.md | PENDING |
| 2.10 | Worker agent instructions generated | AGENTS.md Phase 2 section complete | PENDING |

### Auto-Trigger Mapping

```
pre_execution → check_freeze → verify_output_dir → inject_context(execution) →
  skill_invoke(/design-consultation) → /design-shotgun → /design-html → /design-review →
  post_execution → validate_output → update_worklog → cleanup
```

### Spec-Driven Workflow

```
Phase 1 Specification (approved)
    ↓
[DESIGN] /design-consultation → create design system
    ↓
[EXPLORE] /design-shotgun → generate 3+ variants
    ↓
[SELECT] Choose best variant based on reviews
    ↓
[IMPLEMENT] /design-html → production HTML/CSS
    ↓
[AUDIT] /design-review → visual audit + fix loop
    ↓
[GATE] Design review passes? → YES: proceed to Phase 3
                              → NO: revise design, re-audit
```

### Certified gstack Skills for Phase 2

- `/design-consultation` — Build complete design system (MANDATORY FIRST)
- `/design-shotgun` — Rapid multi-variant exploration
- `/design-html` — Production HTML/CSS from design description
- `/design-review` — Visual audit + fix loop
- `/cso` — OWASP Top 10 + STRIDE security audit

### Context Auto-Injection

At `skill_invoke` trigger:
- Inject `skill_injections.md` (Design & Vibe Coding section)
- Inject previous phase's specification as context
- Inject ETHOS preamble

---

## Phase 3: Implementation & Vibe Coding

**Status:** PENDING
**Gate:** Code implemented, /qa pass completed, /review approved
**Duration target:** 2-4 sessions per feature

### Spec-Driven Requirements

| ID | Requirement | Verification | Status |
|----|-------------|-------------|--------|
| 3.1 | Code follows design specification | Implementation matches Phase 2 design | PENDING |
| 3.2 | All spec items implemented (Boil the Lake) | No 90% shortcuts, complete implementation | PENDING |
| 3.3 | Type system enforced (TypeScript where applicable) | No `any` types without justification | PENDING |
| 3.4 | Error handling comprehensive | All error paths have handlers | PENDING |
| 3.5 | /qa pass completed with zero open bugs | /qa → fix → /qa → zero bugs | PENDING |
| 3.6 | /review approved (code quality) | /review passes without blocking issues | PENDING |
| 3.7 | Token efficiency maintained | No unnecessary file reads, lazy skill loading | PENDING |
| 3.8 | Worklog updated after each subtask | Every agent appends to worklog.md | PENDING |
| 3.9 | Security scan passed (if applicable) | /cso audit completed for web-facing code | PENDING |
| 3.10 | Performance benchmarks met | /benchmark shows no regression | PENDING |

### Auto-Trigger Mapping

```
pre_execution → check_freeze → verify_output_dir → inject_context(execution) →
  → implement via certified workflow (Type-dependent) →
  → skill_invoke(/qa) → /review → /benchmark →
  → post_execution → validate_output → update_worklog → cleanup → update_reliability
```

### Spec-Driven Workflow

```
Phase 2 Design (approved)
    ↓
[IMPLEMENT] Execute via certified workflow:
  Type 1: pdf/docx/xlsx/ppt skill
  Type 2: charts skill (matplotlib/seaborn/ECharts/D3/Mermaid/Playwright+CSS)
  Type 3: fullstack-dev skill → Next.js 16 + React + Prisma
  Type 4: Python script (pandas/numpy)
    ↓
[QA] /qa → find bugs → fix → /qa (re-verify) → zero bugs
    ↓
[REVIEW] /review → code quality check → fix issues → re-review
    ↓
[BENCHMARK] /benchmark → performance check (for Type 3/4)
    ↓
[GATE] QA + Review pass? → YES: proceed to Phase 4
                          → NO: fix issues, re-qa, re-review
```

### Certified gstack Skills for Phase 3

- **Type 1:** `pdf`, `docx`, `xlsx`, `ppt` (system skills)
- **Type 2:** `charts` (system skill)
- **Type 3:** `fullstack-dev` (system skill) + `/design-html`, `/qa`, `/review`, `/ship`
- **Type 4:** Python scripting + `/investigate`, `/benchmark`, `/health`
- **Cross-cutting:** `/qa`, `/qa-only`, `/review`, `/codex`, `/careful`, `/freeze`

### Context Auto-Injection

At `skill_invoke` trigger:
- Inject `skill_injections.md` (category-specific section)
- Inject design specification from Phase 2
- Inject implementation checklist from Phase 1 spec
- Inject ETHOS preamble + "Boil the Lake" emphasis

---

## Phase 4: Testing & Validation

**Status:** PENDING
**Gate:** All test suites pass, benchmarks green, security scan clean
**Duration target:** 1-2 sessions per feature

### Spec-Driven Requirements

| ID | Requirement | Verification | Status |
|----|-------------|-------------|--------|
| 4.1 | Unit tests cover critical paths | Coverage > 80% for new code | PENDING |
| 4.2 | Integration tests cover user flows | End-to-end scenarios pass | PENDING |
| 4.3 | /qa full pass with zero open P0/P1 bugs | QA report shows no critical issues | PENDING |
| 4.4 | /benchmark performance regression check | No regression from baseline | PENDING |
| 4.5 | /cso security audit clean (if applicable) | No high/critical findings | PENDING |
| 4.6 | Cross-browser/device testing (Type 3) | 3 breakpoints pass | PENDING |
| 4.7 | Accessibility testing (WCAG 2.1 AA) | Automated + manual a11y check | PENDING |
| 4.8 | Document quality gates passed (Type 1) | Page count, fonts, TOC verified | PENDING |

### Auto-Trigger Mapping

```
pre_execution → check_freeze → verify_output_dir →
  → skill_invoke(/qa) → /benchmark → /cso →
  → validate_output → update_worklog → update_reliability →
  → post_execution → cleanup
```

### Spec-Driven Workflow

```
Phase 3 Implementation (QA + Review passed)
    ↓
[TEST] /qa → full QA pass
    ↓
[PERF] /benchmark → performance regression check
    ↓
[SEC] /cso → security audit (if web-facing)
    ↓
[VALIDATE] Cross-browser, a11y, document quality
    ↓
[GATE] All tests pass? → YES: proceed to Phase 5
                        → NO: fix → re-test from top
```

### Certified gstack Skills for Phase 4

- `/qa` — Full QA pass (find bugs, fix, re-verify)
- `/qa-only` — Report-only QA (no code changes)
- `/benchmark` — Performance regression detection
- `/benchmark-models` — Cross-model benchmark
- `/cso` — OWASP Top 10 + STRIDE security audit
- `/investigate` — Deep-dive debugging
- `/health` — Code quality dashboard

---

## Phase 5: Ship & Deploy

**Status:** PENDING
**Gate:** PR merged, deployed, production health verified
**Duration target:** 1 session per feature

### Spec-Driven Requirements

| ID | Requirement | Verification | Status |
|----|-------------|-------------|--------|
| 5.1 | /review approved before merge | /review passes with no blocking issues | PENDING |
| 5.2 | /ship creates PR with tests + changelog | PR exists with all required sections | PENDING |
| 5.3 | CI/CD pipeline passes | All automated checks green | PENDING |
| 5.4 | /land-and-deploy completes | Merged, CI passes, deployed | PENDING |
| 5.5 | Production health verified | /canary monitoring active | PENDING |
| 5.6 | /document-release updates docs | All docs reflect shipped changes | PENDING |
| 5.7 | Version bumped correctly | Semantic versioning followed | PENDING |
| 5.8 | Changelog entry added | User-facing changes documented | PENDING |

### Auto-Trigger Mapping

```
pre_execution → check_freeze →
  → skill_invoke(/review) → /ship → /land-and-deploy → /canary →
  → /document-release →
  → post_execution → validate_deployment → update_worklog → update_reliability → cleanup
```

### Spec-Driven Workflow

```
Phase 4 Testing (all pass)
    ↓
[REVIEW] /review → pre-landing review
    ↓
[SHIP] /ship → create PR with tests + changelog + version bump
    ↓
[DEPLOY] /land-and-deploy → merge → CI → deploy
    ↓
[MONITOR] /canary → verify production health
    ↓
[DOCUMENT] /document-release → update all docs
    ↓
[GATE] Production healthy? → YES: proceed to Phase 6
                           → NO: rollback, investigate
```

### Certified gstack Skills for Phase 5

- `/review` — Pre-landing PR review (MANDATORY before ship)
- `/ship` — Create PR with tests, changelog, version bump
- `/land-and-deploy` — Merge → CI → Deploy → Verify
- `/canary` — Post-deploy canary monitoring
- `/landing-report` — Ship queue dashboard
- `/document-release` — Post-ship doc updates

---

## Phase 6: Retrospective & Knowledge Capture

**Status:** PENDING
**Gate:** Retrospective completed, knowledge stored for future sessions
**Duration target:** 1 session per milestone

### Spec-Driven Requirements

| ID | Requirement | Verification | Status |
|----|-------------|-------------|--------|
| 6.1 | /retro completed with per-person breakdowns | Retrospective document generated | PENDING |
| 6.2 | Shipping streaks tracked | Streak data in retro output | PENDING |
| 6.3 | Lessons learned documented | Key takeaways in worklog | PENDING |
| 6.4 | /learn captures cross-session knowledge | Knowledge stored for future sessions | PENDING |
| 6.5 | /context-save preserves working state | Context file written for session resume | PENDING |
| 6.6 | Reliability metrics reviewed | Success rate, failover frequency analyzed | PENDING |
| 6.7 | Token efficiency metrics reviewed | Context usage, waste percentage analyzed | PENDING |
| 6.8 | Process improvements identified | At least 1 improvement per retrospective | PENDING |

### Auto-Trigger Mapping

```
pre_execution →
  → skill_invoke(/retro) → /learn → /context-save →
  → review_reliability_metrics → review_token_metrics →
  → post_execution → update_worklog → update_reliability → cleanup
```

### Spec-Driven Workflow

```
Phase 5 Ship (complete)
    ↓
[RETRO] /retro → per-person breakdowns, shipping streaks
    ↓
[LEARN] /learn → capture cross-session knowledge
    ↓
[SAVE] /context-save → preserve working context
    ↓
[METRICS] Review reliability stats, token efficiency, failover frequency
    ↓
[IMPROVE] Identify process improvements for next cycle
    ↓
[GATE] Retrospective complete? → YES: cycle back to Phase 1 for next feature
                                → NO: complete retrospective
```

### Certified gstack Skills for Phase 6

- `/retro` — Retrospective with breakdowns and streaks
- `/learn` — Cross-session knowledge management
- `/context-save` — Save working context for resume
- `/context-restore` — Resume from saved context
- `/skillify` — Codify successful flows into permanent skills

---

## Cross-Phase Rules

### 1. No Phase Skipping

Every feature MUST go through all phases sequentially. No shortcuts. The auto-trigger engine enforces this by checking the current phase in session state before allowing execution.

### 2. Gate Enforcement

Each phase has a gate. The gate is a set of spec items that MUST all be PASS before the next phase begins. The trigger engine checks gate status at `pre_execution`.

### 3. Phase State Persistence

Current phase is stored in session state:

```json
{
  "current_phase": 3,
  "phase_status": {
    "0": "complete",
    "1": "complete",
    "2": "complete",
    "3": "in_progress",
    "4": "pending",
    "5": "pending",
    "6": "pending"
  }
}
```

### 4. Failover Per Phase

Each phase has its own failover chain, but all follow the 2-retry-then-escalate rule:

```
Failure → Retry (original) → Retry (adjusted) → Escalate → Error file
```

After 2 consecutive failures on the SAME spec item → STOP and suggest session restart.

### 5. Context Auto-Injection Per Phase

| Phase | Primary Context | Additional Injection |
|-------|----------------|---------------------|
| 0 | session_context.md | Infrastructure checklist |
| 1 | task_context.md | Planning & Review skill injections |
| 2 | execution_context.md | Design & Vibe Coding skill injections |
| 3 | execution_context.md | Category-specific skill injections |
| 4 | execution_context.md | Quality & Testing skill injections |
| 5 | execution_context.md | Ship & Deploy skill injections |
| 6 | execution_context.md | Documentation & Learning skill injections |

### 6. Reliability Tracking Per Phase

Every spec item verification updates the reliability tracker:

```json
{
  "phase_0": {"attempts": 10, "successes": 10, "failovers_triggered": 0, "success_rate": "100%"},
  "phase_1": {"attempts": 0, "successes": 0, "failovers_triggered": 0, "success_rate": "N/A"}
}
```

Target: >95% success rate per phase. Below 90% triggers process review in Phase 6.

---

## Workflow Quick Reference

### How AI Agents Use This Document

1. **At session start:** Read PROJECT_PLAN.md alongside CLAUDE.md and AGENTS.md
2. **Check current phase:** Read `.claude/session-state.json` for `current_phase`
3. **Execute within phase:** Only work on spec items for the current phase
4. **Verify gate:** All spec items PASS → advance phase in session state
5. **Update worklog:** Append phase transitions and spec item completions
6. **Update reliability:** Log attempts/successes/failovers for each spec item

### Phase Transition Protocol

```
All spec items PASS →
  1. Update session-state.json: current_phase = next_phase
  2. Append to worklog.md: "Phase X → Phase Y transition"
  3. Fire pre_execution trigger for new phase
  4. Load context template for new phase
  5. Inject ETHOS preamble for new phase skills
  6. Begin executing spec items for new phase
```
