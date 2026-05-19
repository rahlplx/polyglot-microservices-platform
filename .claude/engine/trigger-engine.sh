#!/usr/bin/env bash
# trigger-engine.sh — The Auto-Trigger Engine v3.0
# Reads triggers.json and executes the certified workflow pipeline
# Now with reliability tracking, phase-aware dispatch, and PROJECT_PLAN integration
#
# Usage: bash /home/z/my-project/.claude/engine/trigger-engine.sh <trigger_name> [args...]
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
RELIABILITY="$ENGINE_DIR/reliability.json"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ─── Color output ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

log_trigger() { echo -e "${CYAN}[TRIGGER]${NC} $1"; }
log_pass()    { echo -e "${GREEN}[PASS]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_fail()    { echo -e "${RED}[FAIL]${NC} $1"; }
log_phase()   { echo -e "${MAGENTA}[PHASE]${NC} $1"; }

# ─── Reliability Tracking ───
record_trigger_metric() {
  local trigger_name="$1"
  local outcome="$2"  # success | failover | error
  if [ -f "$RELIABILITY" ] && command -v python3 &>/dev/null; then
    python3 -c "
import json
f = '$RELIABILITY'
with open(f) as fh: d = json.load(fh)
# Update trigger metrics
tm = d.get('trigger_metrics', {}).get('$trigger_name', {'fired': 0, 'succeeded': 0, 'failovers': 0})
tm['fired'] = tm.get('fired', 0) + 1
if '$outcome' == 'success': tm['succeeded'] = tm.get('succeeded', 0) + 1
elif '$outcome' == 'failover': tm['failovers'] = tm.get('failovers', 0) + 1
d.setdefault('trigger_metrics', {})['$trigger_name'] = tm
# Update overall
d['overall']['total_triggers_fired'] = d['overall'].get('total_triggers_fired', 0) + 1
if '$outcome' == 'success':
    d['overall']['total_triggers_succeeded'] = d['overall'].get('total_triggers_succeeded', 0) + 1
elif '$outcome' == 'failover':
    d['overall']['total_failovers_triggered'] = d['overall'].get('total_failovers_triggered', 0) + 1
elif '$outcome' == 'error':
    d['overall']['total_errors_escalated'] = d['overall'].get('total_errors_escalated', 0) + 1
# Calculate overall rate
fired = d['overall'].get('total_triggers_fired', 0)
succeeded = d['overall'].get('total_triggers_succeeded', 0)
if fired > 0: d['overall']['overall_success_rate'] = f'{succeeded/fired*100:.1f}%'
d['updated_at'] = '$TIMESTAMP'
with open(f, 'w') as fh: json.dump(d, fh, indent=2)
" 2>/dev/null || true
  fi
}

record_phase_metric() {
  local phase_key="$1"
  local outcome="$2"
  if [ -f "$RELIABILITY" ] && command -v python3 &>/dev/null; then
    python3 -c "
import json
f = '$RELIABILITY'
with open(f) as fh: d = json.load(fh)
pm = d.get('phase_metrics', {}).get('$phase_key', {})
pm['attempts'] = pm.get('attempts', 0) + 1
if '$outcome' == 'success': pm['successes'] = pm.get('successes', 0) + 1
elif '$outcome' == 'failover': pm['failovers_triggered'] = pm.get('failovers_triggered', 0) + 1
attempts = pm.get('attempts', 0)
successes = pm.get('successes', 0)
if attempts > 0: pm['success_rate'] = f'{successes/attempts*100:.1f}%'
d.setdefault('phase_metrics', {})['$phase_key'] = pm
d['updated_at'] = '$TIMESTAMP'
with open(f, 'w') as fh: json.dump(d, fh, indent=2)
" 2>/dev/null || true
  fi
}

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
  log_pass "gstack v$version verified (team mode enabled)."
  return 0
}

check_output_dir() {
  if [ ! -d "$DOWNLOAD_DIR" ]; then
    mkdir -p "$DOWNLOAD_DIR"
    log_pass "Created output directory: $DOWNLOAD_DIR"
  fi
}

check_core_files() {
  local all_present=true
  for file in "$PROJECT_ROOT/CLAUDE.md" "$PROJECT_ROOT/AGENTS.md" "$PROJECT_ROOT/PROJECT_PLAN.md"; do
    if [ ! -f "$file" ]; then
      log_fail "$(basename $file) is MISSING."
      all_present=false
    fi
  done
  if [ "$all_present" = true ]; then
    log_pass "Core configuration files present (CLAUDE.md + AGENTS.md + PROJECT_PLAN.md)."
    return 0
  fi
  return 1
}

