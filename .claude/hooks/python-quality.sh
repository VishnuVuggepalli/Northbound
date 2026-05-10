#!/usr/bin/env bash
# PostToolUse hook for Northbound — auto-format + lint Python files on Edit/Write.
# Silent on success. Reports remaining violations with exit code 2.

set -u

# Read hook input JSON from stdin
input="$(cat)"

# Extract file path (works for Edit, Write, MultiEdit)
file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

# No path or not a .py file → silent exit
[ -z "$file" ] && exit 0
[[ "$file" != *.py ]] && exit 0
[ ! -f "$file" ] && exit 0

# Only operate inside the Northbound project (defensive)
case "$file" in
  /root/Northbound/*) ;;
  *) exit 0 ;;
esac

# Locate ruff (try common paths if not on PATH)
RUFF=$(command -v ruff || true)
[ -z "$RUFF" ] && [ -x /usr/local/bin/ruff ] && RUFF=/usr/local/bin/ruff
[ -z "$RUFF" ] && [ -x /root/.local/bin/ruff ] && RUFF=/root/.local/bin/ruff
[ -z "$RUFF" ] && exit 0  # not installed — silent

cd /root/Northbound || exit 0

# Phase 1: format (silent fixes)
"$RUFF" format --quiet "$file" >/dev/null 2>&1 || true

# Phase 2: lint with auto-fix (silent fixes)
"$RUFF" check --fix --quiet "$file" >/dev/null 2>&1 || true

# Phase 3: report remaining violations (use exit code, not stdout match)
"$RUFF" check --output-format=concise "$file" >/tmp/.nb-ruff-out 2>&1
status=$?

if [ "$status" -ne 0 ]; then
  echo "[python-quality] remaining violations in $file:" >&2
  cat /tmp/.nb-ruff-out >&2
  rm -f /tmp/.nb-ruff-out
  exit 2
fi

rm -f /tmp/.nb-ruff-out
exit 0
