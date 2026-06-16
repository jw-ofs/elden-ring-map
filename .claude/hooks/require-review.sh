#!/bin/bash
# PreToolUse hook shim — delegates to review_gate.py.
#
# The real logic lives in review_gate.py so we get proper testability and
# stdlib-only execution (no jq/yq dependencies). This shim exists only because
# settings.json invokes hooks via bash for portability.
#
# Configuration is via env vars (see review_gate.py for the list).

set -uo pipefail

PROJ="${CLAUDE_PROJECT_DIR:-$(pwd)}"
PYTHON_BIN="${REVIEW_GATE_PYTHON:-python3}"

# Pass stdin straight through; review_gate.py decides allow/deny.
exec "$PYTHON_BIN" "$PROJ/.claude/hooks/review_gate.py"
