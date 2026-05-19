#!/usr/bin/env bash
# pre-exec.sh — Auto-hook that runs BEFORE each task execution
# Called by the agentic engineering process defined in AGENTS.md
#
# Usage: source /home/z/my-project/.claude/hooks/pre-exec.sh <task_type> <task_id>
#
# Task types: document | visualization | webdev | data | code

set -euo pipefail

TASK_TYPE="${1:-unknown}"
TASK_ID="${2:-0}"
PROJECT_ROOT="/home/z/my-project"
FREEZE_MARKER="$PROJECT_ROOT/.freeze"

# ─── Check freeze state ───
if [ -f "$FREEZE_MARKER" ]; then
  echo "FROZEN: Codebase is frozen. Remove .freeze or use /unfreeze to continue."
  exit 1
fi

# ─── Verify project structure ───
for dir in "$PROJECT_ROOT" "$PROJECT_ROOT/download" "$PROJECT_ROOT/.claude"; do
  if [ ! -d "$dir" ]; then
    mkdir -p "$dir"
  fi
done

# ─── Verify gstack installation ───
GSTACK_SETUP="$HOME/.claude/skills/gstack/setup"
if [ ! -f "$GSTACK_SETUP" ]; then
  echo "WARNING: gstack not installed. Run: git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup"
fi

# ─── Task type validation ───
case "$TASK_TYPE" in
  document|visualization|webdev|data|code)
    # Valid task types
    ;;
  unknown)
    echo "WARNING: Unknown task type. Classification may be needed."
    ;;
  *)
    echo "WARNING: Unrecognized task type '$TASK_TYPE'. Expected: document|visualization|webdev|data|code"
    ;;
esac

# ─── Session state ───
SESSION_FILE="$PROJECT_ROOT/.claude/session-state.json"
if [ ! -f "$SESSION_FILE" ]; then
  cat > "$SESSION_FILE" << 'EOF'
{
  "session_id": "",
  "started_at": "",
  "tasks_completed": 0,
  "last_task_type": "",
  "last_task_id": ""
}
EOF
fi

# Update session state with current task
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
if command -v python3 &>/dev/null; then
  python3 -c "
import json, sys
f = '$SESSION_FILE'
try:
    with open(f) as fh: d = json.load(fh)
except: d = {}
d['last_task_type'] = '$TASK_TYPE'
d['last_task_id'] = '$TASK_ID'
d['last_activity'] = '$TIMESTAMP'
with open(f, 'w') as fh: json.dump(d, fh, indent=2)
" 2>/dev/null || true
fi

echo "PRE-EXEC: Task $TASK_ID ($TASK_TYPE) cleared for execution at $TIMESTAMP"
