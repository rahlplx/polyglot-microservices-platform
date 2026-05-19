# Context Template: Execution
# Auto-injected before executing any task. Provides safety checks, skill loading rules, and gstack integration.

## Pre-Execution Safety Checklist

Before any file write, code execution, or subagent dispatch:

- [ ] **Freeze check:** `/home/z/my-project/.freeze` does NOT exist
- [ ] **Output dir exists:** `/home/z/my-project/download/` is writable
- [ ] **Worklog is current:** Read last entry to check for conflicts
- [ ] **Skill is loaded:** Only the needed gstack skill is loaded (lazy, not eager)
- [ ] **Token budget is clear:** Current task fits within remaining context

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
Project Root: /home/z/my-project/
Worklog: /home/z/my-project/worklog.md (READ before starting, APPEND when done)

Task: <compressed bullet-point specs>
Input: <file paths to read>
Output: <file path and format to produce>

Rules:
- Follow AGENTS.md 7-Phase Loop
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
