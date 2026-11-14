# Frontend conventions (all dashboards)

> Reference doc, read on demand — read it before changing anything under `docs/`. The always-loaded rules (privacy, ground rules, security) live in [`CLAUDE.md`](../CLAUDE.md); where the two differ, `CLAUDE.md` wins.

- Vanilla HTML + Chart.js 4.4 — no frameworks, no build step
- Cache-bust pattern: `data.json?t=${Date.now()}` — always keep this; on the pages that load
  shared.js use the `bust(url)` helper from it (the purely public pages keep it inline)
- **Page-asset cache-bust:** static `<script src="js/<page>.js?v=N">`/`<link ... shared.css?v=N>`
  version params **must be bumped on every change to that file** (mirror of the SRI-bump rule for
  CDN versions) — the JSON `?t=` bust refreshes data but not the page assets, so a forgotten bump
  shows fresh data through stale JS (bit us twice, juli 2026)
- **JS layout:** per-page script in `docs/js/<page>.js`; shared Gist/token/artefact-gist logic
  plus `bust()`/`gistReadJSON()`/`artefactReadJSON()` in `docs/js/shared.js` (loaded *before*
  the page script on index/mowing/vent — the writer pages — **and sinds de privacy-sweep aug 2026
  ook op window/grafiek**, die geen schrijf-functie hebben maar wél een privé artefact lezen).
  **Discoverable login (aug 2026):**
  a `🔑 Account`-button (id `account-btn`, auto-bound by `shared.js` on `DOMContentLoaded`) on
  each of those pages opens `openAccountSettings()` — view/(re)enter gist-id, token and
  artefact-gist-id at any time, or type `reset` to clear all three. `localStorage` is shared
  across the whole Pages origin, so configuring on any one page covers the rest.
  Before this there was only the reactive prompt on a failed load or first save — no visible
  place to (re)configure. The wat-als-speeltuin + plattegrond-renderer +
  hun helpers (`fmt`/`dirName`/`beaufort*`/`normState`) live in `docs/js/speeltuin.js`,
  loaded *before* the page script on vent (plain globals, no modules). The shared `COLORS` palette lives in
  `docs/js/theme.js`, loaded *before* the page script on **every** dashboard (index, model,
  window, grafiek, vent, mowing); camping.html keeps its own posterthema and loads neither.
  CSP `script-src` has **no `unsafe-inline`**: never add inline `<script>` blocks or `onclick=`-style
  attributes — wire events with `addEventListener`/delegation and `data-*` attributes.
- **CSS layout:** rules shared by the dashboard pages live in `docs/css/shared.css` (linked *before*
  the page `<style>` block, so page-specific deviations win at equal specificity). camping.html has
  its own posterthema and deliberately doesn't use it.
- CDN scripts carry SRI `integrity` hashes (computed from the npm tarballs); bump version → recompute.
