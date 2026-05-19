#!/usr/bin/env bash
# trigger-engine.sh — The Auto-Trigger Engine
# Reads triggers.json and executes the certified workflow pipeline
# This is the brain of the agentic system — AI agents follow this pipeline
#
# Usage: bash /home/z/my-project/.claude/engine/trigger-engine.sh <trigger_name>
# Triggers: session_start | task_receive | pre_execution | skill_invoke | subagent_dispatch | post_execution | error_recovery

set -euo pipefail

TRIGGER="${1:-unknown}"
PROJECT_ROOT="/home/z/my-project"
ENGINE_DIR="$PROJECT_ROOT/.claude/engine"
CONTEXT_DIR="$PROJECT_ROOT/.claude/context"
CONFIG_DIR="$PROJECT_ROOT/.claude/config"
DOWNLOAD_DIR="$PROJECT_ROOT/download"
WORKLOG="$PROJECT_ROOT/worklog.md"
FREEZE_MARKER="$PROJECT_ROOT/.freeze"
SESSION_STATE="$PROJECT_ROOT/.claude/session-state.json"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ─── Color output ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_trigger() { echo -e "${CYAN}[TRIGGER]${NC} $1"; }
log_pass()    { echo -e "${GREEN}[PASS]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_fail()    { echo -e "${RED}[FAIL]${NC} $1"; }

# ─── Common checks ───
check_freeze() {
  if [ -f "$FREEZE_MARKER" ]; then
    log_fail "CODEBASE IS FROZEN. Halting."
    cat "$FREEZE_MARKER" 2>/dev/null
    return 1
  fi
  return 0
}

check_gstack() {
  local setup="$HOME/.claude/skills/gstack/setup"
  if [ ! -f "$setup" ]; then
    log_warn "gstack not installed. Auto-installing..."
    git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack 2>/dev/null || true
    cd ~/.claude/skills/gstack && ./setup --quiet 2>/dev/null || true
    if [ -f "$setup" ]; then
      log_pass "gstack auto-installed successfully."
    else
      log_fail "gstack auto-install failed. Manual intervention required."
      return 1
    fi
  fi
  local version=$(cat ~/.claude/skills/gstack/VERSION 2>/dev/null || echo "unknown")
  log_pass "gstack v$version verified."
  return 0
}

check_output_dir() {
  if [ ! -d "$DOWNLOAD_DIR" ]; then
    mkdir -p "$DOWNLOAD_DIR"
    log_pass "Created output directory: $DOWNLOAD_DIR"
  fi
}

check_core_files() {
  for file in "$PROJECT_ROOT/CLAUDE.md" "$PROJECT_ROOT/AGENTS.md"; do
    if [ ! -f "$file" ]; then
      log_fail "$(basename $file) is MISSING."
      return 1
    fi
  done
  log_pass "Core configuration files present."
}

update_session_state() {
  local key="$1"
  local value="$2"
  if [ -f "$SESSION_STATE" ] && command -v python3 &>/dev/null; then
    python3 -c "
import json
f = '$SESSION_STATE'
try:
    with open(f) as fh: d = json.load(fh)
except: d = {}
d['$key'] = '$value'
d['last_activity'] = '$TIMESTAMP'
with open(f, 'w') as fh: json.dump(d, fh, indent=2)
" 2>/dev/null || true
  fi
}

# ═══════════════════════════════════════════════════════════
# TRIGGER: session_start
# ═══════════════════════════════════════════════════════════
trigger_session_start() {
  log_trigger "SESSION_START → Initializing agentic system..."

  # Action 1: Check core files
  check_core_files || { log_fail "Cannot proceed without core files."; return 1; }

  # Action 2: Verify gstack
  check_gstack || { log_warn "gstack check failed. Continuing with degraded capabilities."; }

  # Action 3: Check freeze state
  check_freeze || return 1

  # Action 4: Verify output dir
  check_output_dir

  # Action 5: Read worklog
  if [ -f "$WORKLOG" ]; then
    local entries=$(grep -c "^Task ID:" "$WORKLOG" 2>/dev/null || echo "0")
    log_pass "Worklog loaded ($entries previous tasks)."
  else
    log_warn "No worklog found. Starting fresh."
  fi

  # Action 6: Update session state
  update_session_state "session_id" "$TIMESTAMP"
  update_session_state "started_at" "$TIMESTAMP"
  update_session_state "freeze_state" "false"

  log_pass "Session initialized. Auto-trigger engine ready."
  log_pass "Context templates available: session, task, execution, skill_injections"
  log_pass "Workflow routes: Type1(Document), Type2(Visualization), Type3(WebDev), Type4(Data)"
}

# ═══════════════════════════════════════════════════════════
# TRIGGER: task_receive
# ═══════════════════════════════════════════════════════════
trigger_task_receive() {
  # Shift past the trigger name to get the full query
  local query="$*"
  log_trigger "TASK_RECEIVE → Classifying and routing..."

  # Action 1: Check freeze
  check_freeze || return 1

  # Action 2: Verify output dir
  check_output_dir

  # Action 3: NLP Intelligent Routing (if query provided)
  if [ -n "$query" ] && [ -f "$ENGINE_DIR/nlp_router.py" ]; then
    log_trigger "NLP-ROUTER → Running embeddings-based intent classification..."
    local nlp_result=$(python3 "$ENGINE_DIR/nlp_router.py" "$query" 2>/dev/null || echo '{}')
    if [ "$nlp_result" != "{}" ]; then
      local status=$(echo "$nlp_result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "error")
      local intent=$(echo "$nlp_result" | python3 -c "import json,sys; d=json.load(sys.stdin); p=d.get('primary',{}); print(p.get('name','unknown'))" 2>/dev/null || echo "unknown")
      local confidence=$(echo "$nlp_result" | python3 -c "import json,sys; d=json.load(sys.stdin); p=d.get('primary',{}); print(f\"{p.get('confidence',0):.1%}\")" 2>/dev/null || echo "0%")
      local task_type=$(echo "$nlp_result" | python3 -c "import json,sys; d=json.load(sys.stdin); p=d.get('primary',{}); print(p.get('task_type','unknown'))" 2>/dev/null || echo "unknown")
      local skill=$(echo "$nlp_result" | python3 -c "import json,sys; d=json.load(sys.stdin); p=d.get('primary',{}); print(p.get('system_skill','') or p.get('gstack_skills',[''])[0])" 2>/dev/null || echo "")
      local action=$(echo "$nlp_result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('action','unknown'))" 2>/dev/null || echo "unknown")

      log_pass "NLP Classification: $intent ($confidence) → $task_type"
      log_pass "Recommended skill: $skill | Action: $action"
      update_session_state "last_task_type" "$task_type"
      update_session_state "nlp_confidence" "$confidence"
      update_session_state "nlp_intent" "$intent"
    else
      log_warn "NLP router returned empty. Falling back to keyword classification."
      update_session_state "last_task_type" "pending_classification"
    fi
  else
    log_pass "No query for NLP routing. AI agent should classify manually."
    update_session_state "last_task_type" "pending_classification"
  fi

  # Action 4: Update session state
  update_session_state "last_task_id" "pending"

  log_pass "Task received. AI agent should now:"
  log_pass "  1. Use NLP result above OR classify task type (Type 1-4)"
  log_pass "  2. Create TODO list via TodoWrite"
  log_pass "  3. Estimate token budget"
  log_pass "  4. Inject context template from $CONTEXT_DIR/task_context.md"
  log_pass "  5. Load appropriate skill (lazy, not eager)"
}

# ═══════════════════════════════════════════════════════════
# TRIGGER: pre_execution
# ═══════════════════════════════════════════════════════════
trigger_pre_execution() {
  log_trigger "PRE_EXECUTION → Validating prerequisites..."

  # Action 1: Freeze check
  check_freeze || return 1

  # Action 2: Output dir
  check_output_dir

  # Action 3: Worklog conflict scan
  if [ -f "$WORKLOG" ]; then
    local last_task=$(grep "^Task ID:" "$WORKLOG" | tail -1 | awk '{print $3}' 2>/dev/null || echo "none")
    log_pass "Last worklog task: $last_task"
  fi

  # Action 4: Inject execution context
  log_pass "Execution context template: $CONTEXT_DIR/execution_context.md"

  update_session_state "last_activity" "$TIMESTAMP"
}

# ═══════════════════════════════════════════════════════════
# TRIGGER: skill_invoke
# ═══════════════════════════════════════════════════════════
trigger_skill_invoke() {
  local skill_name="${2:-unknown}"
  log_trigger "SKILL_INVOKE → Loading skill: $skill_name"

  # Verify skill exists
  local skill_dir="$HOME/.claude/skills/$skill_name"
  if [ -d "$skill_dir" ] && [ -f "$skill_dir/SKILL.md" ]; then
    log_pass "Skill found: $skill_dir/SKILL.md"
  else
    log_warn "Skill '$skill_name' not found at expected path."
    log_pass "Fallback: AI agent should use generic implementation."
  fi

  # Inject ETHOS
  local ethos="$HOME/.claude/skills/gstack/ETHOS.md"
  if [ -f "$ethos" ]; then
    log_pass "ETHOS.md available for preamble injection."
  fi

  # Inject skill-specific context
  log_pass "Skill injections template: $CONTEXT_DIR/skill_injections.md"
}

# ═══════════════════════════════════════════════════════════
# TRIGGER: subagent_dispatch
# ═══════════════════════════════════════════════════════════
trigger_subagent_dispatch() {
  local task_id="${2:-0}"
  log_trigger "SUBAGENT_DISPATCH → Preparing context for Task ID: $task_id"

  # Action 1: Verify worklog exists
  if [ ! -f "$WORKLOG" ]; then
    log_warn "Worklog missing. Subagent may lack context."
  fi

  # Action 2: Context compression reminder
  log_pass "Compress context to bullet-point specs before dispatching."
  log_pass "Max subagent context: 8000 tokens."

  update_session_state "last_task_id" "$task_id"
}

# ═══════════════════════════════════════════════════════════
# TRIGGER: post_execution
# ═══════════════════════════════════════════════════════════
trigger_post_execution() {
  local task_id="${2:-0}"
  local status="${3:-unknown}"
  local output_path="${4:-}"
  log_trigger "POST_EXECUTION → Task $task_id ($status)"

  # Action 1: Validate output
  if [ -n "$output_path" ] && [ -f "$output_path" ]; then
    local size=$(stat -c%s "$output_path" 2>/dev/null || stat -f%z "$output_path" 2>/dev/null || echo "0")
    if [ "$size" -gt 0 ]; then
      log_pass "Output verified: $output_path ($size bytes)"
    else
      log_fail "Output is empty: $output_path (0 bytes)"
    fi
  fi

  # Action 2: Cleanup temp files
  for f in "$DOWNLOAD_DIR"/*_body.pdf "$DOWNLOAD_DIR"/cover.pdf "$DOWNLOAD_DIR"/cover.html "$DOWNLOAD_DIR"/generate_*.py "$DOWNLOAD_DIR"/merge_*.py "$DOWNLOAD_DIR"/*.tmp "$DOWNLOAD_DIR"/*.bak; do
    if [ -f "$f" ]; then
      rm -f "$f"
      log_pass "Cleaned up: $(basename "$f")"
    fi
  done

  # Action 3: Update session state
  update_session_state "last_task_id" "$task_id"
  update_session_state "last_task_status" "$status"

  local completed=$(python3 -c "
import json
try:
    with open('$SESSION_STATE') as f: d = json.load(f)
    print(d.get('tasks_completed', 0) + 1)
except: print(1)
" 2>/dev/null || echo "1")
  update_session_state "tasks_completed" "$completed"

  log_pass "Post-execution complete. Task $task_id status: $status"
}

# ═══════════════════════════════════════════════════════════
# TRIGGER: error_recovery
# ═══════════════════════════════════════════════════════════
trigger_error_recovery() {
  local error_msg="${2:-unknown error}"
  log_trigger "ERROR_RECOVERY → $error_msg"

  # Action 1: Write error to pending file
  cat > "$PROJECT_ROOT/.claude/error-pending.json" << EOF
{
  "timestamp": "$TIMESTAMP",
  "error": "$error_msg",
  "trigger": "$TRIGGER",
  "session_state": "$(cat "$SESSION_STATE" 2>/dev/null || echo '{}')",
  "retry_count": 0,
  "status": "pending_user_action"
}
EOF

  log_fail "Error logged to .claude/error-pending.json"
  log_pass "Recovery protocol: retry once → retry with adjusted params → escalate to user"
  log_pass "After 2 consecutive failures: suggest session restart."
}

# ═══════════════════════════════════════════════════════════
# TRIGGER DISPATCH
# ═══════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════"
echo "  AUTO-TRIGGER ENGINE v2.0"
echo "  Trigger: $TRIGGER"
echo "  Time: $TIMESTAMP"
echo "═══════════════════════════════════════════════════"
echo ""

case "$TRIGGER" in
  session_start)     trigger_session_start ;;
  task_receive)      shift; trigger_task_receive "$@" ;;
  pre_execution)     trigger_pre_execution ;;
  skill_invoke)      trigger_skill_invoke "$@" ;;
  subagent_dispatch) trigger_subagent_dispatch "$@" ;;
  post_execution)    trigger_post_execution "$@" ;;
  error_recovery)    trigger_error_recovery "$@" ;;
  *)
    log_fail "Unknown trigger: $TRIGGER"
    echo "Valid triggers: session_start | task_receive | pre_execution | skill_invoke | subagent_dispatch | post_execution | error_recovery"
    exit 1
    ;;
esac

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Trigger $TRIGGER complete."
echo "═══════════════════════════════════════════════════"
