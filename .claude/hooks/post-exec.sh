#!/usr/bin/env bash
# post-exec.sh — Auto-hook that runs AFTER each task execution
# Called by the agentic engineering process defined in AGENTS.md
#
# Usage: source /home/z/my-project/.claude/hooks/post-exec.sh <task_id> <status> <output_path>
#
# Status: success | failure | partial

set -euo pipefail

TASK_ID="${1:-0}"
STATUS="${2:-unknown}"
OUTPUT_PATH="${3:-}"
PROJECT_ROOT="/home/z/my-project"
DOWNLOAD_DIR="$PROJECT_ROOT/download"
WORKLOG="$PROJECT_ROOT/worklog.md"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ─── Validate output file (if specified) ───
if [ -n "$OUTPUT_PATH" ]; then
  if [ -f "$OUTPUT_PATH" ]; then
    FILE_SIZE=$(stat -f%z "$OUTPUT_PATH" 2>/dev/null || stat -c%s "$OUTPUT_PATH" 2>/dev/null || echo "0")
    if [ "$FILE_SIZE" -eq 0 ]; then
      echo "POST-EXEC WARNING: Output file $OUTPUT_PATH is empty (0 bytes)"
    else
      echo "POST-EXEC: Output verified: $OUTPUT_PATH ($FILE_SIZE bytes)"
    fi
  else
    echo "POST-EXEC WARNING: Output file $OUTPUT_PATH does not exist"
  fi
fi

# ─── Cleanup temp artifacts ───
# Remove known temporary file patterns from download/
TEMP_PATTERNS=(
  "*_body.pdf"
  "cover.pdf"
  "cover.html"
  "generate_*.py"
  "merge_*.py"
  "*.tmp"
  "*.bak"
)

for pattern in "${TEMP_PATTERNS[@]}"; do
  for f in $DOWNLOAD_DIR/$pattern; do
    if [ -f "$f" ]; then
      rm -f "$f"
      echo "POST-EXEC: Cleaned up temp file: $(basename "$f")"
    fi
  done
done

# ─── Update session state ───
SESSION_FILE="$PROJECT_ROOT/.claude/session-state.json"
if [ -f "$SESSION_FILE" ] && command -v python3 &>/dev/null; then
  python3 -c "
import json
f = '$SESSION_FILE'
try:
    with open(f) as fh: d = json.load(fh)
except: d = {}
d['tasks_completed'] = d.get('tasks_completed', 0) + 1
d['last_task_id'] = '$TASK_ID'
d['last_task_status'] = '$STATUS'
d['last_activity'] = '$TIMESTAMP'
with open(f, 'w') as fh: json.dump(d, fh, indent=2)
" 2>/dev/null || true
fi

echo "POST-EXEC: Task $TASK_ID completed with status: $STATUS at $TIMESTAMP"
