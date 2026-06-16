# Elden Ring Map — Project Guide & Governance

Interactive, offline-capable Elden Ring map (markers, questlines, browser-local progress), built as a
**static site** and deployed to GitHub Pages. This file governs how changes are made: project truth is
tracked with **symbolic alignment**, and non-trivial source edits go through a **plan → independent
review → implement** gate.

## Project map

- `index.html` — the entire web app (Leaflet, UI, quest tracker). Loads local data + vendored Leaflet.
- `markers.js`, `quests.js`, `itemdata.js`, `bossdata.js` — **generated** data. Do not hand-edit; regenerate via the build scripts.
- `questlines.json` — authored questline input consumed by `build-quests.ps1`.
- `bossdata.json` — authored boss combat data (damage dealt + weaknesses) consumed by `build-bossdata.ps1`. Not datamined — hand-edit this, then rebuild.
- `build-markers.ps1`, `build-quests.ps1`, `build-itemdata.ps1` — PowerShell builds that regenerate the data from the datamined source. `build-bossdata.ps1` wraps `bossdata.json` into `bossdata.js`.
- `server.ps1` — local static preview server.
- `ctiles/`, `icons/`, `vendor/` — tiles, item icons, vendored Leaflet (offline assets).
- `symbols/`, `scripts/align.py`, `.claude/`, `Agents/`, `docs/` — the governance harness described below.

## Build & deploy

Regenerate data (order matters — quests + itemdata read `markers.js`):

```
powershell -File build-markers.ps1     # markers.js
powershell -File build-quests.ps1      # quests.js   (reads questlines.json + markers.js)
powershell -File build-itemdata.ps1    # itemdata.js (+ downloads icons)
powershell -File build-bossdata.ps1    # bossdata.js  (wraps authored bossdata.json — independent of the others)
```

Deploy: `git push origin main` → GitHub Pages rebuilds (~1–2 min) → https://jw-ofs.github.io/elden-ring-map/.

**Never hand-edit `markers.js` / `quests.js` / `itemdata.js` / `bossdata.js`** — they are build outputs. Edit the
source (`questlines.json`, `bossdata.json`, the build scripts) and regenerate.

---

## Symbolic Alignment

Project truth is encoded as typed symbols in `symbols/manifest.json`, hashed into
`symbols/manifest.lock`. Agents read the `description` / `means` fields; machines verify hashes.

The symbols that matter here:

- **`projection`** — the master-pixel projection constants (`offset_x`, `offset_y`, `native_zoom`,
  `tile_size`, `img_size`). They appear in BOTH `index.html` (`CONFIG` + `xy()`) and the PowerShell
  build scripts. **If they drift between the app and the build scripts, every pin misaligns.**
- **`data_source`** — the datamined upstream the build scripts pull from.
- **`deployment`** — the GitHub Pages target; interlocked so `deployment.expects_native_zoom` must
  equal `projection.native_zoom` (tiles are pre-rendered at that zoom).

Check / update:

```
python scripts/align.py status    # full report
python scripts/align.py check     # exit 0=ok, 1=broken, 2=stale
python scripts/align.py verify    # semantic diff — what drifted, in property terms
python scripts/align.py lock      # regenerate the lock after changes
```

When you change tracked state (e.g. a projection constant): update `manifest.json`, update any
interlocked symbol, run `align.py lock`, and commit `manifest.json` + `manifest.lock` **together**.
If `check` reports broken/stale: **stop**, fix the root cause, then re-lock.

---

## Review Gate

A `PreToolUse` hook (`.claude/hooks/require-review.sh`) enforces **review before implementation**.
While any active task exists in `Agents/TODO/Active/`, edits to gated source — `index.html`,
`build-*.ps1`, `server.ps1`, `scripts/` (set via `REVIEW_GATE_GATED_PREFIXES` in
`.claude/settings.json`) — are blocked until a committed review report references the task. A second
hook (`check-alignment.sh`) blocks gated edits while alignment is broken or stale.

### Workflow

1. Task doc `Agents/TODO/Active/<task>.md` — problem+evidence, plan, key files, verification; `## Status: Not Started`.
2. Line-level plan `<task>-plan.md` — file + line range, verbatim current code, exact replacement. *"Update X" is not a plan.*
3. Review `Agents/Review-reports/<task>-review.md` — by a **separate** agent: logic + edge cases, naming consistency, data/schema alignment, integration. Commit it.
4. Implement → verify → move task + plan + review to `Agents/TODO/CompletedTODO/`.

If ≥2 active tasks declare the same `Surface: <key>` (registered in
`.claude/hooks/combined-surfaces.json`), a **combined-scenario review** is also required — see
[`docs/review-workflow.md`](docs/review-workflow.md).

### Agent-driven changes

When a task force will modify gated source, run the `gated-change` workflow — it runs plan → an
**independent reviewer agent** that writes the committed review the gate expects, so the verification is
recorded rather than dormant. PreToolUse hooks apply to subagent edits too, so agents are gated exactly
like the main thread. See [`docs/agent-gated-change.md`](docs/agent-gated-change.md).

Validation runs against the **committed git tree**. Do not bypass the hook (no `--no-verify`). Ad-hoc
work without an active task doc is not gated; non-source files (`Agents/`, `docs/`, `.claude/`, and the
generated `*.js`) are always allowed.

### Local requirement

The hooks and `align.py` need **Python 3.10+**. This machine's interpreter is wired in via
`REVIEW_GATE_PYTHON` in `.claude/settings.local.json` (gitignored); on any other machine, Python 3.10+
must be on PATH. CI runs the alignment check on GitHub Actions regardless.

---

## Project-Specific Instructions

- Tiles are pre-rendered at native zoom 6; projection is 1px = 1 game unit on the 10496×10496 master image.
- Build scripts must read the datamined `.ts` source with `-Encoding UTF8` (UTF-8 source; ANSI reads cause mojibake).
- Progress is browser-local (`localStorage`); nothing is uploaded.
- Leaflet is vendored under `vendor/leaflet/` — the site has no CDN/runtime dependency and works offline.
