#!/usr/bin/env python3
"""Alignment-gate PreToolUse hook.

Reads a Claude Code PreToolUse event on stdin and emits a deny decision when
`align.py check` reports broken or stale alignment for a gated source path.

Path filtering reuses the same gated-prefix logic as review_gate.py: by default
only `src/`, `k8s/`, `scripts/`, `config/` paths trigger an alignment check.
Override via REVIEW_GATE_GATED_PREFIXES (shared with review_gate.py).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_GATED_PREFIXES = ["src/", "k8s/", "scripts/", "config/"]


def load_manifest_gated_prefixes(project_root: Path) -> list[str] | None:
    """Return gates.gated_paths from symbols/manifest.json, or None if absent."""
    manifest_path = project_root / "symbols" / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    gates = manifest.get("gates") or {}
    paths = gates.get("gated_paths")
    if isinstance(paths, list) and all(isinstance(p, str) for p in paths):
        return [p.rstrip("/") + "/" for p in paths if p]
    return None


def resolve_gated_prefixes(project_root: Path) -> list[str]:
    """Resolve gated prefixes via env > manifest > defaults."""
    env = os.environ.get("REVIEW_GATE_GATED_PREFIXES")
    if env:
        return [p.strip() for p in env.split(",") if p.strip()]
    manifest_prefixes = load_manifest_gated_prefixes(project_root)
    if manifest_prefixes is not None:
        return manifest_prefixes
    return DEFAULT_GATED_PREFIXES


def emit_allow() -> None:
    sys.exit(0)


def emit_deny(reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    sys.exit(0)


def normalize_path(file_path: str, project_root: Path) -> str:
    if not file_path:
        return ""
    fp = Path(file_path)
    if fp.is_absolute():
        try:
            return fp.resolve().relative_to(project_root.resolve()).as_posix()
        except (ValueError, OSError):
            return fp.as_posix()
    return fp.as_posix()


def is_gated(rel_path: str, prefixes: list[str]) -> bool:
    if not rel_path:
        return False
    return any(rel_path.startswith(p) for p in prefixes)


def main() -> None:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        emit_allow()

    file_path = event.get("tool_input", {}).get("file_path", "")
    cwd = event.get("cwd", "")

    project_root = Path(
        os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()
    ).resolve()

    prefixes = resolve_gated_prefixes(project_root)

    rel = normalize_path(file_path, project_root)
    if not is_gated(rel, prefixes):
        emit_allow()

    # Run align.py check with explicit project-dir so CWD doesn't matter.
    align_script = project_root / "scripts" / "align.py"
    if not align_script.is_file():
        # No align.py — nothing to check, allow.
        emit_allow()

    python_bin = os.environ.get("REVIEW_GATE_PYTHON") or sys.executable
    proc = subprocess.run(
        [python_bin, str(align_script), "--project-dir", str(project_root), "check", "--quiet"],
        capture_output=True,
        text=True,
    )

    if proc.returncode == 0:
        emit_allow()
    elif proc.returncode == 1:
        emit_deny(
            f"ALIGNMENT BROKEN: {proc.stderr.strip()}. "
            "Stop and fix the root cause. Run 'python3 scripts/align.py status' "
            "for details, then 'python3 scripts/align.py lock' after fixing."
        )
    elif proc.returncode == 2:
        emit_deny(
            f"ALIGNMENT STALE: {proc.stderr.strip()}. "
            "Run 'python3 scripts/align.py lock' to regenerate the lock before "
            "editing source files."
        )
    else:
        # align.py itself errored — don't block (preserves prior behavior).
        emit_allow()


if __name__ == "__main__":
    main()
