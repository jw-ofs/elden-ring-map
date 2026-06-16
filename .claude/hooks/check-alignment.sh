#!/bin/bash
# PreToolUse hook shim — delegates to alignment_gate.py.
#
# The real logic lives in alignment_gate.py so we share the path-filter logic
# with review_gate.py and drop the jq dependency. This shim exists only because
# settings.json invokes hooks via bash for portability.

set -uo pipefail

PROJ="${CLAUDE_PROJECT_DIR:-$(pwd)}"
PYTHON_BIN="${REVIEW_GATE_PYTHON:-python3}"

exec "$PYTHON_BIN" "$PROJ/.claude/hooks/alignment_gate.py"
