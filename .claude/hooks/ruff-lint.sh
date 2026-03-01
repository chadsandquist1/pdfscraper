#!/bin/bash
# Run Ruff linting and formatting after Claude edits a Python file.

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only run on Python files
[[ "$FILE_PATH" == *.py ]] || exit 0

# Use the project virtual environment if available, fall back to system ruff
RUFF="$CLAUDE_PROJECT_DIR/.venv/bin/ruff"
if [[ ! -x "$RUFF" ]]; then
  RUFF=$(command -v ruff 2>/dev/null)
fi

if [[ -z "$RUFF" ]]; then
  echo "ruff not found — skipping lint" >&2
  exit 0
fi

"$RUFF" check --fix "$FILE_PATH" 2>&1
"$RUFF" format "$FILE_PATH" 2>&1
