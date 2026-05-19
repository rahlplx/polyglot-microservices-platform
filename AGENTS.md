# AGENTS.md — Systematic Agentic Engineering Process

> Auto-loaded alongside CLAUDE.md. Defines the step-by-step execution process that every AI agent follows for each task.
> **This file is a SESSION RULE.** Phase-aware execution is mandatory. No ad-hoc work.

---

## Core Process: The 7-Phase Agentic Loop

Every task enters this loop. No shortcuts. No skipped phases.

```
┌─────────────────────────────────────────────────────────┐
│  PHASE 1: RECEIVE  →  Classify & scope the task        │
│  PHASE 2: PLAN     →  Break down & estimate tokens     │
│  PHASE 3: SEARCH   →  Find existing code, skills, docs │
│  PHASE 4: EXECUTE  →  Implement with parallel agents   │
│  PHASE 5: VALIDATE →  QA, test, verify outputs         │
│  PHASE 6: COMMIT   →  Update worklog, clean up         │
│  PHASE 7: HANDOFF  →  Report results, next steps       │
└─────────────────────────────────────────────────────────┘
```

### PROJECT_PLAN.md Phase Awareness

The agentic loop operates WITHIN the current project phase from PROJECT_PLAN.md. Before executing any phase of the loop, check the project phase:

| Project Phase | Agentic Loop Behavior |
|---------------|----------------------|
| Phase 0 (Foundation) | Loop focuses on infrastructure verification only |
| Phase 1 (Discovery) | Loop emphasizes RECEIVE + PLAN + SEARCH |
| Phase 2 (Design) | Loop emphasizes SEARCH + EXECUTE (design skills) |
| Phase 3 (Implementation) | Full loop with type-specific execution |
| Phase 4 (Testing) | Loop emphasizes VALIDATE |
| Phase 5 (Ship) | Loop emphasizes EXECUTE (ship) + VALIDATE |
| Phase 6 (Retrospective) | Loop emphasizes COMMIT + HANDOFF |

**Rule:** Read `.claude/session-state.json` for `current_phase` at session start and before each major execution step.

---

## Phase 1: RECEIVE — Classify & Scope

### Step 1.1: Task Classification

Determine the task type using this decision tree:

| If user wants... | Type | Route to |
|---|---|---|
| Reports, articles, PDFs, DOCX, PPT, XLSX as final deliverable | Type 1: Document | `docx`/`pdf`/`xlsx`/`ppt` skill |
| Charts, diagrams, flowcharts, mind maps, PNG visualizations | Type 2: Visualization | `charts` skill |
| Interactive web pages, dashboards, real-time web apps | Type 3: Web Dev | `fullstack-dev` skill → Next.js |
| Data processing, analysis, transformation, calculations | Type 4: Data Processing | Python script |

### Step 1.2: Scope Assessment

- Estimate the number of steps (1-2 = simple, 3+ = complex)
- Identify dependencies (what must complete before what)
- Check for existing work in `worklog.md`
- **Check current project phase** from session state — can this task execute within the current phase?

### Step 1.3: Language Detection

- Match user's input language for ALL outputs
- If ambiguous, default to English but confirm

### Step 1.4: Spec-Driven Gate Check

Before proceeding to PLAN, verify:
- [ ] Task type is classified (Type 1-4)
- [ ] Current project phase allows this type of work
- [ ] Required gstack skills are available for this project phase
- [ ] No gate from a previous project phase is blocking

---

## Phase 2: PLAN — Break Down & Estimate

### Step 2.1: Create TODO List

Use `TodoWrite` with:
- Unique IDs reflecting execution order (1, 2-a, 2-b, 3)
- Clear, actionable descriptions
- Priority levels (high/medium/low)
- Status tracking (pending → in_progress → completed)
- **Project phase annotation** (e.g., "[Phase 3] Implement feature X")

### Step 2.2: Token Budget Estimate

| Task Complexity | Estimated Tokens | Strategy |
|---|---|---|
| Simple (1-2 steps) | < 5K | Execute directly, no subagent |
| Medium (3-5 steps) | 5K-20K | Use 1-2 subagents for parallel work |
| Complex (6+ steps) | 20K+ | Full parallel agent orchestration |

### Step 2.3: Parallelization Plan

Identify which tasks can run concurrently:
- Independent file reads → parallel
- Independent data fetches → parallel
- Dependent operations → sequential
- Subagent tasks → always parallel when possible

### Step 2.4: Spec-Driven Planning

Map TODO items to PROJECT_PLAN.md spec items:
- Each TODO should trace to a spec item in the current project phase
- If a TODO doesn't map to any spec item, it may be out of scope for the current phase
- Log the spec item mapping in the worklog

