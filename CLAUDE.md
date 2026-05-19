# CLAUDE.md — Project Configuration & AI Automation Blueprint

> Auto-loaded by Claude Code at session start. Every AI agent reads this first.
> **This file is a SESSION RULE.** It is non-negotiable. Every AI action must comply.

---

## 1. gstack — AI Automation & Vibe Coding Skills

Gstack is the **primary AI skill system** for this project. It provides structured, specialist-driven workflows for the entire software lifecycle: planning, vibe coding, testing, reviewing, shipping, and deploying.

**Browser rule (CRITICAL):** Always use the `/browse` skill from gstack for all web browsing. **NEVER** use `mcp__claude-in-chrome__*` tools — they are slow, unreliable, and not what this project uses.

### Planning & Review Skills

| Skill | Purpose |
|-------|---------|
| `/office-hours` | Reframe product ideas before writing code. Design doc with problem statement, premises, alternatives. |
| `/autoplan` | Full review gauntlet: CEO + eng + design + DX + codex adversarial. |
| `/plan-ceo-review` | CEO-level strategic review of a plan. |
| `/plan-eng-review` | Engineering feasibility, data flow, edge cases, and test architecture. |
| `/plan-design-review` | Design and UX review, rate each dimension 0-10. |
| `/plan-devex-review` | Developer experience review: TTHW, magical moments, friction points. |
| `/plan-tune` | Self-tune AskUserQuestion sensitivity per question. |
| `/design-consultation` | Build a complete design system from scratch. |

### Vibe Coding & Design Skills

| Skill | Purpose |
|-------|---------|
| `/design-consultation` | Get a design consultation for a feature or change. |
| `/design-shotgun` | Rapid design exploration, generate multiple approaches quickly. |
| `/design-html` | Generate production-quality HTML/CSS from a design description. |
| `/design-review` | Review existing designs for issues, live-site visual audit + fix loop. |
| `/codex` | Adversarial code review and edge-case hunting via OpenAI Codex. |

### Code Review & Ship Skills

| Skill | Purpose |
|-------|---------|
| `/review` | Full PR review before merging. Finds bugs that pass CI but break in prod. |
| `/ship` | Create a PR with tests, changelog, and version bump. Workspace-aware queue. |
| `/land-and-deploy` | Merge PR, wait for CI, deploy, verify production health. |
| `/canary` | Set up and manage canary deployments. |
| `/landing-report` | Read-only dashboard for the workspace-aware ship queue. |

### Quality & Testing Skills

| Skill | Purpose |
|-------|---------|
| `/qa` | Full QA pass: open browser, find bugs, fix them, re-verify. |
| `/qa-only` | QA only mode — identify issues without fixing them. |
| `/benchmark` | Performance regression detection (page load, Core Web Vitals). |
| `/benchmark-models` | Cross-model benchmark for skills (Claude, GPT, Gemini side-by-side). |
| `/investigate` | Deep-dive investigation into a bug or incident. Systematic root-cause. |

### Deployment & Infra Skills

| Skill | Purpose |
|-------|---------|
| `/setup-deploy` | Set up deployment configuration (Fly.io, Render, Vercel, etc.). |
| `/setup-browser-cookies` | Configure browser cookies for authenticated testing. |
| `/setup-gbrain` | Set up gbrain integration for cross-machine session memory sync. |
| `/sync-gbrain` | Keep gbrain current with this repo's code. |

### Guardrails & Control Skills

| Skill | Purpose |
|-------|---------|
| `/careful` | Enable careful mode — extra verification before destructive actions. |
| `/freeze` | Freeze the codebase, prevent changes. Hard block, not just a warning. |
| `/guard` | Activate both careful + freeze at once. |
| `/unfreeze` | Remove directory edit restrictions. |

### Documentation & Learning Skills

| Skill | Purpose |
|-------|---------|
| `/document-release` | Update all docs to match what you just shipped. |
| `/document-generate` | Generate Diataxis docs (tutorial/how-to/reference/explanation) from code. |
| `/retro` | Run a retrospective with per-person breakdowns and shipping streaks. |
| `/learn` | Learn from a codebase or pattern. Manage cross-session knowledge. |
| `/skillify` | Codify a successful browse/scrape flow into a permanent browser-skill. |

### Browsing & Utilities Skills

