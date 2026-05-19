#!/usr/bin/env bash
# failover.sh — Failover/Fallback Chain Executor
# Called by trigger-engine.sh when a primary action fails
# Implements the precise retry → adjust → escalate → last-resort chain
#
# Usage: bash /home/z/my-project/.claude/engine/failover.sh <action> <error_detail>

set -euo pipefail

ACTION="${1:-unknown}"
ERROR="${2:-unspecified error}"
PROJECT_ROOT="/home/z/my-project"
ERROR_FILE="$PROJECT_ROOT/.claude/error-pending.json"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ─── Retry counter ───
RETRY_FILE="$PROJECT_ROOT/.claude/.retry-count"
get_retry_count() {
  if [ -f "$RETRY_FILE" ]; then
    cat "$RETRY_FILE"
  else
    echo "0"
  fi
}
increment_retry() {
  local count=$(get_retry_count)
  echo $((count + 1)) > "$RETRY_FILE"
}
reset_retry() {
  echo "0" > "$RETRY_FILE"
}

# ─── Failover actions ───
failover_auto_install_gstack() {
  echo "[FAILOVER] Auto-installing gstack..."
  rm -rf ~/.claude/skills/gstack 2>/dev/null || true
  git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack 2>/dev/null
  cd ~/.claude/skills/gstack && ./setup --quiet 2>/dev/null
  if [ -f ~/.claude/skills/gstack/setup ]; then
    echo "[FAILOVER] gstack auto-installed successfully."
    reset_retry
  else
    echo "[FAILOVER] gstack auto-install FAILED. Escalating."
    failover_escalate "gstack auto-install failed"
  fi
}

failover_generate_default_claude_md() {
  echo "[FAILOVER] Generating default CLAUDE.md..."
  cat > "$PROJECT_ROOT/CLAUDE.md" << 'DEFAULT_CLAUDE'
# CLAUDE.md — Project Configuration

## gstack — AI Automation & Vibe Coding Skills

Always use `/browse` for web browsing. NEVER use `mcp__claude-in-chrome__*` tools.

### Key Skills
- `/office-hours` — Reframe product ideas
- `/qa` — Full QA pass
- `/review` — PR review
- `/ship` — Create PR with tests and changelog
- `/browse` — Headless browser (always prefer this)

## Token Efficiency
- Lazy load skills (only load what you need)
- Use Grep/Glob before Read
- Compress context for subagents

## Auto-Triggers
- Session start: Read CLAUDE.md, AGENTS.md, worklog.md
- Pre-execution: Check freeze, verify output dir
- Post-execution: Validate output, update worklog, cleanup
DEFAULT_CLAUDE
  echo "[FAILOVER] Default CLAUDE.md generated."
  reset_retry
}

failover_halt_and_report() {
  echo "[FAILOVER] HALTING: $ERROR"
  echo "[FAILOVER] Codebase may be frozen or a critical prerequisite is missing."
  echo "[FAILOVER] Suggested actions:"
  echo "  1. Check /home/z/my-project/.freeze (delete if frozen)"
  echo "  2. Verify gstack installation: ls ~/.claude/skills/gstack/setup"
  echo "  3. Run session init: bash .claude/hooks/session-init.sh"
  # Write error file for AI agent to pick up
  cat > "$ERROR_FILE" << EOF
{"timestamp":"$TIMESTAMP","action":"$ACTION","error":"$ERROR","status":"halted"}
EOF
}

failover_default_to_type1() {
  echo "[FAILOVER] Task classification failed. Defaulting to Type 1 (Document Creation)."
  echo "[FAILOVER] AI agent should route to pdf/docx/xlsx/ppt skill."
  reset_retry
}

failover_proceed_without_todo() {
  echo "[FAILOVER] TODO list creation failed. Proceeding with inline tracking."
  echo "[FAILOVER] AI agent should track progress in conversation text."
  reset_retry
}

failover_create_output_dir() {
  mkdir -p "$PROJECT_ROOT/download"
  echo "[FAILOVER] Created output directory: $PROJECT_ROOT/download/"
  reset_retry
}

failover_warn_and_proceed() {
  echo "[FAILOVER] Warning: $ERROR"
  echo "[FAILOVER] Proceeding with caution. AI agent should be aware of potential conflicts."
  reset_retry
}

