# Code Quality Audit 2 — Pineapple Under The Sea

**Date:** 2026-08-13 · **Scope:** all 12 pipelines (P1–P7, P9–P11, P13–P14), shared modules, 20 workflows, frontend (docs/), tools/, tests/, committed data shards.
**Dimensions:** dead code · duplication · maintainability · **privacy/secret leakage** (new axis).
**Predecessor:** [AUDIT.md](AUDIT.md) (2026-07-01, 8 pipelines). §5 re-checks its open backlog.

Line numbers refer to the state *before* the fixes in [Fixed in this audit](#fixed-in-this-audit).

---

## Executive summary

| Dimension | Verdict |
|---|---|
| **Privacy/secrets** | **Exemplary on secrets, was structurally leaky on privacy — now remediated where decided.** Zero credentials/tokens/station-IDs anywhere in the tree; `sanitize_error` at every credentialed call site; workflows follow every repo security rule. But published artefacts pinned the home location to a ~11 m cell — sharper than the station ID the repo keeps secret precisely for location reasons — and a child's first name was a first-class identifier across code, Pages artefacts and Telegram templates. **Both fixed in this audit** (coords → ~1 km, room pseudonymised). Family schedule, house survey and occupancy-trace exposures remain as **documented, accepted choices** (§4c). |
| **Maintainability** | **B+ — high discipline, drift-prone structure.** Zero bare `except:`, zero mutable default args in 34k lines, ~600 property-style tests, exceptional constant documentation. Real risk was concentrated in "a fix landed on one copy and never travelled": the missing `run_guarded` on the calibration-source pipeline, one state loader that catches nothing, and three workflows still on the naive push block — all **fixed in this audit**. `vent_twin.py`'s god-main and the `_`-private cross-module imports remain the top open items. |
| **Duplication** | **The biggest open debt, unchanged in character since July.** The warmup+anchor physics sequence exists twice (night forecast ↔ koelplan) with constants tripled; six drifting `load_state` copies; 9× guard-job YAML; the FAO-56 JS port has no golden test while the vent stack demonstrates exactly that fix. One duplication class was a *latent bug* (zero-span interpolator guard, 3 of 4 copies wrong) — **fixed in this audit**. |
| **Dead code** | **Substantially clean — ~45 lines total** (§1). Two orphaned helpers of the deliberately-removed `backfill_rmse_history` complex, two consumer-less back-compat aliases, one abandoned constant, and one unreachable-from-UI frontend feature. Nothing structural. |

**Fixed in this audit** (details at the bottom): the 5-item must-fix bundle, coordinate coarsening, room pseudonymisation incl. data-shard migration and the `TADO_ZONE_ALIASES` bridge. `ruff` + 677 tests + golden vector green.

---

## 1. Dead code

**Method:** every `def`/module-level constant/JS `function` name cross-referenced against all usage forms (py/js/html/yml, string references and workflow-dispatch filenames included); module wiring checked against workflow entrypoints; state files checked against readers. `ruff` (incl. unused imports) green.

**Verdict: substantially clean — ~45 lines total.** The July audit already removed the one large block (~75 lines of email code); the P8/P12 → P13 rebuild left only two stragglers.

| # | Confidence | Where | Finding |
|---|---|---|---|
| DC-1 | Confirmed | `vent_fit.py:517` `_window_naive`, `:532` `timed_residuals_from_sim` | ~40 lines, zero references anywhere. Both docstrings reference `backfill_rmse_history` — the safety-net complex CLAUDE.md documents as **deliberately left out** of the P13 rebuild. These are its orphaned helpers; the removal just never reached them. Safe to delete. |
| DC-2 | Confirmed | `soil_model.py:235-236` | Back-compat aliases `seasonal_kc = seasonal_kcb` and `KC_SEASONAL = KCB_SEASONAL`, commented "zodat externe importeerders (tests etc.) niet breken" — but zero importers exist; tests and `model.js` all use the new names. The alias guards consumers that aren't there. |
| DC-3 | Confirmed | `vent_io.py:95` | `CALIB_COVERAGE_WARN_H = 24.0` — unused constant whose trailing comment is cut off mid-sentence ("na AC-/verwarmings-/"): an abandoned coverage-warning feature that never got its implementation. Delete or implement. |
| DC-4 | Likely (unreachable feature, not dead by intent) | `docs/js/shared.js:51` `forgetCredentials()` | Complete, working credentials-wipe flow with zero callers in any page — unreachable from the UI, usable only via the browser console, undocumented. Wire a small "vergeet token" link on the writer pages or remove it. |

Everything else checked out wired: all root modules are workflow entrypoints or imported, all state/JSON files at the root have readers, no unused module constants beyond the above, and no commented-out code blocks were found. The always-`True` flag pair in `mowing_advisor` is reported under maintainability (M-10) — technically reachable, practically frozen.

---

## 2. Duplication

### Must address

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| D2-1 | **High** | `night_forecast.py:265-330` ↔ `cooldown_notify.py:53-95` | The warmup+anchor pipeline (load house → weather → context → warmup timeline → routines → seed → simulate → anchor) is duplicated between the two evening runners, with its constants defined **three times** (`WARMUP_H` in both runners *and* already exported by `vent_io.py:90`; `ANCHOR_MAX_STALENESS_MIN` twice). These two scripts message about the *same night* 2.5 h apart — divergence produces contradictory advice with no error signal. | **Open** — extract `vent_io.warmup_and_anchor(...)`, delete the local constants |
| D2-2 | **High** | `vent_physics.py:1479`, `vent_io.py:618`, `tools/vent_diagnostics.py:71` vs `window_advisor.py:745` | Four linear interpolators; three used `max(1.0, span)` which *fabricates a 1-second span* on duplicate-timestamp samples (exactly what double dispatches produce) instead of the `span <= 0 → v0` guard the fourth already had. Duplicated latent bug — the fix never travelled. | **Fixed** — all three now carry the guard |

### Should address

| # | Sev | Where | Finding |
|---|---|---|---|
| D2-3 | Med | `check_and_notify.py:91`, `mowing_advisor.py:496`, `sandbox_notify.py:45`, `shade_advisor.py:190`, `heating_experiment_notify.py:128`, `window_advisor.py:1085` | Six hand-rolled `load_state`/`save_state` pairs drifting on four axes: encoding, trailing newline, exception coverage, and `last_updated` timezone (`window_advisor` stamps **local** where five siblings stamp UTC; `shade_advisor` stamps nothing). The no-catch case is fixed (see M-2); the rest wants a `shared_const.load_state/save_state` with the Gist-backed variant as the documented exception. `advice_slot_open` is byte-identical in `check_and_notify.py:108` and `mowing_advisor.py:482`. |
| D2-4 | Med | 9 workflows | The dedup guard-job is copied 9× (`gh run list --jq` filter character-identical; only filename + since-hour vary). ~150 removable lines via a reusable `workflow_call` workflow parameterised on `(workflow_file, since_hour)`. |
| D2-5 | Med | `soil_model.py:314-342` ↔ `docs/js/model.js:57-85` | The full FAO-56 core (ET0, `seasonal_kcb`, `temp_factor`) is ported to JS with **13 re-declared physics constants** and *no golden test* — while the vent stack solved the identical problem with `tools/test_golden.js` (which caught a stray NUL byte worth 0.098 °C). A one-character `KCB_SEASONAL` edit in Python goes undetected in JS. Either publish the constants via `data.json` or add a model.js golden vector. |
| D2-6 | Med | `soil_model.py:659/701/738`, `station_accuracy.py:82`, `window_advisor.py:429/493` | The WU URL template + `observations[0]`/`metric` unwrap ×6 across three files, two of which feed the bias calibration the third consumes — a half-applied param change silently biases the correction. A tiny `wu_api.py` (own retry, no `http_util` dep) preserves the documented boundary. |
| D2-7 | Med | `docs/js/speeltuin.js:583` ↔ `docs/js/vent_core.js:44` | Two copies of the same partial-pivot Gauss solver in one page's global scope, plus `speeltuin.js:552-690` re-implementing the pressure network — the *speeltuin* runs an unverified third physics copy while the golden test covers only `vent_core.js`. Its header still credits a module retired in the P8→13 rebuild. |
| D2-8 | Med | `window.js:6-42` ↔ `grafiek.js:12-67`, `index.js:65-67` | Byte-identical page-head (loadData/ageLabel/staleness banner) in two pages; the **front page copy has drifted** — `index.js` lost the >3h staleness banner its siblings have. Move `ageLabel` + banner into `theme.js`. |
| D2-9 | Low-Med | `window_advisor.py:165`, `soil_model.py:318-321`, `docs/js/model.js:61` | Magnus/Tetens saturation vapour pressure ×3 → `shared_const.sat_vapour_pressure_kpa`. Also: `DRY_RUN` send gate ×6 (already drifted on parse_mode) → `notify.send_or_print`; Chart.js tooltip config ×11 (`vent.js:231` already factored `ventTooltip()` — propagate it); `TADO_CLIENT_ID`/`TOKEN_FILE` duplicated between `tado_auth_bootstrap.py:28` and `window_advisor.py:217`. |

---

## 3. Maintainability

### Must address

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| M-1 | **High** | `station_accuracy.py:760` | The only runner violating the repo's own ground rule: `main()` called bare, no `run_guarded`. A crash of the monthly cron (which nobody watches) would silently age `SOLAR_BIAS_SLOPE` — the calibration constant two other projects consume; the file itself documents this exact staleness class. | **Fixed** — `run_guarded(main, "station-accuracy")` |
| M-2 | **High** | `heating_experiment_notify.py:128` | `load_state` caught nothing: a corrupt committed state file ⇒ crash Telegram every Monday 21:00 until hand-repaired. Safe to degrade (the arm choice is date-derived; state is logbook, not steering). | **Fixed** — graceful default + sanitized warning |
| M-3 | **High** | `night-forecast.yml:97`, `station-accuracy.yml:79`, `twin-eval.yml:92` | Push-hardening (`rebase --abort` + `-X theirs` + hard `exit 1`) existed in 6 of 9 committing workflows; these three were still on `pull --rebase \|\| true; git push`, which leaves the repo mid-rebase on conflict and drops the commit silently — for night-forecast that is the verification log the project exists to accumulate. | **Fixed** — hardened block backported |
| M-4 | **High** | CLAUDE.md:79/82/95 vs `soil_model.py:31/136` | The spec contradicted the code on domain numbers: shrubs `Zr` 0.42 (doc, twice, incl. the schema block) vs 0.50 (code + live artefact); `fc` 0.75 vs 0.90. The repo's drift defence is prose, and it had failed silently on numbers that materially change the water balance. | **Fixed** — doc updated. Structural remedy below (M-8) |

### Should address

| # | Sev | Where | Finding |
|---|---|---|---|
| M-5 | Med-High | `vent_twin.py:104/259/476` | The real god-module (worse than the bigger files): 71 % of the file in 3 functions; `build_dashboard` takes **22 parameters** and works around its own arity with an untyped `bundle` dict whose key typos surface as runtime `KeyError` in the publish path. Split into a `DashboardInputs` dataclass + named phases (fetch → filter → calibrate → publish). By contrast `window_advisor.py` (1933 lines) is genuinely decomposed — fat orchestration shell only. |
| M-6 | Med-High | `vent_twin.py:47-51` + 10 further sites | **13 underscore-prefixed `vent_physics`/`vent_io` names are load-bearing for five pipelines** (P9/P10/P13/P14 + tools). A legitimate "internal" refactor breaks four projects at import time in production. Promote the genuinely shared names to public. |
| M-7 | Med | tests | Coverage gaps concentrated exactly where July predicted: `cooldown_notify.main` (102 L, the duplicated warmup/anchor block) has no test file; `soil_model`'s ~600 fetch/merge/bootstrap lines have zero coverage while the science core is excellently tested. One **flaky test** observed: `tests/test_night_forecast.py::test_main_ijkt_de_massaknoop_mee` failed once in-suite, passes in isolation and on re-runs — likely order/time dependence worth pinning. |
| M-8 | Med | CLAUDE.md ↔ code | The doc is ~1100 lines of spec for 34k lines of code with no sync mechanism; it has now drifted three times on load-bearing numbers. The repo's own best pattern (`assert_checkout_pinned`, `test_golden.js`) is the remedy: assert the doc's schema block against `soil_model.ZONES` in a test. |
| M-9 | Low-Med | `.github/workflows/ml-dataset.yml:42`, `requirements-tools.txt` | `pandas`/`pyarrow` are declared only inline in a workflow `pip install` line, unpinned, and missing from `requirements-tools.txt` which claims to enumerate the offline-tool deps. |
| M-10 | Low | `mowing_advisor.py:62/67` | Two module-level always-`True` flags (`SELF_CALIBRATE`, `BOLT_SUPPRESS_HEAT_DERATE`) guarding never-exercised `False` branches — either test the `False` path (cf. `DIRECT_IS_HORIZONTAL`, which is a live tested switch) or inline them. Also: `SEASON_MONTHS` names *summer* in `night_forecast.py:85`/`vent_suggest.py:47` and *winter* in `heating_experiment_notify.py:65` — rename the heating one `HEATING_SEASON_MONTHS`. |

---

## 4. Privacy / secret leakage

Classified per the agreed bar: **(a) credentials and (b) location = must-fix; (c) personal-life inference = informed choice; (d) accepted/documented.**

### (a) Credentials — clean, verified

- Zero tokens, API keys, Gist IDs, station IDs, `.env`/key files in the working tree (searched incl. `docs/`, `data/`, `tools/`, tests, workflows; the only hits are the deliberate fake fixtures in `tests/test_notify.py` etc.).
- `notify.sanitize_error` scrubs `apiKey=`, **`stationId=`**, generic token params, bot-token URLs and Gist paths, and is applied at every WU/Gist/Telegram/HTTP boundary (18 sites verified). `run_guarded` sanitizes the top-level FATAL.
- Workflows: no `pull_request`/`pull_request_target` anywhere; secrets only bound via `env:`; minimal `GITHUB_TOKEN` permissions; no env dumps; no non-`actions/` third-party actions.
- Pages dashboards: `gh_token` lives in `localStorage`, is sent **only** to `api.github.com` in a header, never in URLs or console; the Gist ID ships as a placeholder, never baked in. The tado `client_id` is the well-known public device-code app ID — correctly not a secret.
- Minor gap: `vent_twin.py:717` prints a raw `{e}` in a public workflow log (no credential reaches that path today, but it contradicts the never-raw-`{e}` rule). Two more in local-only tools. **Open, trivial.**
- **Caveat:** this session ran on a shallow clone — full git *history* could not be audited. A full-depth clone through gitleaks/trufflehog remains the one unclosed credentials question. **Open, recommended.**

### (b) Location — was the headline finding; fixed

The repo keeps `WU_STATION_ID`/`WU_NEIGHBOUR_IDS` secret *because station IDs reveal the home location* — yet 4-decimal coordinates (a ~11 m × 7 m cell, i.e. a single dwelling) were committed **and served via GitHub Pages** in seven places: `shared_const.py`, `house_model.json`, `docs/data.json`, `docs/accuracy_data.json`, `docs/js/ipad.js`, `docs/js/model.js`, plus prose in `docs/index.html`. The public artefact was a sharper location fix than the protected secret.

**Fixed in this audit:** all sources coarsened to 2 decimals (~1 km — negligible for every consumer: Open-Meteo grids are 1–10 km, ET0/sun-position shifts are noise), generated artefacts scrubbed to match what the next runs write, cache-bust params added so cached devices pick it up. The station-ID policy itself was verified to hold (no real ID anywhere, neighbours published only as "buur 1..3").

**Residual — gesloten (privacy-assessment aug 2026):** de geschiedenis is sindsdien tot één initial commit gesquasht; een scan over álle bereikbare commits vond geen enkel 4-decimalen-paar en geen legacy-naam meer. Kanttekening die ervoor terugkomt: de strings die de privacy-fix-branch van aug 2026 zelf verwijdert (buurtnaam, één-decimaal-afstand) blijven in de pre-fix commits van díe branch staan — eigenaar geïnformeerd; een nieuwe squash is een eigenaarsbeslissing.

### (c) Personal-life inference — one item remediated by choice; the rest accepted

| Item | Exposure | Decision |
|---|---|---|
| Child's first name as room identifier | Was first-class in code, `house_model.json`, published Pages artefacts, dashboards, Telegram templates and committed data shards | **Fixed in this audit** — pseudonymised repo-wide (`nursery`/"Kinderkamer"), shards + stateful artefacts migrated, `TADO_ZONE_ALIASES` secret added so the private tado-app zone name never needs to match the public name. De naam-in-historie-zorg is met de squash (zie (b)) gesloten. |
| Weekly family schedule (`weather_briefing.py` blocks: departure/daycare/sport windows) | In source **and published verbatim** in `docs/js/ipad.js` | **Alsnog gefixt (privacy-sweep aug 2026)** — blokken naar het `BRIEFING_BLOCKS`-secret, generieke dagdelen als terugval, het iPad-dashboard in zijn geheel verwijderd; bewaakt door `test_geen_weekrooster_in_de_broncode`. |
| Full house survey + live opening state (`docs/vent_data.json` `house_meta`/`controls`: per-room floor-plan positions, window sizes/orientations, live open/closed per opening) | Pages visitors | **Alsnog gefixt (tweede privatiseringsronde aug 2026)** — de vent-artefacten leven in de privé artefact-gist en `vent.html` is token-gated. Residu (privacy-assessment aug 2026): de huisgeometrie/oriëntatie in het publieke `house_model.json` zelf is inherent aan de fysica en **geaccepteerd**; de afstands- en buurtnaam-lekken die dit residu scherp maakten zijn in diezelfde assessment gedicht. |
| Occupancy trace in `data/twin2_history/` (373 minute-stamped resident-reported events whose hour histogram reproduces the household rhythm; `paused` readable as away-marker; bathroom humidity as shower-time trace) | Repo readers | **Gefixt in stappen**: openingen-snapshots + `paused` uit de shards (privacy-scrub aug 2026), badkamer eruit (`exclude_from_shards`), en met de privacy-assessment (aug 2026) verhuizen de shards zelf naar de privé Gist (`twin2_history_<YYYY-MM>.json`, zelf-uitvoerende migratie) — de kwartier-kamerreeksen verdwijnen daarmee uit de publieke boom; de reeds gecommitte maanden blijven in de git-historie (zie (b)). |

### (d) Accepted / documented all along

Public tado `client_id`; owner name/email in git commit metadata (normal); `DASHBOARD_URL` as a plain variable; SRI-pinned CDN scripts (credit-side).

---

## 5. July backlog re-check (AUDIT.md)

| Item | July status | Now |
|---|---|---|
| R1 token-rotation local backup | Open | **Still open** — touches protected Gist-write path, needs deliberate decision. Still the top reliability risk. |
| R7 push-race daily jobs | Open | **Resolved** — hardened block reached 6 workflows since July; this audit backported the last 3 (M-3). |
| R9 `load_soil_days` all-or-nothing | Open | **Still open** (`mowing_advisor.py:154`). |
| R10 three `generated_at` formats | Open | **Improved** — `shared_const.utc_now_iso` exists; call-site variants remain (see D2-3's timezone drift). |
| S2 loop jobs whole-job `contents: write` | Open | **Still open** (`window-notify.yml:24`, `vent-notify.yml:20`). |
| S3 `inputs.days` unvalidated | Open | **Still open.** |
| S5 innerHTML escaping | Open | **Still open.** |
| M2 god-modules | Open | **Still open**; the worst offender is now `vent_twin.py` (M-5), successor to the retired `airflow_model.py`. |
| M5 solar_bonus magic numbers · M6 `IRRIGATION_RATES` placement + unreachable `return 0.75` (`soil_model.py:231`) · M7 `_room_dashboard_row` name collision (`vent_twin.py:104` ↔ `window_advisor.py:1483`) | Open | **All still open** (cosmetic tier). |
| D1 Open-Meteo boilerplate · D3 Gist/state loaders · D5 workflow YAML · D6 frontend copy-paste · D7 interception curve ×2 (`soil_model.py:293/407`) · D8 `accuracy.js` off `theme.js` | Open | **All still open** — superseded by the sharper findings in §2. D4 (WU refinement wrapper) partially resolved by `vent_io.refine_outside_now`; the URL-template layer remains (D2-6). |

---

## Fixed in this audit

All behaviour-preserving or strictly hardening; no FAO-56 formulas, soil parameters, Gist-write logic or artefact schemas touched (the pseudonymisation renames identifiers, not semantics). `ruff` green, **677 tests** green, golden vector (`node tools/test_golden.js`) **PASS**.

1. **Must-fix bundle** — `run_guarded` on `station_accuracy`; graceful `load_state` in `heating_experiment_notify`; hardened push block in `night-forecast`/`station-accuracy`/`twin-eval`; CLAUDE.md soil numbers (`Zr`, `fc`); zero-span guard in 3 interpolators.
2. **Location coarsening** — coordinates to 2 decimals in `shared_const.py`, `house_model.json`, `docs/js/ipad.js`, `docs/js/model.js`, the one full-precision test, and scrubbed in the generated `docs/data.json`/`docs/accuracy_data.json`; `?v=` cache-busts added to `ipad.html`/`model.html`.
3. **Room pseudonymisation** — room id, element ids, labels, tado/artefact name, Telegram texts, workflow names, docs/assessments, tests, golden vectors, surrogate column contract, uncertainty bands, month shards (incl. `ac_room` values) and the stateful generated artefacts (`vent_learned.json` params migrated so the room's learned state survives; `window_data.json` history keys migrated for continuity). New optional secret **`TADO_ZONE_ALIASES`** bridges published name ↔ private tado-app zone name.

**Post-merge notes for the owner:**
- Optionally set the `TADO_ZONE_ALIASES` secret (`{"Nursery": "<zonenaam in de tado-app>"}`) *or* rename the tado zone to `Nursery` in the app — without either, that room drops out of `window_data.json` until matched.
- Entries in the **openings-Gist** (`house_openings.json`) written before the rename reference old element ids and will be ignored by the reconstruction; re-report the current window stands once via the meldmodal after merging.
- The per-room advice state in the secret Gist (`window_state.json`) keys on the old room name; that room restarts cold (one advice cycle) after the rename.

## Recommendations backlog (highest value first)

1. **Full-depth history secret scan** (gitleaks/trufflehog on an unshallow clone) — grotendeels ingehaald door de squash naar één initial commit (privacy-assessment aug 2026: alle bereikbare commits gescand, geen legacy-coördinaten of -namen meer); een tool-gedreven credential-scan blijft goedkoop en kan geen kwaad.
2. **Extract `vent_io.warmup_and_anchor`** shared by night forecast + koelplan (D2-1) and delete the tripled constants — prevents two messages about the same night diverging.
3. **R1 token-rotation local backup** — unchanged from July, still the top reliability risk, still needs a deliberate decision on the protected path.
4. **`shared_const.load_state`/`save_state`** + UTC-stamp convention (D2-3); reusable guard-job workflow (D2-4).
5. **model.js golden test or artefact-published constants** (D2-5) — the vent stack's own pattern, applied to the soil twin.
6. **Split `vent_twin` main/dashboard** (M-5) and promote the 13 load-bearing `_`-private names (M-6).
7. **Doc-drift assertion** for the CLAUDE.md schema block (M-8) — turn the prose contract into a red build, the repo's own proven trick.
8. Cosmetic tier when nearby: the ~45 dead lines of §1 (DC-1..3 are pure deletions; DC-4 wants a one-line UI hook or removal), tooltip/`ageLabel` helpers + front-page staleness banner (D2-8), Magnus/Tetens + DRY_RUN helpers (D2-9), dead flags + `SEASON_MONTHS` rename (M-10), `pandas`/`pyarrow` pinning (M-9).