| Skill | Purpose |
|-------|---------|
| `/browse` | Headless browser — real Chromium, real clicks, ~100ms/command. **ALWAYS prefer this.** |
| `/open-gstack-browser` | Launch the visible GStack Browser with sidebar + stealth. |
| `/connect-chrome` | Alias for `/open-gstack-browser` (backwards compat). |
| `/pair-agent` | Pair a remote AI agent (OpenClaw, Codex, etc.) with your browser. |
| `/scrape` | Pull data from a web page. First call prototypes, codified call ~200ms. |
| `/cso` | OWASP Top 10 + STRIDE security audit. |
| `/health` | Code quality dashboard (type checker, linter, tests, dead code). |
| `/context-save` | Save working context (git state, decisions, remaining work). |
| `/context-restore` | Resume from a saved context, even across workspaces. |
| `/gstack-upgrade` | Upgrade gstack to the latest version. |

---

## 2. Token Efficiency System

### Context Budget Rules

- **Hard limit:** Never exceed 60% of context window for skill loading. Reserve 40% for actual work.
- **Lazy skill loading:** Only load the SKILL.md for the skill being invoked. Never preload all skills.
- **Worklog compression:** Keep `/home/z/my-project/worklog.md` entries under 200 words per task. Use structured format only.
- **File reading:** Always use `offset` + `limit` for files over 500 lines. Never read entire large files.
- **Search before read:** Use `Grep` and `Glob` to locate relevant sections before using `Read`.

### Prompt Compression

- When invoking subagents, compress context to **only what's needed** for that specific subtask.
- Never pass full conversation history to subagents — they don't have access to it anyway.
- Use bullet-point specs instead of prose for subagent prompts.
- Reference files by path, not by content, when the subagent can read them.

### Output Efficiency

- No redundant summaries. If a tool output shows the result, don't restate it in text.
- Batch related tool calls in a single message (parallel execution).
- Use `TodoWrite` for tracking, not conversation text.
- Prefer code comments over explanation text for implementation details.

---

## 3. Auto-Trigger Engine & Failover System

The auto-trigger engine is the brain of the agentic system. Every AI action MUST flow through certified triggers with failover chains. No ad-hoc execution.

**Engine location:** `/home/z/my-project/.claude/engine/trigger-engine.sh`
**Failover system:** `/home/z/my-project/.claude/engine/failover.sh`
**Trigger config:** `/home/z/my-project/.claude/engine/triggers.json`

### 7 Certified Triggers (in execution order)

| # | Trigger | When | Auto? | Blocking? |
|---|---------|------|-------|-----------|
| 1 | `session_start` | Every session start | YES | YES |
| 2 | `task_receive` | New task received | YES | NO |
| 3 | `pre_execution` | Before any execution | YES | YES |
| 4 | `skill_invoke` | gstack skill called | NO | NO |
| 5 | `subagent_dispatch` | Subagent launched | NO | NO |
| 6 | `post_execution` | After execution | YES | NO |
| 7 | `error_recovery` | On any error | YES | NO |

### Trigger → Action → Failover Chain

Every trigger has a defined action sequence and failover chain:

```
Trigger fires → Action 1 → (fail?) → Failover A → Action 2 → (fail?) → Failover B → ... → Escalate to user
```

**session_start** failovers:
- gstack missing → auto_install_gstack
- CLAUDE.md missing → generate_default_claude_md
- freeze active → halt_and_report

**task_receive** failovers:
- classification failed → default_to_type1
- TODO creation failed → proceed_without_todo

**pre_execution** failovers:
- freeze active → halt_and_report
- output dir missing → create_output_dir
- worklog conflict → warn_and_proceed

**skill_invoke** failovers:
- skill not found → fallback_to_generic
- skill load error → retry_once_then_generic

**subagent_dispatch** failovers:
- context too large → truncate_to_essentials (max 8000 tokens)
- subagent timeout → retry_with_simpler_prompt (max 1 retry)

**post_execution** failovers:
- output missing → log_error_and_report
- worklog update failed → retry_once
- cleanup failed → log_warning_only

**error_recovery** failovers:
- escalation failed → write_error_file to `.claude/error-pending.json`
- log failed → write_stderr

### The 2-Retry-Then-Escalate Rule