get_current_phase() {
  if [ -f "$SESSION_STATE" ] && command -v python3 &>/dev/null; then
    python3 -c "
import json
with open('$SESSION_STATE') as f: d = json.load(f)
print(d.get('current_phase', 0))
" 2>/dev/null || echo "0"
  else
    echo "0"
  fi
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

  # Action 1: Check core files (now includes PROJECT_PLAN.md)
  check_core_files || { log_fail "Cannot proceed without core files."; record_trigger_metric "session_start" "error"; return 1; }

  # Action 2: Verify gstack (with team mode)
  check_gstack || { log_warn "gstack check failed. Continuing with degraded capabilities."; }

  # Action 3: Check freeze state
  check_freeze || { record_trigger_metric "session_start" "error"; return 1; }

  # Action 4: Verify output dir
  check_output_dir

  # Action 5: Read worklog
  if [ -f "$WORKLOG" ]; then
    local entries=$(grep -c "^Task ID:" "$WORKLOG" 2>/dev/null || echo "0")
    log_pass "Worklog loaded ($entries previous tasks)."
  else
    log_warn "No worklog found. Starting fresh."
  fi

  # Action 6: Check reliability metrics
  if [ -f "$RELIABILITY" ]; then
    local rate=$(python3 -c "
import json
with open('$RELIABILITY') as f: d = json.load(f)
print(d.get('overall', {}).get('overall_success_rate', 'N/A'))
" 2>/dev/null || echo "N/A")
    log_pass "Reliability tracker: $rate success rate"
  fi

  # Action 7: Read current phase from PROJECT_PLAN
  local current_phase=$(get_current_phase)
  local phase_names=("Foundation" "Discovery" "Design" "Implementation" "Testing" "Ship" "Retrospective")
  local phase_name="${phase_names[$current_phase]:-Unknown}"
  log_phase "Current phase: Phase $current_phase ($phase_name)"

  # Action 8: Update session state
  update_session_state "session_id" "$TIMESTAMP"
  update_session_state "started_at" "$TIMESTAMP"
  update_session_state "freeze_state" "false"
  update_session_state "gstack_team_mode" "true"

  record_trigger_metric "session_start" "success"
  log_pass "Session initialized. Auto-trigger engine v3.0 ready."
  log_pass "Context templates: session, task, execution, skill_injections"
  log_pass "Workflow routes: Type1(Document), Type2(Viz), Type3(WebDev), Type4(Data)"
  log_pass "Phase execution: Follow PROJECT_PLAN.md for current phase spec items"
}

# ═══════════════════════════════════════════════════════════
# TRIGGER: task_receive
# ═══════════════════════════════════════════════════════════
trigger_task_receive() {
  local query="$*"
  log_trigger "TASK_RECEIVE → Classifying and routing..."

  # Action 1: Check freeze
  check_freeze || { record_trigger_metric "task_receive" "error"; return 1; }

  # Action 2: Verify output dir
  check_output_dir

  # Action 3: Check current phase
  local current_phase=$(get_current_phase)
  log_phase "Executing within Phase $current_phase per PROJECT_PLAN.md"

  # Action 4: NLP Intelligent Routing (if query provided)
  if [ -n "$query" ] && [ -f "$ENGINE_DIR/nlp_router.py" ]; then
    log_trigger "NLP-ROUTER → Running intent classification..."
    local nlp_result=$(python3 "$ENGINE_DIR/nlp_router.py" "$query" 2>/dev/null || echo '{}')
    if [ "$nlp_result" != "{}" ]; then
      local intent=$(echo "$nlp_result" | python3 -c "import json,sys; d=json.load(sys.stdin); p=d.get('primary',{}); print(p.get('name','unknown'))" 2>/dev/null || echo "unknown")
      local confidence=$(echo "$nlp_result" | python3 -c "import json,sys; d=json.load(sys.stdin); p=d.get('primary',{}); print(f\"{p.get('confidence',0):.1%}\")" 2>/dev/null || echo "0%")
      local task_type=$(echo "$nlp_result" | python3 -c "import json,sys; d=json.load(sys.stdin); p=d.get('primary',{}); print(p.get('task_type','unknown'))" 2>/dev/null || echo "unknown")
      local skill=$(echo "$nlp_result" | python3 -c "import json,sys; d=json.load(sys.stdin); p=d.get('primary',{}); print(p.get('system_skill','') or p.get('gstack_skills',[''])[0])" 2>/dev/null || echo "")
      log_pass "NLP Classification: $intent ($confidence) → $task_type"
      log_pass "Recommended skill: $skill"
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

  # Action 5: Phase-aware routing reminder
  log_phase "Check PROJECT_PLAN.md Phase $current_phase spec items for gate requirements"
  log_phase "Inject context: $CONTEXT_DIR/task_context.md"

  update_session_state "last_task_id" "pending"
  record_trigger_metric "task_receive" "success"
}

# ═══════════════════════════════════════════════════════════
# TRIGGER: pre_execution
# ═══════════════════════════════════════════════════════════
trigger_pre_execution() {
  log_trigger "PRE_EXECUTION → Validating prerequisites..."

  # Action 1: Freeze check
  check_freeze || { record_trigger_metric "pre_execution" "error"; return 1; }

  # Action 2: Output dir
  check_output_dir

  # Action 3: Worklog conflict scan
  if [ -f "$WORKLOG" ]; then
    local last_task=$(grep "^Task ID:" "$WORKLOG" | tail -1 | awk '{print $3}' 2>/dev/null || echo "none")
    log_pass "Last worklog task: $last_task"
  fi

  # Action 4: Phase check
  local current_phase=$(get_current_phase)
  log_phase "Phase $current_phase — verify spec item gate status"

  # Action 5: Inject execution context
  log_pass "Execution context template: $CONTEXT_DIR/execution_context.md"

  update_session_state "last_activity" "$TIMESTAMP"
  record_trigger_metric "pre_execution" "success"
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

  # Phase-aware injection
  local current_phase=$(get_current_phase)
  log_phase "Phase $current_phase skill injection — check PROJECT_PLAN.md for certified skills"

  record_trigger_metric "skill_invoke" "success"
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

  # Action 3: Phase context for subagent
  local current_phase=$(get_current_phase)
  log_phase "Subagent operates in Phase $current_phase context"

  update_session_state "last_task_id" "$task_id"
  record_trigger_metric "subagent_dispatch" "success"
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

  # Action 4: Phase metric tracking
  local current_phase=$(get_current_phase)
  local phase_keys=("phase_0_foundation" "phase_1_discovery" "phase_2_design" "phase_3_implementation" "phase_4_testing" "phase_5_ship" "phase_6_retrospective")
  local phase_key="${phase_keys[$current_phase]:-phase_0_foundation}"
  if [ "$status" = "success" ]; then
    record_phase_metric "$phase_key" "success"
  elif [ "$status" = "failure" ]; then
    record_phase_metric "$phase_key" "failover"
  fi

  # Action 5: Reliability alert check
  if [ -f "$RELIABILITY" ] && command -v python3 &>/dev/null; then
    local alert=$(python3 -c "
import json
with open('$RELIABILITY') as f: d = json.load(f)
pm = d.get('phase_metrics', {}).get('$phase_key', {})
rate = pm.get('success_rate', 'N/A')
if rate != 'N/A':
    rate_val = float(rate.replace('%',''))
    if rate_val < 90: print('ALERT: Phase $current_phase success rate below 90%')
    else: print('OK')
else: print('OK')
" 2>/dev/null || echo "OK")
    if [ "$alert" != "OK" ]; then
      log_warn "$alert — Process review needed in Phase 6"
    fi
  fi

  record_trigger_metric "post_execution" "success"
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

  # Action 2: Record in reliability metrics
  record_trigger_metric "error_recovery" "error"

  # Action 3: Phase-aware error logging
  local current_phase=$(get_current_phase)
  local phase_keys=("phase_0_foundation" "phase_1_discovery" "phase_2_design" "phase_3_implementation" "phase_4_testing" "phase_5_ship" "phase_6_retrospective")
  local phase_key="${phase_keys[$current_phase]:-phase_0_foundation}"
  record_phase_metric "$phase_key" "failover"

  log_fail "Error logged to .claude/error-pending.json"
  log_pass "Recovery: retry once → retry adjusted → escalate → error file"
  log_pass "After 2 consecutive failures: suggest session restart."
}

# ═══════════════════════════════════════════════════════════
# TRIGGER DISPATCH
# ═══════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════"
echo "  AUTO-TRIGGER ENGINE v3.0"
echo "  Trigger: $TRIGGER"
echo "  Time: $TIMESTAMP"
PHASE_DISP=$(get_current_phase 2>/dev/null || echo "0")
echo "  Current Phase: $PHASE_DISP"
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