---

## Phase 3: SEARCH — Find Existing Resources

### Step 3.1: Search Checklist

Before writing any new code or content, check:

- [ ] `worklog.md` — Has a previous agent done related work?
- [ ] `CLAUDE.md` — Are there project-specific rules or configs?
- [ ] `PROJECT_PLAN.md` — What spec items exist for the current phase?
- [ ] `/home/z/my-project/skills/` — Is there an existing skill for this?
- [ ] `~/.claude/skills/gstack/` — Is there a gstack skill for this?
- [ ] Codebase — Use `Grep`/`Glob` to find existing implementations
- [ ] `download/` — Are there reusable assets (images, templates)?

### Step 3.2: Lazy Loading Strategy

Only load what you need:
- Use `Grep` to find relevant lines, then `Read` with offset/limit
- Never read entire files over 500 lines without a targeted reason
- Use `Glob` to find files by pattern before reading
- For gstack skills, invoke only the specific skill needed

### Step 3.3: Context Compression

When passing context to subagents:
- Compress to bullet-point specs (not prose)
- Reference files by path (subagents can read them)
- Include only the Task ID, specific instructions, and output requirements
- Never include full conversation history
- **Include current project phase** so subagent knows its execution context

### Step 3.4: Reliability Check

Before proceeding to EXECUTE, check reliability metrics:
- [ ] Current phase success rate is above 90% (from `.claude/engine/reliability.json`)
- [ ] No pending errors in `.claude/error-pending.json`
- [ ] No consecutive failures on the same spec item

---

## Phase 4: EXECUTE — Implement with Parallel Agents

### Step 4.1: Direct Execution (Simple Tasks)

For simple tasks (1-2 steps):
1. Execute directly in the main agent
2. No subagent overhead
3. Update TODO as you go
4. **Verify execution stays within current project phase scope**

### Step 4.2: Subagent Orchestration (Complex Tasks)

For complex tasks, delegate to specialized subagents:

| Subagent Type | Best For | Tools |
|---|---|---|
| `general-purpose` | Research, multi-step tasks, code search | All |
| `Explore` | Quick codebase searches, file finding | Read, Grep, Glob |
| `Plan` | Architecture decisions, implementation strategy | All |
| `frontend-styling-expert` | CSS, responsive design, animations | All |
| `full-stack-developer` | Next.js 16, React, Prisma, API routes | All |

### Step 4.3: Subagent Communication Protocol

Every subagent prompt MUST include:

```
Task ID: <id from TODO list>
Project Phase: <current phase from PROJECT_PLAN.md>
Context: <compressed bullet-point specs>
Input files: <paths the subagent should read>
Output: <exactly what to produce and where to save it>
Worklog: Read /home/z/my-project/worklog.md before starting.
         Append your work record when done.
Spec Items: <relevant spec items from current PROJECT_PLAN.md phase>
```

### Step 4.4: Parallel Execution Rules

- Launch multiple subagents in a **single message** with multiple `Task` calls
- Each subagent gets a unique Task ID
- Subagents are stateless — they cannot communicate with each other
- Main agent collects all results and synthesizes

### Step 4.5: Spec-Driven Execution

During execution, continuously verify against PROJECT_PLAN.md:
- Each code change or content creation should map to a spec item
- If work drifts outside the current phase's spec items, STOP and reassess
- Use `/careful` (gstack) before any destructive operation
- Use `/freeze` if working on a critical section that shouldn't be modified

---

## Phase 5: VALIDATE — QA, Test, Verify

### Step 5.1: Output Verification

For every generated file:
- [ ] File exists at the expected path
- [ ] File is non-empty (check size > 0)
- [ ] File format is correct (PDF not corrupted, XLSX opens, etc.)
- [ ] Content matches requirements (spot-check key sections)
- [ ] Content matches spec items from PROJECT_PLAN.md

### Step 5.2: Quality Gates by Task Type

| Type | Quality Gate |
|---|---|
| Type 1 (Document) | Page count, font embedding, TOC links, no empty sections |
| Type 2 (Visualization) | Chart renders, labels readable, data matches source |
| Type 3 (Web Dev) | Page loads, no console errors, responsive at 3 breakpoints |
| Type 4 (Data) | Output row count matches, no NaN/null in required fields |

### Step 5.3: gstack QA Integration

For code-related tasks:
- Use `/qa` for full QA pass (find bugs, fix, re-verify)
- Use `/qa-only` for report-only QA (no code changes)
- Use `/review` before merging any PR
- Use `/health` for code quality dashboard
- Use `/benchmark` for performance regression detection