On ANY failure:
1. **Attempt 1:** Retry with original parameters
2. **Attempt 2:** Retry with adjusted parameters (increased timeout, simplified approach)
3. **Escalate:** Report to user with specific error details
4. **After 2 consecutive failures → STOP** and suggest: "Please click the restart button to restart the session."
5. **Never silently skip** a failed step

### Context Auto-Injection Pipeline

Context is automatically injected at each trigger point from templates:

| Trigger | Context Template | What It Injects |
|---------|-----------------|----------------|
| session_start | `session_context.md` | AI identity, project paths, gstack rules, ETHOS principles, freeze state |
| task_receive | `task_context.md` | Classification decision tree, workflow routing map, token budgets, skill mapping |
| pre_execution | `execution_context.md` | Safety checklist, skill loading protocol, skill chain rules, subagent dispatch protocol |
| skill_invoke | `skill_injections.md` | Category-specific prompt injections (Planning/Design/QA/Ship/Guardrail/Doc/Browser) |

**Context template location:** `/home/z/my-project/.claude/context/`

### Workflow Router — AI Only Triggers Into Certified Workflows

The workflow router ensures the AI NEVER takes an ad-hoc path. Every task MUST be classified and routed:

| Task Type | Trigger Patterns | Certified gstack Skills | System Skill | Fallback |
|-----------|-----------------|------------------------|-------------|----------|
| Type 1: Document | "generate document", "create report", "PDF", "docx", "xlsx", "ppt" | /office-hours, /design-consultation, /document-generate | pdf, docx, xlsx, ppt | pdf |
| Type 2: Visualization | "chart", "diagram", "flowchart", "mind map", "plot" | /design-consultation, /design-shotgun, /design-review | charts | charts |
| Type 3: Web Dev | "webpage", "dashboard", "interactive", "Next.js" | /design-html, /design-review, /qa, /review | fullstack-dev | fullstack-dev |
| Type 4: Data | "process data", "analyze", "transform", "calculate" | /investigate, /benchmark, /health | (python) | python |

**Ambiguity resolution:** If task type is unclear → Ask user: "Do you want a document with charts, or an interactive web page?"
**Default route:** Type 1 (Document Creation) if classification fails.

### Certified Skill Chains

These are the ONLY approved skill sequences. No custom chains:

| Workflow | Chain | Rule |
|----------|-------|------|
| Document with design | /office-hours → pdf | Design first, generate second |
| Document with review | pdf → /review | Generate, then review |
| Web app full cycle | /design-html → fullstack-dev → /qa → /ship | Design → Build → QA → Ship |
| Code review only | /review | Standalone |
| QA pass | /qa | Standalone |
| Deploy pipeline | /ship → /land-and-deploy → /canary | Ship → Deploy → Monitor |

### ETHOS Auto-Injection (Every Skill)

Every gstack skill invocation MUST include the ETHOS preamble:
1. **Boil the Lake** — Do the complete thing, not the 90% shortcut. Completeness is cheap with AI.
2. **Search Before Building** — Check existing solutions first. The cost of not checking is reinventing something worse.
3. **The Golden Age** — One person + AI = what used to take 20 people. The engineering barrier is gone.

---

## 4. PROJECT_PLAN.md — Phased Execution (SESSION RULE)

**PROJECT_PLAN.md is a required companion document.** It defines 7 execution phases (0-6) with spec-driven gates. No phase starts until the previous phase's gate passes. The auto-trigger engine enforces phase-aware dispatch.

### Phase Overview

| Phase | Name | Gate | Key gstack Skills |
|-------|------|------|-------------------|
| 0 | Foundation | All infra verified | /browse, /health, /careful |
| 1 | Discovery & Spec | /office-hours + reviews pass | /office-hours, /autoplan, /plan-*-review |
| 2 | Design & Architecture | /design-review passes | /design-consultation, /design-shotgun, /design-html |
| 3 | Implementation & Coding | /qa + /review pass | Type-specific skills + /qa, /review |
| 4 | Testing & Validation | All tests pass | /qa, /benchmark, /cso |
| 5 | Ship & Deploy | Production healthy | /review, /ship, /land-and-deploy, /canary |
| 6 | Retrospective & Knowledge | Retro complete | /retro, /learn, /context-save |

### Phase Session Rules

