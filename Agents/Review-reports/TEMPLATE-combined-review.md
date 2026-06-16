# Combined-Scenario Review — `<surface-key>`

**Date:** YYYY-MM-DD
**Reviewer:** new agent instance — not the author of any of the tasks below
**Verdict:** _APPROVED / APPROVED WITH CHANGES / BLOCKED_

> Copy this file to `Agents/Review-reports/<surface-key>-combined-review.md` and fill in every section. The hook validates keywords (`compound`, `shared-state`, `ordering`, `boundary`, `simulated`) and minimum line count. A review that leaves sections as placeholders will fail validation.

---

## Tasks Combined In This Review

List every task doc + plan + per-task review whose implementation will ship on the same branch or in close-cluster deploys. Each row is a task that this combined review covers.

| Task doc | Plan commit | Per-task review commit | Implementation commit (if landed) |
|---|---|---|---|
| `<task-1>.md` | | | |
| `<task-2>.md` | | | |
| ... | | | |

---

## 1. Compound Diff

Paste the full unified diff across all N PRs. This is the "read it as one change" artifact — do not summarize or paraphrase. If the diff is large, include a file-by-file breakdown plus the full diff attached or linked by commit range.

```diff
<full compound diff>
```

State any diff sections that are significant to the interaction between PRs (not just big — significant). Call out which PR each hunk belongs to.

---

## 2. Shared-State Audit

Enumerate every piece of shared state referenced by **any** of the N PRs:

- Every dataclass (even ones not in any task's Key Files list)
- Every DB table/column/index
- Every enum
- Every JSONB key
- Every config field
- Every event/message contract
- Every file the dashboard or UI reads

For each, answer: is every consumer in the codebase consistent after the N PRs ship? List every consumer explicitly. A consumer missed here is the D1 failure mode from the case study.

### Shared state inventory

| Item | Declared in | All consumers | Consistent after N PRs? |
|---|---|---|---|
| `<shared item>` | | | yes / no + reason |

### Newly-introduced shared state

For any item introduced by one of the N PRs, explicitly trace it through every consumer:

- Producer: where the value is first written
- Storage: where it persists (DB column, JSONB, in-memory, event)
- Every reader: each file or function that consumes it
- Roundtrip integrity: if it's serialized at any point, does it survive deserialization with value intact?

---

## 3. Ordering and Race Analysis

For every pair of PRs that can touch the same row, record, or state in the same execution window:

### Overlapping-state pairs

| PR A | PR B | Shared target | Can both modify in same tick/cycle? | What determines order? |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

### Per-pair race analysis

For each pair above, answer:

- What if PR A's UPDATE runs first? What does PR B observe?
- What if PR B's UPDATE runs first? What does PR A observe?
- Do both log their action regardless of whether the UPDATE matched a row? (If yes, logs can mislead.)
- Is there an idempotency guarantee that makes ordering irrelevant? If so, cite it.

This section catches the D3 failure mode from the case study.

---

## 4. Boundary-Value Semantics

For every new numeric threshold, signal, config field, or binary gate introduced by any of the N PRs, name **three** cases explicitly:

| New input | Missing (no signal) | Present-but-low-quality | Present-and-actionable |
|---|---|---|---|
| `<input>` | What happens? | What happens? | What happens? |

"Fail CLOSED on missing state" is not sufficient. Low-quality state must be handled distinctly from missing state. This section catches the D2 failure mode from the case study.

Also enumerate boundary behaviors:

- What happens at the exact threshold (e.g., `confidence == 0.55`)?
- What if the threshold value is configured to zero? To one? To negative?
- What happens on the first tick after a cold boot (before any signal has arrived)?
- What happens if the signal oscillates around the threshold (hysteresis needed)?

---

## 5. Simulated Combined Deploy

Given **current production state** — not a clean-slate simulation — walk all N PRs' implementations through the first 60 seconds of runtime. Document expected state transitions step by step. This is the reviewer's acceptance test.

### Starting state

Summarize the current DB state, in-memory queues, active slots, pending events, etc. that the deploy will hit.

### Expected transitions

```
t+0:   <deploy> — pod restart
t+1s:  <first boot log expected>
t+5s:  <startup complete>
t+30s: <first tick fires — what does each PR's code do?>
t+45s: <second tick — state after both ticks>
t+60s: <end state summary>
```

Specifically:
- Which rows get modified?
- Which `paused_cause` values land?
- How many active slots remain?
- Any new events fired?

### Red flags

What specific state, if observed in the simulation, indicates a defect that must be fixed before deploy? Name them explicitly — they become the reviewer's go/no-go criteria.

---

## Verdict

Pick one:

### [ ] APPROVED

All N PRs clear together. The combined interaction is safe. Shipping may proceed.

### [ ] APPROVED WITH CHANGES

Specific fixes required before shipping. List them as a numbered plan. The fixes must be folded into the respective task plans, re-reviewed (at the per-task level), and this combined review re-committed with the changes verified before any PR ships.

1. _specific change_
2. _specific change_
3. ...

### [ ] BLOCKED

The interaction as proposed cannot ship safely. At least one PR must be redesigned. Explain which one and why.

---

## Post-Deploy Verification Plan

After deploy, how is the reviewer's simulation validated against real runtime? Name the exact commands, log greps, or DB queries that confirm the predicted end state matched reality.

```bash
# Example: after deploy, within 60s, the following should hold:
# kubectl logs ... | grep <canonical-line> | wc -l  → <expected>
# psql ... -c "SELECT ... FROM ..."                 → <expected>
```

If verification fails, the combined review's predictions were wrong — that is a signal to revisit the five dimensions above, not to soften them.
