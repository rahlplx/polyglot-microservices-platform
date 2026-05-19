# Context Template: Execution
# Auto-injected before executing any task. Provides safety checks, skill loading rules, phase-aware dispatch, and gstack integration.

## Pre-Execution Safety Checklist

Before any file write, code execution, or subagent dispatch:

- [ ] **Freeze check:** `/home/z/my-project/.freeze` does NOT exist
- [ ] **Output dir exists:** `/home/z/my-project/download/` is writable
- [ ] **Worklog is current:** Read last entry to check for conflicts
- [ ] **Skill is loaded:** Only the needed gstack skill is loaded (lazy, not eager)
- [ ] **Token budget is clear:** Current task fits within remaining context
- [ ] **Project phase is valid:** Current task is allowed within the current project phase
- [ ] **No pending errors:** `.claude/error-pending.json` does not exist or has been resolved

## Phase-Aware Execution Rules

### Phase 0 (Foundation)
- Only infrastructure verification and configuration
- Do NOT start feature work
- Verify gstack, configs, hooks, trigger engine

### Phase 1 (Discovery & Spec)
- Use /office-hours FIRST (mandatory)
- Write specification documents
- Run review gauntlet (/autoplan or individual reviews)
- Do NOT implement yet

### Phase 2 (Design & Architecture)
- Use /design-consultation first
- Explore variants with /design-shotgun
- Implement design with /design-html
- Audit with /design-review
- Do NOT write production code yet (prototypes only)

### Phase 3 (Implementation & Coding)
- Full implementation allowed
- Use type-specific skills (pdf/docx/charts/fullstack-dev)
- Run /qa after implementation
- Run /review before considering complete
- Boil the Lake — complete implementation, no 90% shortcuts

### Phase 4 (Testing & Validation)
- /qa full pass
- /benchmark performance check
- /cso security audit (if web-facing)
- Cross-browser, accessibility testing
- Do NOT add new features

### Phase 5 (Ship & Deploy)
- /review before /ship (mandatory)
- /ship → /land-and-deploy → /canary
- /document-release for doc updates
- Do NOT add new features during ship

### Phase 6 (Retrospective & Knowledge)
- /retro for retrospective
- /learn for knowledge capture
- /context-save for session preservation
- Review reliability metrics
- Identify process improvements

## gstack Skill Loading Protocol

### Lazy Loading (MANDATORY)

Never preload all gstack skills. Only load the specific skill being invoked:

1. **Identify the skill** from the workflow route (e.g., Type 1 → `pdf`)
2. **Invoke the Skill tool** with the exact skill name: `Skill(command="pdf")`
3. **Read the skill instructions** that the Skill tool returns
4. **Follow those instructions** precisely — they contain the implementation guide
5. **Never load a second skill** unless the first one explicitly requires it

### Skill Chain Rules

Some workflows require skill chaining. Follow these certified chains only:

| Workflow | Skill Chain | Rule |
|----------|-------------|------|
| Document with design thinking | `/office-hours` → `pdf` | Design first, then generate |
| Document with review | `pdf` → `/review` | Generate first, then review |
| Web app full cycle | `/design-html` → `fullstack-dev` → `/qa` → `/ship` | Design → Build → QA → Ship |
| Code review only | `/review` | Standalone |
| QA pass | `/qa` | Standalone |
| Deploy pipeline | `/ship` → `/land-and-deploy` → `/canary` | Ship → Deploy → Monitor |

### ETHOS Injection

Every skill invocation MUST include the ETHOS preamble:
1. **Boil the Lake** — Do the complete thing, not the 90% shortcut
2. **Search Before Building** — Check existing solutions first
3. **The Golden Age** — One person + AI = what used to take 20 people

## Subagent Dispatch Protocol

When dispatching a subagent, inject this compressed context:

```
Task ID: <id>
Project Phase: <current phase from PROJECT_PLAN.md>
Project Root: /home/z/my-project/
Worklog: /home/z/my-project/worklog.md (READ before starting, APPEND when done)

Task: <compressed bullet-point specs>
Input: <file paths to read>
Output: <file path and format to produce>

Spec Items: <relevant spec items from current PROJECT_PLAN.md phase>

Rules:
- Follow AGENTS.md 7-Phase Loop
- Execute ONLY within the current project phase
- Use gstack /browse for web browsing (NEVER mcp__claude-in-chrome__*)
- All outputs to /home/z/my-project/download/
- Append work record to /home/z/my-project/worklog.md
```

## Failover Chain

On ANY failure during execution:

```
Attempt 1: Retry with original parameters
    ↓ (if fails)
Attempt 2: Retry with adjusted parameters (increased timeout, simplified approach)
    ↓ (if fails)
Escalate: Report to user with specific error details
    ↓ (if escalation fails)
Last resort: Write error to /home/z/my-project/.claude/error-pending.json
```

**After 2 consecutive failures on the same task → STOP and inform user.**
**Suggest: "Please click the restart button in the top right corner to restart the session."**

## Reliability Update

After each execution step:
- Record attempt/success/failover in `.claude/engine/reliability.json`
- Check phase success rate — if below 90%, flag for review
- Log any failover actions taken
