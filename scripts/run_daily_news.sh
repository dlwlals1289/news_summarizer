#!/bin/bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

if [ -x "$PROJECT_DIR/venv/bin/python" ]; then
  PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
elif [ -x "$PROJECT_DIR/nenv/bin/python" ]; then
  PYTHON_BIN="$PROJECT_DIR/nenv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] python3 executable not found" >> "$LOG_DIR/scheduler.log"
  exit 1
fi

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] start: $PYTHON_BIN main.py"
  cd "$PROJECT_DIR" || exit 1
  "$PYTHON_BIN" main.py
  STATUS=$?
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] end: status=$STATUS"
  exit "$STATUS"
} >> "$LOG_DIR/scheduler.log" 2>&1