1. **Read phase state at session start:** Check `.claude/session-state.json` for `current_phase`
2. **Only execute within current phase:** No jumping ahead. Gate must pass first.
3. **Spec items are atomic:** Each spec item in PROJECT_PLAN.md must be verified PASS or FAIL
4. **Phase transitions are logged:** Append transition to worklog.md
5. **Reliability is tracked per phase:** Below 90% success rate triggers process review
6. **Context injection is phase-aware:** Each phase injects its own context template

---

## 5. Project Structure

```
/home/z/my-project/
├── CLAUDE.md              # This file — AI agent config, gstack rules, auto-trigger spec (SESSION RULE)
├── AGENTS.md              # 7-Phase agentic loop, subagent protocol, anti-patterns (SESSION RULE)
├── PROJECT_PLAN.md        # Phased execution blueprint with spec-driven gates (SESSION RULE)
├── worklog.md             # Shared worklog across all agents (append only)
├── .freeze                # Freeze marker (exists = codebase frozen)
├── .claude/
│   ├── skills/
│   │   └── gstack -> ~/.claude/skills/gstack  # gstack symlink
│   ├── engine/            # Auto-trigger engine & failover system
│   │   ├── trigger-engine.sh   # Master trigger dispatcher v3.0 (7 triggers, phase-aware)
│   │   ├── failover.sh         # Failover chain executor (16 failover actions)
│   │   ├── triggers.json       # Trigger config, workflow router, context templates
│   │   └── reliability.json    # Per-phase success rates, failover counts, alerts
│   ├── context/           # Auto-injection context templates
│   │   ├── session_context.md    # Session start: AI identity, ETHOS, project paths, phase state
│   │   ├── task_context.md       # Task receive: classification, routing, budgets, phase spec
│   │   ├── execution_context.md  # Pre-exec: safety checks, skill chains, phase dispatch
│   │   └── skill_injections.md   # Skill invoke: per-category + per-phase prompt injections
│   ├── config/
│   │   └── token-efficiency.json # Token budget, lazy loading, parallelization
│   ├── hooks/             # Hook scripts (check-gstack, session-init, pre-exec, post-exec)
│   ├── settings.json      # gstack team mode enforcement hook
│   └── session-state.json # Cross-session state + phase tracking
├── skills/                # Project-level custom skills
│   ├── coding-agent/      # Coding agent skill with memory & planning
│   ├── ui-ux-pro-max/     # UI/UX design expertise skill
│   └── ...                # Other project skills
└── download/              # All deliverable outputs go here
```

### File Management Rules

- **ALL output files** → `/home/z/my-project/download/`
- **ALL worklog entries** → `/home/z/my-project/worklog.md` (append only)
- **NO temp files** left in download/ after task completion
- **NO files** saved outside `/home/z/my-project/`

---

## 6. Agentic Engineering Principles

1. **Search Before Building** — Always check existing code, skills, and worklog before starting new work.
2. **One Task Per Agent** — Each subagent handles exactly one well-defined subtask.
3. **Structured Communication** — Agents communicate via worklog.md, not conversation.
4. **Fail Fast, Fail Loud** — Never silently swallow errors. Always report and escalate.
5. **Token Awareness** — Every read, every search, every subagent call costs tokens. Be efficient.
6. **Idempotent Operations** — Every script and operation must be safe to re-run.
7. **Atomic Commits** — Each commit should be a single logical change.

---

## 7. Language & Consistency

- **Language:** Match the user's input language for all responses, documents, and outputs.
- **Chinese plots:** Use `Noto Sans SC` + `DejaVu Sans` fallback for matplotlib.
- **Document fonts:** Use `LibSerif` (headings) + `Carlito` (body) for PDF generation.
- **No emoji** in code files or documents unless explicitly requested.

## gstack (REQUIRED — global install)

**Before doing ANY work, verify gstack is installed:**

```bash
test -d ~/.claude/skills/gstack/bin && echo "GSTACK_OK" || echo "GSTACK_MISSING"
```

If GSTACK_MISSING: STOP. Do not proceed. Tell the user:

> gstack is required for all AI-assisted work in this repo.
> Install it:
> ```bash
> git clone --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
> cd ~/.claude/skills/gstack && ./setup --team
> ```
> Then restart your AI coding tool.

Do not skip skills, ignore gstack errors, or work around missing gstack.

Using gstack skills: After install, skills like /qa, /ship, /review, /investigate,
and /browse are available. Use /browse for all web browsing.
Use ~/.claude/skills/gstack/... for gstack file paths (the global path).
