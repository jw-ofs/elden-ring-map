# Elden Ring — Interactive Map

A fast, offline-capable interactive map for Elden Ring (base game + *Shadow of the Erdtree*),
in the style of Map Genie: pan/zoom, category filters, search, marker popups with item stats,
step-by-step questline tracking, and progress tracking that saves in your browser.

**Live map:** https://jw-ofs.github.io/elden-ring-map/

## Features

- **Overworld, Underground, and DLC (Land of Shadow)** map layers, built from datamined master tiles.
- **~1,860 markers** across graces, bosses, weapons, armor, talismans, spirit ashes, ashes of war,
  sorceries & incantations, golden seeds, sacred/crystal tears, great runes, larval tears,
  memory stones, whetblades, and quest NPCs.
- **27 questlines** with ordered, location-anchored steps and rewards.
- **Rich popups** — weapon attack/scaling/requirements, armor negation/poise grids, spell costs, etc.
- **Marker clustering, search + fly-to, region labels, a completion dashboard, hide-found**, and
  shareable progress (export/import).
- **Progress is private to you** — stored in your browser's `localStorage`, nothing is uploaded.

## Usage

Just open the live link. Click a marker to mark it found; your progress saves automatically in that
browser. Open it on a phone or tablet too — it works on any modern browser.

## Running locally

The site is fully static (no build step, no server logic required). Either:

- Open `index.html` directly, **or**
- Serve the folder with any static server, e.g. `powershell -File server.ps1` (serves on `http://localhost:8777`).

### Regenerating the data

The marker/quest/item data is generated from the community datamining project by PowerShell scripts:

```
build-markers.ps1    # markers.js   (pins, deduped & projected)
build-quests.ps1     # quests.js    (questline steps, from questlines.json)
build-itemdata.ps1   # itemdata.js  (popup stats) + downloads item icons
```

## Credits & attribution

- **Map tiles & game data** are datamined from the community project
  [EthanShoeDev/elden-ring-compass](https://github.com/EthanShoeDev/elden-ring-compass).
- **Map rendering** by [Leaflet](https://leafletjs.com/) + [Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster) (bundled under `vendor/`).
- Questline details verified against community wikis (Fextralife, Game8, and others).

*Elden Ring* and all related assets are © FromSoftware, Inc. and Bandai Namco Entertainment.
This is an unofficial, non-commercial fan project and is not affiliated with or endorsed by them.
