# Project 11: Weekjournaal (Weekly Digest)

> Reference doc, read on demand — read it before changing this project's files. The always-loaded rules (privacy, ground rules, security) live in [`CLAUDE.md`](../CLAUDE.md); where the two differ, `CLAUDE.md` wins.

**Goal:** One Sunday-evening Telegram digest (orchestrator target zondag 20:00) summarizing the week across the pipelines — pure aggregation of the already-published artefacts, no new data fetching.

## Files
- `weekjournaal.py` — per-section pure functions over the local checkout artefacts (env-path overrides for tests)
- `.github/workflows/weekjournaal.yml` — fallback cron zo 20:40 + guard-job; `contents: read`; no in-job retry (no external API besides Telegram, which has its own retry)

## Sections (each independently optional — missing/stale artefact → section silently omitted)
- 🌱 **Tuinwater** (`docs/data.json`): week-window (today−6..today, non-forecast days) Σ precip / Σ ET0 / Σ per-zone irrigation + current `lawn_status`/`shrubs_status` depletion.
- 🌾 **Maaien** (`docs/mowing_data.json`): mows this week from `mowings`, `accum_today` vs `params.READY_GU_effective`, next-mow prediction / maairijp / winterrust.
- 🧠 **Tweeling** (`docs/vent_learned.json`, env-override `VENT_LEARNED_PATH`): RMSE now vs the last non-`held` point ≥ `RMSE_LOOKBACK_D 6.5` days back (fallback: earliest) + skill + trend arrow.
- 🌤️ **Weer** (`docs/data.json`): Tmax range (bias-corrected where available), week precip, warmest day.
- 📡 **Station** (`docs/accuracy_data.json`): overall bias one-liner, only when the (manual-dispatch) check is younger than `STATION_MAX_AGE_D 30` — stale → omitted rather than misleading.
- All sections `None` → no message. Defensive truncation at `MAX_LEN 4000` (< Telegram's 4096; `send_telegram` doesn't chunk).

## Relation to other projects
Read-only aggregation of the published artefacts of Projects 1, 5, 7, 13 from the local checkout (the `mowing_advisor` `open()`-pattern). Stateless. Telegram secrets only.
