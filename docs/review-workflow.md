# Review Workflow

This project uses a plan-first, reviewer-gated workflow for any non-trivial change to production files (`src/`, `k8s/`, `scripts/`, `config/`). The gate is enforced by the PreToolUse hook at `.claude/hooks/require-review.sh`, so the workflow is not optional — source edits will be blocked until the required artifacts exist and are committed.

## The standard flow

```
┌──────────────────────────────────────────────────────────────┐
│  1. Task doc in Agents/TODO/Active/<task>.md                 │
│     - Problem statement with evidence                        │
│     - Hypotheses to prove or falsify                         │
│     - Investigation plan                                     │
│     - Key files                                              │
│     - Constraints and verification                           │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  2. Plan doc: Agents/TODO/Active/<task>-plan.md              │
│     Line-level precise. Every code change cites:             │
│     - File path + line range being replaced                  │
│     - Verbatim current code                                  │
│     - Exact replacement code                                 │
│     For SQL: the full ALTER/CREATE/UPDATE statement.         │
│     "Update X" is NOT a plan.                                │
└───────────────────────────┬──────────────────────────────────┘
                            │ plan committed
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  3. Review doc: Agents/Review-reports/<task>-review.md       │
│     Written by a SEPARATE agent instance (not the planner).  │
│     Four review dimensions, each called out explicitly:      │
│     - Logic errors (and named edge cases)                    │
│     - Variable-name consistency with connected systems       │
│     - Database schema alignment                              │
│     - Integration with related systems                       │
└───────────────────────────┬──────────────────────────────────┘
                            │ review committed to git
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  4. PreToolUse hook (review_gate.py via require-review.sh)   │
│     Blocks source edits under gated prefixes until a review  │
│     report exists in Agents/Review-reports/. In strict mode  │
│     (default) the review must contain the task filename, at  │
│     least REVIEW_GATE_MIN_LINES meaningful lines, and all    │
│     REVIEW_GATE_KEYWORDS. Set REVIEW_GATE_STRICT=false to    │
│     fall back to filename-only matching during onboarding.   │
└───────────────────────────┬──────────────────────────────────┘
                            │ hook passes
                            ▼
                      Implementation
                            │
                            ▼
                     Verification
                            │
                            ▼
             Move task + plan + review to
              Agents/TODO/CompletedTODO/
```

## The combined-scenario extension

When two or more tasks in `Agents/TODO/Active/` modify the **same registered shared surface**, a fifth artifact is required: a **combined-scenario review**. This closes the gap that per-task review cannot close — how changes interact when shipped together.

Shared surfaces are declared in `.claude/hooks/combined-surfaces.json`. Each entry defines a surface key, the required review path, the minimum line count, and the keywords the combined review must include.

Tasks declare which surface they target via a single `Surface: <key>` line in the task body. When `review_gate.py` finds two or more active tasks declaring the same registered surface, it requires the combined review file (path declared in the registry) to exist with all the required keywords and at least `minimum-lines` meaningful lines.

### Why this exists

See `docs/case-study-compound-regression.md` for the incident that motivated this extension. The short version: three PRs that each passed their own committed plan + review still compound-regressed on deploy because no single review examined them together.

### The combined-scenario review's five dimensions

Use `Agents/Review-reports/TEMPLATE-combined-review.md` as the starting template.

1. **Compound diff** — read all N PRs' changes as a single unified diff. No "assume the others are correct" allowed.
2. **Shared-state audit** — enumerate every dataclass, DB column, enum, JSONB key, and config field referenced by ANY of the N PRs. For each, verify every consumer in the codebase is updated consistently — including consumers not named in any of the N task docs.
3. **Ordering and race analysis** — for every pair of PRs that touch overlapping state, identify the UPDATE ordering. Document every condition where UPDATE order matters or one update can lose a race to another.
4. **Boundary-value semantics** — for every new numeric threshold, config field, or signal, name three cases explicitly: missing, present-but-low-quality, present-and-actionable. Fail-closed behavior must cover all three, not just the first.
5. **Simulated combined deploy** — given current production state, walk all N implementations through the first 60 seconds of runtime. Document the expected state transitions. This is the reviewer's acceptance test.

### Verdict

The combined review concludes with one of three verdicts:

- **APPROVED** — all N PRs cleared together; shipping is safe.
- **APPROVED WITH CHANGES** — a small number of specific fixes needed, folded back into the plan before implementation. The combined review is re-committed with the changes applied before any PR can ship.
- **BLOCKED** — the interaction cannot ship safely as proposed; at least one PR must be redesigned.

## Operator responsibilities

- **Register new surfaces as they become apparent.** When a cluster of tasks targets the same file or function, add it to `.claude/hooks/combined-surfaces.json`. The gate only enforces on registered surfaces — unregistered ones will ship unreviewed.
- **Keep review artifacts committed.** Hook validation runs against the git tree, not the working directory. Uncommitted reviews do not count.
- **Do not bypass the hook.** No `--no-verify`, no force-flags, no env-var escape hatches. If the hook blocks, the blocking artifact is missing; produce it.
- **Audit combined reviews post-incident.** When a cascade happens despite the workflow running, that's signal to add a new review dimension or expand the surface registry — not to soften the gate.

## CI integration

The same hook logic runs in CI via the `pre-checks` job in `.github/workflows/ci.yml`. A PR that touches a registered surface without a committed combined review will fail CI.

## When the workflow feels heavy

It is. That's the intent. The line-level plan + independent reviewer + combined-scenario review stack adds 30–60 minutes per multi-surface PR — which is small compared to the 8-hour rollback cycle a compound regression costs. If the workflow feels unnecessarily slow for a particular change, the change probably isn't multi-surface, in which case only the standard three-artifact flow applies and you're done in the usual time. If it is multi-surface and the workflow feels slow, that is exactly when the extra rigor earns its keep.

## Related

- `docs/case-study-compound-regression.md` — the incident that motivated the combined-scenario extension
- `.claude/hooks/review_gate.py` — the gate logic (invoked via `require-review.sh`)
- `.claude/hooks/combined-surfaces.json` — registered shared-surface definitions
- `Agents/Review-reports/TEMPLATE-combined-review.md` — reviewer's starting point
