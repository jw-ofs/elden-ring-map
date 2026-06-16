# Architecture

The Elden Ring map is a **static Leaflet site** rendered over datamined master tiles. There is no
backend — `server.ps1` is only a local preview server, and production is a dumb static host.

## Data flow

```
datamined source (data_source symbol)            authored input
  EthanShoeDev/elden-ring-compass @ main          questlines.json
            │                                            │
            ▼                                            ▼
  build-markers.ps1 ─► markers.js          build-quests.ps1 ─► quests.js
  build-itemdata.ps1 ─► itemdata.js (+ icons/)         (reads markers.js + questlines.json)
            │
            ▼
        index.html  ◄──  vendor/leaflet (offline)  +  ctiles/ (tiles)  +  icons/
```

- **`markers.js`, `quests.js`, `itemdata.js` are generated** — never hand-edit them. Edit the source
  (`questlines.json`, the build scripts) and regenerate. Build order matters: markers first, then
  quests and itemdata (which read `markers.js`).
- The build scripts read the datamined `.ts` source with `-Encoding UTF8` (the source is UTF-8;
  reading it as ANSI causes mojibake like `MisÃ©ricorde`).

## Projection (the `projection` symbol)

Markers carry **master-pixel** `(px, py)` coordinates that map 1:1 onto the master tile image
(1px = 1 game unit). Both the web app and the build scripts must agree on these constants:

| Constant | Value | Used by |
|---|---|---|
| `offset_x` | -7168 | `xy()` in index.html, `Project()` in the build scripts |
| `offset_y` | 16640 | same |
| `native_zoom` | 6 | tile pyramid depth (`ceil(log2(10496/256))`) |
| `tile_size` | 256 | Leaflet tile size + tile pyramid |
| `img_size` | 10496 | master image dimension |

`index.html` holds these in `CONFIG` and the `xy()` / `fromLatLng()` helpers; the PowerShell build
scripts hold them as `$OFFSET_X` / `$OFFSET_Y` and the native-zoom math. **If the app and the build
scripts ever disagree, every pin misaligns from the tiles.** When you change any of these:

1. Update `index.html` and all three build scripts together.
2. Update the `projection` symbol in `symbols/manifest.json`.
3. Re-run `python scripts/align.py lock` and commit `manifest.json` + `manifest.lock`.

## Map layers (masters)

Three pre-rendered tile pyramids under `ctiles/`, surfaced as base layers in the app:

- `M00` — overworld (The Lands Between)
- `M01` — underground (Siofra / Ainsel / Deeproot / Nokron)
- `M10` — DLC (Land of Shadow)

(`M11`, DLC underground, has no markers and is excluded from the published site.)
