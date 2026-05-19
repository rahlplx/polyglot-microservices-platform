# CLAUDE.md — Project Configuration & AI Automation Blueprint

> Auto-loaded by Claude Code at session start. Every AI agent reads this first.

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

## 3. Auto-Hooks & Execution Triggers

### Session Start Auto-Actions

On every new session, the AI agent MUST:

1. **Read this file** (`CLAUDE.md`) — it's auto-loaded by Claude Code.
2. **Read `AGENTS.md`** — for the systematic agentic engineering process.
3. **Check `worklog.md`** — understand what previous agents have done.
4. **Verify gstack** — run `ls ~/.claude/skills/gstack/setup` to confirm gstack is installed.
5. **Check for frozen state** — if `/home/z/my-project/.freeze` exists, halt and report.

### Pre-Execution Hooks

Before executing any task, the AI agent MUST:

1. **Classify the task** using the Type system (Type 1: Document, Type 2: Visualization, Type 3: Web Dev, Type 4: Data Processing).
2. **Create a TODO list** with `TodoWrite` for any task with 3+ steps.
3. **Estimate token budget** — if the task requires reading multiple large files, plan which sections are needed.
4. **Check for conflicts** — verify no other agent is working on the same files (check worklog).

### Post-Execution Hooks

After completing any task, the AI agent MUST:

1. **Update `worklog.md`** — append structured entry with Task ID, agent name, work log, and stage summary.
2. **Mark TODO items complete** — use `TodoWrite` to update status.
3. **Validate outputs** — check that generated files exist and are non-empty.
4. **Clean up temp files** — remove any intermediate artifacts from `/home/z/my-project/download/`.

### Error Recovery Hooks

On any error or timeout:

1. **Log the error** in worklog.md with full context.
2. **Retry once** with adjusted parameters (timeout, approach).
3. **After 2 consecutive failures** — inform the user and suggest restarting the session.
4. **Never silently skip** a failed step.

---

## 4. Project Structure

```
/home/z/my-project/
├── CLAUDE.md              # This file — AI agent configuration & rules
├── AGENTS.md              # Systematic agentic engineering process
├── worklog.md             # Shared worklog across all agents
├── .freeze                # Freeze marker (exists = codebase frozen)
├── .claude/
│   └── skills/
│       └── gstack -> ~/.claude/skills/gstack  # gstack symlink
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

## 5. Agentic Engineering Principles

1. **Search Before Building** — Always check existing code, skills, and worklog before starting new work.
2. **One Task Per Agent** — Each subagent handles exactly one well-defined subtask.
3. **Structured Communication** — Agents communicate via worklog.md, not conversation.
4. **Fail Fast, Fail Loud** — Never silently swallow errors. Always report and escalate.
5. **Token Awareness** — Every read, every search, every subagent call costs tokens. Be efficient.
6. **Idempotent Operations** — Every script and operation must be safe to re-run.
7. **Atomic Commits** — Each commit should be a single logical change.

---

## 6. Language & Consistency

- **Language:** Match the user's input language for all responses, documents, and outputs.
- **Chinese plots:** Use `Noto Sans SC` + `DejaVu Sans` fallback for matplotlib.
- **Document fonts:** Use `LibSerif` (headings) + `Carlito` (body) for PDF generation.
- **No emoji** in code files or documents unless explicitly requested.
