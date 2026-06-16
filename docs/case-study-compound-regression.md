# Case Study — The Compound-Regression Incident

This doc is a sanitized, project-agnostic version of a real incident that motivated the combined-scenario review extension in `docs/review-workflow.md`. The original incident shipped in a downstream project; names and specifics are abstracted here. The lessons apply to any project adopting this workflow.

## TL;DR

Three independently-scoped PRs — each with its own committed line-level plan + committed independent review — shipped together and produced a production regression. The individual reviews were locally correct. The regression was in the interaction between the three changes, and no single review examined them together.

## The scenario

Project has a trading system with a periodic **rebalance tick** that runs several sub-gates in sequence (dedup, regime-fit, global-count cap, per-family cap). Each sub-gate can pause strategies. The pause reason is written to a single `paused_cause` column.

Three separate tasks were worked in parallel:

- **Task A — Dedup:** add a new sub-gate that pauses duplicate strategies with `paused_cause='duplicate'`.
- **Task B — Regime-fit:** add a new sub-gate that pauses regime-mismatched strategies with `paused_cause='regime_mismatch'`.
- **Task C — New display fields:** unrelated dashboard work that happened to add three new JSONB fields to strategy configs (`target_regimes`, `regime_analysis`, `fitness`).

All three shipped together in the same release.

## What went wrong

Sixty seconds after deploy, the active-strategy count dropped from 13 to 1. Three defects compounded:

### D1 — Cross-file invariant missed

Task C's three new JSONB fields were read by Task B's regime-fit gate. The fields needed to roundtrip through a shared dataclass (`StrategyParameters`, in a file none of the three tasks' "Key Files" sections listed). The dataclass was defined before those fields existed and silently dropped them with a warning.

With those fields dropped, Task B's gate fell back to a coarse per-type default affinity table instead of the strategy-specific affinity Task C was supposed to supply. The fallback made almost every strategy look mismatched for the current regime.

### D2 — Boundary-value semantic gap

Task B's spec said "fail closed on missing regime state." The implementation honored that — when the regime classifier had no signal, the gate passed through.

But when the classifier emitted a **low-confidence** signal (0.40 confidence, essentially a coin-flip), the gate treated it identically to a 0.95-confidence signal. The spec never bound low-confidence as a distinct case. The gate fired aggressively on a near-random signal.

### D3 — Ordering race between sub-gates

Tasks A and B each added a sub-gate to the same rebalance tick. Each gate's UPDATE statement included `WHERE status='active'`. When both gates targeted the same strategy in the same tick, whichever ran first won the `paused_cause` field. The loser emitted a log line ("Duplicate detected: pausing X") but its UPDATE found zero matching rows and silently no-op'd.

Downstream reconcile logic classifies hypotheses by `paused_cause`. Mis-categorized rows would be flipped to wrong hypothesis statuses on the next pod restart.

## Why the review workflow didn't catch it

All three PRs had:
- A committed line-level plan with verbatim before/after code for every change.
- A committed independent review covering logic, variable-name consistency, schema alignment, integration — by a separate agent instance.
- The PreToolUse hook enforced the reviews before implementation.

These are the usual workflow artifacts, and they caught dozens of other defects before they shipped. For this incident, they missed:

**D1** — no review examined the shared dataclass, because it wasn't in any task's file list. "Variable-name consistency with connected systems" caught naming drift in the files the reviewer was looking at; nothing prompted the reviewer to enumerate all consumers of a new JSONB field across the codebase.

**D2** — "does the plan handle edge cases?" was checked. Missing-state was called out as an edge case. Low-quality-state was not. The reviewer validated the plan against the cases the plan named.

**D3** — each review looked at one PR. Two independently-correct sub-gates became a race when they shipped together. No artifact in the workflow asked "what happens when both run on the same row in the same tick?"

## The fix — combined-scenario review

A fourth review artifact, required when multiple active tasks modify a registered shared surface. It covers five dimensions (see `docs/review-workflow.md`):

1. **Compound diff** — read all N PRs together as one unified change.
2. **Shared-state audit** — enumerate every dataclass, column, enum, JSONB key, config field touched by any of the N PRs; verify every consumer is consistent. This catches D1.
3. **Ordering and race analysis** — for every pair of PRs touching overlapping state, identify UPDATE ordering and name every race. This catches D3.
4. **Boundary-value semantics** — for every new numeric threshold, name missing, low-quality, and actionable cases explicitly. This catches D2.
5. **Simulated combined deploy** — walk all N implementations through the first 60 seconds of runtime against current production state; predict the end state.

Hook-enforced the same way the per-task reviews are. No force flags.

## Cost-benefit

Writing a combined review for a multi-surface change adds 30–60 minutes.

The cascade cost:
- 45 seconds of production damage (12 strategies paused in error)
- ~8 hours of rollback, re-plan, re-review, re-implement, re-deploy, re-verify
- Trust erosion ("our review workflow is rigorous, yet this still shipped")

The trade favors the extra review by two orders of magnitude. The combined review is not optional for registered surfaces.

## Residual limits

This extension closes the three specific failure modes named above. The next incident class — if one appears — will not fit any of these five scan patterns. That doesn't mean the extension is wrong; it means the workflow should keep evolving as new incident classes are observed.

Better-than-nothing: register the incident's surface after an incident so the *next* compound change to that surface is covered. Audit the surface registry quarterly for new additions.

## Applying the lesson to a fresh project

When starting a new project from this template:

1. Copy `docs/review-workflow.md` as-is. Don't customize until you have incident signal.
2. Leave `.claude/hooks/combined-surfaces.yaml` empty. Surfaces get registered as you encounter multi-task clusters, not prophylactically.
3. Keep `Agents/Review-reports/TEMPLATE-combined-review.md` committed even if unused — reviewers need it as a starting point.
4. The first time two active tasks modify the same file, add that file (or the specific functions being modified) as a registered surface in the YAML. Don't retroactively require a combined review for already-shipped work.
5. After the first production incident that a combined review would have caught, write your own project-specific case study in `docs/` and revise the review template to name the specific scan pattern that would have prevented it.

The workflow is not a fixed spec. It is a minimum set of gates that should tighten as the project's scope grows and as incident signal accumulates.
