#!/usr/bin/env bash
# session-init.sh — Auto-hook that runs at SESSION START
# Reads CLAUDE.md, AGENTS.md, worklog.md, and verifies gstack installation
#
# This script is designed to be sourced or called at the beginning of each
# new AI agent session to establish proper context.

set -euo pipefail

PROJECT_ROOT="/home/z/my-project"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "═══════════════════════════════════════════════════"
echo "  SESSION INIT — $TIMESTAMP"
echo "═══════════════════════════════════════════════════"

# ─── 1. Verify core files exist ───
echo ""
echo "[1/5] Verifying core configuration files..."
for file in "$PROJECT_ROOT/CLAUDE.md" "$PROJECT_ROOT/AGENTS.md" "$PROJECT_ROOT/worklog.md"; do
  if [ -f "$file" ]; then
    LINES=$(wc -l < "$file")
    echo "  ✓ $(basename "$file") ($LINES lines)"
  else
    echo "  ✗ $(basename "$file") — MISSING"
  fi
done

# ─── 2. Check gstack installation ───
echo ""
echo "[2/5] Checking gstack installation..."
GSTACK_DIR="$HOME/.claude/skills/gstack"
if [ -d "$GSTACK_DIR" ] && [ -f "$GSTACK_DIR/setup" ]; then
  GSTACK_VERSION=$(cat "$GSTACK_DIR/VERSION" 2>/dev/null || echo "unknown")
  SKILL_COUNT=$(ls -d "$HOME/.claude/skills"/*/SKILL.md 2>/dev/null | wc -l || echo "0")
  echo "  ✓ gstack v$GSTACK_VERSION ($SKILL_COUNT skills linked)"
else
  echo "  ✗ gstack not installed — run: cd ~/.claude/skills/gstack && ./setup"
fi

# ─── 3. Check freeze state ───
echo ""
echo "[3/5] Checking freeze state..."
if [ -f "$PROJECT_ROOT/.freeze" ]; then
  echo "  ⚠ CODEBASE IS FROZEN — Use /unfreeze to remove restrictions"
  cat "$PROJECT_ROOT/.freeze" 2>/dev/null || echo "  (no freeze details)"
else
  echo "  ✓ Codebase is unfrozen (normal operation)"
fi

# ─── 4. Check project structure ───
echo ""
echo "[4/5] Verifying project structure..."
for dir in "$PROJECT_ROOT/download" "$PROJECT_ROOT/.claude" "$PROJECT_ROOT/.claude/hooks" "$PROJECT_ROOT/.claude/config"; do
  if [ -d "$dir" ]; then
    echo "  ✓ $(basename "$dir")/"
  else
    mkdir -p "$dir"
    echo "  + $(basename "$dir")/ (created)"
  fi
done

# ─── 5. Show recent worklog ───
echo ""
echo "[5/5] Recent activity..."
if [ -f "$PROJECT_ROOT/worklog.md" ]; then
  # Show last 3 task entries (last 15 lines approximately)
  TAIL_LINES=$(tail -15 "$PROJECT_ROOT/worklog.md" 2>/dev/null || echo "  (empty)")
  echo "$TAIL_LINES"
else
  echo "  (no worklog entries yet)"
fi

# ─── Session state initialization ───
SESSION_FILE="$PROJECT_ROOT/.claude/session-state.json"
if [ ! -f "$SESSION_FILE" ]; then
  cat > "$SESSION_FILE" << EOF
{
  "session_id": "$TIMESTAMP",
  "started_at": "$TIMESTAMP",
  "tasks_completed": 0,
  "last_task_type": "",
  "last_task_id": "",
  "last_activity": "$TIMESTAMP"
}
EOF
  echo ""
  echo "  Session state initialized."
else
  # Update started_at for new session
  if command -v python3 &>/dev/null; then
    python3 -c "
import json
f = '$SESSION_FILE'
try:
    with open(f) as fh: d = json.load(fh)
except: d = {}
d['session_id'] = '$TIMESTAMP'
d['started_at'] = '$TIMESTAMP'
with open(f, 'w') as fh: json.dump(d, fh, indent=2)
" 2>/dev/null || true
  fi
  echo ""
  echo "  Session state updated."
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Session ready. Follow AGENTS.md for execution."
echo "═══════════════════════════════════════════════════"