### Step 5.4: Spec Item Verification

After validation, verify each spec item from the current PROJECT_PLAN.md phase:
- [ ] Each spec item has a clear PASS or FAIL status
- [ ] FAIL items have documented reasons and remediation plans
- [ ] All PASS items are logged in worklog.md
- [ ] Phase gate can be assessed: can we advance to the next phase?

---

## Phase 6: COMMIT — Update Worklog & Clean Up

### Step 6.1: Worklog Update

Append to `/home/z/my-project/worklog.md` using this exact format:

```markdown
---
Task ID: <id>
Agent: <agent name>
Project Phase: <current phase from PROJECT_PLAN.md>
Task: <what was asked>

Work Log:
- <concrete step 1>
- <concrete step 2>
- ...

Spec Items Verified:
- <spec_id>: PASS/FAIL — <brief note>

Stage Summary:
- <key results / decisions / produced artifacts>
```

### Step 6.2: TODO Completion

- Mark all completed tasks in `TodoWrite`
- Remove tasks that are no longer relevant
- Add any follow-up tasks discovered during execution

### Step 6.3: Cleanup

- Remove temporary build artifacts from `download/`
- Keep only final deliverables in `download/`
- Verify no files were written outside `/home/z/my-project/`

### Step 6.4: Reliability Update

After each task completion:
- [ ] Update `.claude/engine/reliability.json` with attempt/success/failover counts
- [ ] Check if current phase success rate dropped below 90%
- [ ] If below 90%, flag for process review in Phase 6 of PROJECT_PLAN.md

---

## Phase 7: HANDOFF — Report & Next Steps

### Step 7.1: User Report

Provide a concise summary:
- What was done
- Where the output files are
- Any issues or blockers encountered
- Suggested next steps (if any)
- **Current project phase status** — which spec items passed, which are pending

### Step 7.2: Context Preservation

If the session might continue:
- Ensure worklog.md is up to date
- Note any partial work in the TODO list
- Save any important state to files (not just conversation)
- Update session-state.json with current phase and status

### Step 7.3: Phase Gate Assessment

At handoff, assess whether the current project phase's gate can be passed:
- List all spec items and their PASS/FAIL status
- If all PASS → recommend phase transition (update session-state.json `current_phase`)
- If any FAIL → document what needs to happen before the gate can pass
- Log the gate assessment in worklog.md

---

## Emergency Protocols

### Timeout Protocol

After 2+ consecutive tool call timeouts:
1. Stop retrying immediately
2. Inform the user: "The tool calls are timing out frequently. Please click the **restart** button in the top right corner to restart the session and try again."
3. Do NOT silently retry more than 2 times

### Error Protocol

On any error:
1. Log the error in worklog.md with full context
2. Attempt one retry with adjusted parameters
3. If still failing, report to user with specific error details
4. Never swallow exceptions silently
5. **Update reliability tracker** with the error outcome

### Freeze Protocol

If `/home/z/my-project/.freeze` exists:
1. Halt all file modifications immediately
2. Report the freeze state to the user
3. Suggest using `/unfreeze` (via gstack) to remove the restriction
4. Read-only operations are still allowed

### Failover Protocol

On any trigger failure:
1. **Attempt 1:** Retry with original parameters
2. **Attempt 2:** Retry with adjusted parameters (increased timeout, simplified approach)
3. **Escalate:** Report to user with specific error details
4. **After 2 consecutive failures → STOP** and suggest session restart
5. **Never silently skip** a failed step
6. **Log failover** in reliability tracker

---

## Anti-Patterns (NEVER Do These)

1. **Never build a web page when a document was requested** — Type 1 tasks use skills, not Next.js
2. **Never pass full conversation history to subagents** — They don't have access anyway
3. **Never read entire large files** — Use offset/limit or Grep
4. **Never save files outside `/home/z/my-project/`** — System requirement
5. **Never use `mcp__claude-in-chrome__*` tools** — Use `/browse` from gstack instead
6. **Never skip worklog updates** — Other agents depend on it
7. **Never leave temp files in download/** — Clean up after each task
8. **Never add emoji to code/docs** — Unless user explicitly requests
9. **Never add artificial document endings** — No "------End of Report------"
10. **Never create single-sentence paragraphs** — Minimum 3 sentences per paragraph
11. **Never skip project phase gates** — Every spec item must be verified before advancing
12. **Never execute outside the current project phase** — Stay within phase scope
13. **Never ignore reliability alerts** — Below 90% success rate needs attention
14. **Never bypass the auto-trigger engine** — Every action flows through certified triggers
