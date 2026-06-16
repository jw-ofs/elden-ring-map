# Agent-driven gated changes

This is the path to take when a **task force of agents** is going to modify gated source
(`index.html`, `build-*.ps1`, `server.ps1`, `scripts/`). It turns the verification we already do
inside multi-agent runs into the **committed review report the gate expects**, so the review gate
records real, independent scrutiny instead of sitting dormant.

## Why this exists

Our agents normally return *in-memory* findings — the verification evaporates when the run ends, and
nothing lands in `Agents/Review-reports/`. The review gate (`.claude/hooks/require-review.sh`) only
unblocks a gated edit when a review report references the active task. This workflow closes that gap:
a **separate reviewer agent** adversarially reviews the plan and **writes** the review file.

It enables a real review — it does not fake one. The reviewer can (and must) return **BLOCKED** when
the plan is unsafe. A BLOCKED verdict means stop and fix the plan; do not implement around it.

## How the gate is satisfied (mechanics)

`review_gate.py` checks, for each active task in `Agents/TODO/Active/`, that some file in
`Agents/Review-reports/` (a) references the task filename verbatim and (b) in strict mode has at least
`REVIEW_GATE_MIN_LINES` (10) meaningful lines and contains any `REVIEW_GATE_KEYWORDS` (none by default
for per-task reviews). The hook reads the **working tree** (the files on disk), so the review file
existing is enough to unblock locally — **commit it** so CI and the audit trail also have it.

## Run it

Run with **elden-ring-map as the project root** (so the paths resolve and the gate is active):

```
Workflow({ name: "gated-change", args: {
  slug:     "fix-projection-offset",          // becomes <slug>.md / <slug>-plan.md / <slug>-review.md
  title:    "Correct OFFSET_X in the build scripts",
  problem:  "Pins are 64px off after the last tile re-render; OFFSET_X drifted.",
  approach: "Update OFFSET_X in build-markers.ps1 and index.html CONFIG to match the new master.",
  files:    ["build-markers.ps1", "index.html"]
}})
```

It runs two agents:

1. **Plan** — reads the target files and writes `Agents/TODO/Active/<slug>.md` (task doc, marked
   `## Status: Not Started`) and `Agents/TODO/Active/<slug>-plan.md` (a line-level plan).
2. **Review** — a *separate* agent reads the plan, reviews it across the four dimensions (logic +
   edge cases, identifier consistency, data/schema alignment, integration), and writes
   `Agents/Review-reports/<slug>-review.md` ending in `Verdict: APPROVED | APPROVED WITH CHANGES | BLOCKED`.

The workflow returns `{ verdict, artifacts }`.

## After it returns

- **APPROVED** — commit the three artifacts, then implement. The gate now allows the gated edits.
- **APPROVED WITH CHANGES** — fold the listed fixes into the plan, re-commit the plan + review, then implement.
- **BLOCKED** — do not implement. Fix the plan and re-run, or abandon the change.
- When done, set the task to `## Status: Complete` (the gate then ignores it) and move task + plan +
  review to `Agents/TODO/CompletedTODO/`.

```
git add Agents/TODO/Active/<slug>.md Agents/TODO/Active/<slug>-plan.md Agents/Review-reports/<slug>-review.md
git commit -m "plan + review: <slug>"
```

## When NOT to use this

- **Multi-task shared surfaces.** If two or more active tasks touch the same registered surface
  (`.claude/hooks/combined-surfaces.json`), a per-task review is not enough — write a
  **combined-scenario review** from `Agents/Review-reports/TEMPLATE-combined-review.md` instead
  (see [`review-workflow.md`](review-workflow.md)).
- **Non-gated edits.** Editing `docs/`, `Agents/`, `.claude/`, or the generated `*.js` is never gated —
  no task or review needed.
- **Trivial one-liners** where the plan + independent review overhead exceeds the change's risk. The
  gate only fires once you create a task doc, so for ad-hoc work, simply do not open one.

## Subagent enforcement

Confirmed against the Claude Code docs: **PreToolUse hooks apply to subagent tool calls, not just the
main thread.** Agents spawned via the Task/Agent tool inherit the parent session's hooks; so do
worktree-isolated parallel agents and background subagents (an earlier bypass for background subagents
was fixed in the v2.1.x line). The one exception is *plugin-delivered* subagents, whose own frontmatter
hooks are ignored for security — but they still inherit the parent session's hooks, so they cannot edit
around the gate either.

Practical consequence: when this repo is the project root, **a task force that edits gated source is
gated exactly like you are.** An agent that tries to `Write` `index.html` while an active task lacks a
review gets the same `deny`. That is precisely why the combined-scenario review matters if you ever fan
parallel file-editing agents across one shared surface — the gate holds for each of them, but only a
combined review examines their changes together.

(Sourced from the Claude Code subagents / permissions / worktrees docs, not a live test in this repo.
To confirm on your machine: open elden-ring-map as the project root, leave an unreviewed active task in
`Agents/TODO/Active/`, and have a subagent attempt to edit `index.html` — it should be denied.)