failover_fallback_to_generic() {
  echo "[FAILOVER] Skill not found. Falling back to generic implementation."
  echo "[FAILOVER] AI agent should implement the task using standard tools without the skill."
  reset_retry
}

failover_retry_once_then_generic() {
  local count=$(get_retry_count)
  if [ "$count" -lt 1 ]; then
    increment_retry
    echo "[FAILOVER] Retrying skill load (attempt $((count + 1)))..."
  else
    echo "[FAILOVER] Skill load retry exhausted. Falling back to generic."
    failover_fallback_to_generic
  fi
}

failover_truncate_to_essentials() {
  echo "[FAILOVER] Context too large for subagent. Truncating to essentials."
  echo "[FAILOVER] AI agent should compress context to <8000 tokens, bullet points only."
  reset_retry
}

failover_retry_with_simpler_prompt() {
  local count=$(get_retry_count)
  if [ "$count" -lt 1 ]; then
    increment_retry
    echo "[FAILOVER] Retrying subagent with simplified prompt..."
  else
    echo "[FAILOVER] Subagent retry exhausted. Escalating."
    failover_escalate "$ERROR"
  fi
}

failover_log_error_and_report() {
  echo "[FAILOVER] Output validation failed: $ERROR"
  echo "[FAILOVER] The task may have failed. AI agent should report to user."
  cat >> "$PROJECT_ROOT/worklog.md" << EOF

---
Task ID: FAILOVER
Agent: failover.sh
Task: Error recovery for $ACTION

Work Log:
- Error occurred: $ERROR
- Timestamp: $TIMESTAMP
- Failover action: log_error_and_report

Stage Summary:
- Task may have failed. User notification required.
EOF
  reset_retry
}

failover_retry_once() {
  local count=$(get_retry_count)
  if [ "$count" -lt 1 ]; then
    increment_retry
    echo "[FAILOVER] Retrying once (attempt $((count + 1)))..."
  else
    echo "[FAILOVER] Retry exhausted. Continuing without this step."
    reset_retry
  fi
}

failover_log_warning_only() {
  echo "[FAILOVER] Warning (non-critical): $ERROR"
  reset_retry
}

failover_escalate() {
  local detail="${1:-$ERROR}"
  echo "[FAILOVER] ESCALATING TO USER: $detail"
  echo "[FAILOVER] After 2 consecutive failures, suggest: restart the session."
  cat > "$ERROR_FILE" << EOF
{"timestamp":"$TIMESTAMP","action":"$ACTION","error":"$detail","status":"escalated_to_user","retry_count":$(get_retry_count)}
EOF
  reset_retry
}

failover_write_error_file() {
  cat > "$ERROR_FILE" << EOF
{"timestamp":"$TIMESTAMP","action":"$ACTION","error":"$ERROR","status":"error_file_written"}
EOF
  echo "[FAILOVER] Error written to $ERROR_FILE for later recovery."
}

# ═══════════════════════════════════════════════════════════
# FAILover DISPATCH
# ═══════════════════════════════════════════════════════════
echo "[FAILOVER] Action: $ACTION | Error: $ERROR"

case "$ACTION" in
  auto_install_gstack)         failover_auto_install_gstack ;;
  generate_default_claude_md)  failover_generate_default_claude_md ;;
  halt_and_report)             failover_halt_and_report ;;
  default_to_type1)            failover_default_to_type1 ;;
  proceed_without_todo)        failover_proceed_without_todo ;;
  create_output_dir)           failover_create_output_dir ;;
  warn_and_proceed)            failover_warn_and_proceed ;;
  fallback_to_generic)         failover_fallback_to_generic ;;
  retry_once_then_generic)     failover_retry_once_then_generic ;;
  truncate_to_essentials)      failover_truncate_to_essentials ;;
  retry_with_simpler_prompt)   failover_retry_with_simpler_prompt ;;
  log_error_and_report)        failover_log_error_and_report ;;
  retry_once)                  failover_retry_once ;;
  log_warning_only)            failover_log_warning_only ;;
  escalate_to_user)            failover_escalate ;;
  write_error_file)            failover_write_error_file ;;
  *)
    echo "[FAILOVER] Unknown failover action: $ACTION"
    failover_escalate "Unknown failover action: $ACTION"
    ;;
esac
