#!/usr/bin/env python3
"""Review-gate PreToolUse hook.

Reads a Claude Code PreToolUse hook event on stdin and emits a JSON decision
(allow/deny) on stdout. Replaces the bash require-review.sh with proper
validation:

  - Per-task review reports must reference the task filename AND meet
    keyword + minimum-line-count rules (configurable, defaults below).
  - Combined-scenario reviews are required when ≥2 active tasks declare the
    same surface key. Surface registry lives in combined-surfaces.json.

The hook only gates paths under configurable prefixes (default: src/, k8s/,
scripts/, config/). Paths are normalized so absolute and relative both gate.

Environment variables for tuning:
  REVIEW_GATE_TASKS_DIR        Active task dir (default: Agents/TODO/Active)
  REVIEW_GATE_REVIEWS_DIR      Review reports dir (default: Agents/Review-reports)
  REVIEW_GATE_MIN_LINES        Per-task review minimum lines (default: 10)
  REVIEW_GATE_KEYWORDS         Comma-separated required keywords (default: none)
  REVIEW_GATE_STRICT           Set to "false" to revert to lenient mode (filename-only)
  REVIEW_GATE_GATED_PREFIXES   Comma-separated path prefixes to gate
                               (default: src/,k8s/,scripts/,config/)
  REVIEW_GATE_SURFACES_FILE    Combined-surfaces registry (default: .claude/hooks/combined-surfaces.json)

Exit codes are always 0 — the hook signals decisions via JSON on stdout
per the Claude Code PreToolUse contract.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


# ─── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_TASKS_DIR = "Agents/TODO/Active"
DEFAULT_REVIEWS_DIR = "Agents/Review-reports"
DEFAULT_SURFACES_FILE = ".claude/hooks/combined-surfaces.json"
DEFAULT_MIN_LINES = 10
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


# ─── Decision emission ───────────────────────────────────────────────────────

def emit_allow() -> None:
    """Emit nothing — hook stays silent on allow per Claude Code conventions."""
    sys.exit(0)


def emit_deny(reason: str) -> None:
    decision = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    json.dump(decision, sys.stdout)
    sys.stdout.write("\n")
    sys.exit(0)


# ─── Path normalization ──────────────────────────────────────────────────────

def normalize_path(file_path: str, project_root: Path) -> str:
    """Return path relative to project_root, with forward slashes.

    If file_path is absolute and starts with project_root, strip the prefix.
    Otherwise return file_path unchanged with backslashes converted.
    """
    if not file_path:
        return ""
    fp = Path(file_path)
    if fp.is_absolute():
        try:
            rel = fp.resolve().relative_to(project_root.resolve())
            return rel.as_posix()
        except (ValueError, OSError):
            return fp.as_posix()
    return fp.as_posix()


def is_gated(rel_path: str, prefixes: list[str]) -> bool:
    """True if rel_path starts with any gated prefix (POSIX form)."""
    if not rel_path:
        return False
    return any(rel_path.startswith(p) for p in prefixes)


# ─── Task and review parsing ─────────────────────────────────────────────────

SURFACE_RE = re.compile(r"^Surface:\s*([A-Za-z0-9._-]+)", re.MULTILINE)
STATUS_COMPLETE_RE = re.compile(r"^##\s*Status:.*\bcomplete\b", re.MULTILINE | re.IGNORECASE)


@dataclass
class Task:
    name: str  # filename, e.g. "my-task.md"
    path: Path
    text: str
    surface: str | None  # declared via "Surface: <key>" in body


def load_tasks(active_dir: Path) -> list[Task]:
    """Load non-complete tasks from active_dir."""
    if not active_dir.is_dir():
        return []
    tasks: list[Task] = []
    for p in sorted(active_dir.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if STATUS_COMPLETE_RE.search(text):
            continue
        surface_match = SURFACE_RE.search(text)
        surface = surface_match.group(1) if surface_match else None
        tasks.append(Task(name=p.name, path=p, text=text, surface=surface))
    return tasks


def count_meaningful_lines(text: str) -> int:
    """Count non-blank, non-comment lines."""
    return sum(
        1 for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    )


def review_validates_task(
    review_text: str,
    task_name: str,
    keywords: list[str],
    min_lines: int,
    strict: bool,
) -> tuple[bool, str]:
    """Return (is_valid, reason_if_not)."""
    if task_name not in review_text:
        return False, f"review does not reference task '{task_name}'"
    if not strict:
        return True, ""
    if count_meaningful_lines(review_text) < min_lines:
        return False, f"review has fewer than {min_lines} meaningful lines (too thin)"
    body_lower = review_text.lower()
    missing = [kw for kw in keywords if kw.lower() not in body_lower]
    if missing:
        return False, f"review missing required keywords: {', '.join(missing)}"
    return True, ""


def find_review_for_task(
    task: Task,
    reviews_dir: Path,
    keywords: list[str],
    min_lines: int,
    strict: bool,
) -> tuple[bool, str]:
    """Look for a review report validating this task. Returns (found_valid, reason)."""
    if not reviews_dir.is_dir():
        return False, f"reviews directory '{reviews_dir}' does not exist"
    failures = []
    for p in sorted(reviews_dir.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if task.name not in text:
            continue
        ok, why = review_validates_task(text, task.name, keywords, min_lines, strict)
        if ok:
            return True, ""
        failures.append(f"{p.name}: {why}")
    if failures:
        return False, "; ".join(failures)
    return False, "no review report references this task"


# ─── Combined-surfaces ───────────────────────────────────────────────────────

@dataclass
class Surface:
    key: str
    review_file: str
    min_lines: int
    keywords: list[str]


def load_surfaces(surfaces_file: Path) -> dict[str, Surface]:
    """Load surface registry from JSON. Returns {key: Surface}."""
    if not surfaces_file.is_file():
        return {}
    try:
        data = json.loads(surfaces_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    entries = data.get("combined-surfaces", [])
    if not isinstance(entries, list):
        return {}
    surfaces: dict[str, Surface] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        review_file = entry.get("review-file")
        if not key or not review_file:
            continue
        surfaces[key] = Surface(
            key=key,
            review_file=review_file,
            min_lines=int(entry.get("minimum-lines", 40)),
            keywords=list(entry.get("required-keywords", [])),
        )
    return surfaces


def check_combined_surface_overlaps(
    tasks: list[Task],
    surfaces: dict[str, Surface],
    project_root: Path,
) -> str | None:
    """If ≥2 tasks declare the same registered surface, require the combined review.

    Returns a deny reason on failure, None on success.
    """
    by_surface: dict[str, list[str]] = {}
    for t in tasks:
        if t.surface and t.surface in surfaces:
            by_surface.setdefault(t.surface, []).append(t.name)

    for surface_key, task_names in by_surface.items():
        if len(task_names) < 2:
            continue
        surface = surfaces[surface_key]
        review_path = project_root / surface.review_file
        if not review_path.is_file():
            return (
                f"COMBINED REVIEW MISSING: surface '{surface_key}' has {len(task_names)} "
                f"active tasks ({', '.join(task_names)}) but no combined review at "
                f"'{surface.review_file}'. See docs/review-workflow.md."
            )
        try:
            text = review_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return f"COMBINED REVIEW UNREADABLE: '{surface.review_file}'"
        if count_meaningful_lines(text) < surface.min_lines:
            return (
                f"COMBINED REVIEW TOO THIN: '{surface.review_file}' has fewer than "
                f"{surface.min_lines} meaningful lines for surface '{surface_key}'."
            )
        body_lower = text.lower()
        missing = [kw for kw in surface.keywords if kw.lower() not in body_lower]
        if missing:
            return (
                f"COMBINED REVIEW MISSING KEYWORDS: '{surface.review_file}' missing "
                f"{', '.join(missing)} for surface '{surface_key}'."
            )
    return None


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        emit_allow()

    file_path = event.get("tool_input", {}).get("file_path", "")
    cwd = event.get("cwd", "")

    # Resolve project root
    project_root_str = os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()
    project_root = Path(project_root_str).resolve()

    # Config
    gated_prefixes = resolve_gated_prefixes(project_root)
    active_dir = Path(
        os.environ.get("REVIEW_GATE_TASKS_DIR", project_root / DEFAULT_TASKS_DIR)
    )
    reviews_dir = Path(
        os.environ.get("REVIEW_GATE_REVIEWS_DIR", project_root / DEFAULT_REVIEWS_DIR)
    )
    surfaces_file = Path(
        os.environ.get(
            "REVIEW_GATE_SURFACES_FILE", project_root / DEFAULT_SURFACES_FILE
        )
    )
    min_lines = int(os.environ.get("REVIEW_GATE_MIN_LINES", str(DEFAULT_MIN_LINES)))
    keywords = [
        kw.strip() for kw in os.environ.get("REVIEW_GATE_KEYWORDS", "").split(",") if kw.strip()
    ]
    strict = os.environ.get("REVIEW_GATE_STRICT", "true").lower() != "false"

    # Path filter — only gate matching paths
    rel = normalize_path(file_path, project_root)
    if not is_gated(rel, gated_prefixes):
        emit_allow()

    # Load active tasks
    tasks = load_tasks(active_dir)
    if not tasks:
        # No active tasks → ad-hoc edits permitted
        emit_allow()

    # Per-task review validation
    unreviewed: list[str] = []
    for t in tasks:
        ok, why = find_review_for_task(t, reviews_dir, keywords, min_lines, strict)
        if not ok:
            unreviewed.append(f"{t.name} ({why})")

    if unreviewed:
        reason = (
            "REVIEW GATE: Active task(s) lack a valid review: "
            + "; ".join(unreviewed)
            + ". Write a review in "
            + str(reviews_dir.relative_to(project_root) if reviews_dir.is_relative_to(project_root) else reviews_dir)
            + " referencing the task filename"
            + (
                f", with at least {min_lines} meaningful lines"
                if strict
                else ""
            )
            + (
                f" and these keywords: {', '.join(keywords)}"
                if strict and keywords
                else ""
            )
            + "."
        )
        emit_deny(reason)

    # Combined-surface enforcement
    surfaces = load_surfaces(surfaces_file)
    combined_fail = check_combined_surface_overlaps(tasks, surfaces, project_root)
    if combined_fail:
        emit_deny(combined_fail)

    emit_allow()


if __name__ == "__main__":
    main()
