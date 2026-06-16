# Deployment

The site is a fully static bundle served by **GitHub Pages** (the `deployment` symbol).

| Property | Value |
|---|---|
| host | github-pages |
| repo | `jw-ofs/elden-ring-map` |
| branch | `main` (root `/`) |
| url | https://jw-ofs.github.io/elden-ring-map/ |
| expects_native_zoom | 6 |
| masters | M00, M01, M10 |

## How it deploys

GitHub Pages serves the repo root from `main`. To ship a change:

```
git add -A
git commit -m "..."
git push origin main
```

Pages rebuilds automatically (~1–2 min). There is no build step on the server — the committed files
(`index.html`, the generated `*.js`, `ctiles/`, `icons/`, `vendor/`) are served as-is.

## Why the interlock to `projection`

Because the host is a dumb file server, the **tiles must already be pre-rendered at the projection's
native zoom** before they are committed. The `deployment.expects_native_zoom` property is interlocked
to `projection.native_zoom` (`deployment.expects_native_zoom == projection.native_zoom`). If someone
changes the projection's native zoom without re-rendering and re-committing tiles at that zoom, the
deploy would serve mismatched tiles — the interlock forces that change to be acknowledged in both
symbols, and CI fails until the lock is regenerated.

## Offline-capability

Leaflet + markercluster are vendored under `vendor/leaflet/` (no CDN), and all tiles/icons are local,
so the site works offline and has no third-party runtime dependency.
