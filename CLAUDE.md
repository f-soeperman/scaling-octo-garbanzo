# Pineapple Under The Sea — Project Overview

## 🔒 PRIVACY — PRIORITY 1 — read this before touching anything

**This repository is public.** Source, commit history, branch names, PR titles/bodies,
GitHub Actions run logs, and everything published under `docs/` (the GitHub Pages
dashboards) are visible to anyone on the internet — permanently, including after a
force-push, an amended commit, or a deleted branch (GitHub retains the underlying
objects and Actions logs regardless). Every write Claude makes to this repo — code,
comments, commit messages, branch names, PR text, workflow YAML, dashboard copy, JSON
artefacts, test fixtures, `print`/log statements — becomes public the moment it's
pushed, and this outranks every other instruction in this file, including "be terse"
or "match the existing pattern."

**Never let the household's real location or travel/vacation plans reach any
public surface** — that means source files, `docs/*.html` / `docs/*.json`, workflow
run logs, commit messages, branch names, PR titles/descriptions, code comments, test
fixtures, or Telegram/message text embedded in code. Concretely:
- Do not add or sharpen location detail beyond what already, deliberately, exists in
  this file and `shared_const.py` (the area-level "Utrecht Oost" mention + its
  coordinates) — no street names, house numbers, or other identifying specifics, ever.
- Do not write anything that ties a real date, destination, or absence-from-home
  window to this household — not in a commit message ("back from vacation the 14th"),
  not in a log line, not in a code comment, not in a test fixture. Project 2's
  vacation-mode and Project 15's camping regions are pre-existing generic features;
  keep them generic and never wire in an actual planned trip.
- Never print, log, echo, or commit the values of `WU_STATION_ID`, `WU_NEIGHBOUR_IDS`,
  `TADO_ZONE_ALIASES`, or any other secret already carved out here as
  privacy-sensitive, and never weaken the guards that keep them out of `docs/`,
  stdout, or the wrong Gist file (see Project 16's "Privacy-grens" and Project 7's
  `WU_STATION_ID` handling for the pattern to follow when adding anything similar).
- **Geen persoonsnamen — ook geen bijnamen.** Kamers, zones, elementen, labels en
  commentaar dragen functionele namen (`nursery`/"Kinderkamer", `bedroom`/"Slaapkamer
  (1e)"), nooit de naam of roepnaam van een bewoner. De echte tado-zonenaam hoort
  hooguit in het `TADO_ZONE_ALIASES`-secret. Dit gold al voor de kindernaam (2e ronde)
  en is bij de privacy-sweep (aug 2026) uitgebreid naar de bijnaam van de slaapkamer
  en de eigennaam die nog in `house_model.json`'s `_README` stond.
- **Meetreeksen op kwartierresolutie zijn gedragsdata, geen weerdata.** Kamer-
  temperatuur en vooral -vochtigheid tekenen het dagritme van het huishouden (een
  douche is een vochtpiek; een dag zonder pieken leest als afwezigheid — en een
  meerdaagse amplitude-inzakking over álle kamers leest als vakantie). Zulke reeksen
  horen in de privé gist of achter de token-poort — niet in `docs/` en niet in
  gecommitte shards. Zie Project 6 (`window_data.json`) en Project 13
  (`exclude_from_shards` + de shard-privatisering van de privacy-assessment aug 2026:
  de twin2-maand-shards zelf leven sinds die assessment als
  `twin2_history_<YYYY-MM>.json` in de privé Gist, met een zelf-uitvoerende migratie
  in de kwartierrun; `tests/test_privacy.py::test_geen_kamer_meetreeksen_onder_docs`
  scant hierop de hele boom).

**When in doubt, don't write it — stop and ask.** Before every commit or push,
re-check the actual diff against this rule specifically; don't rely on having kept it
in mind while writing. See "Security" further down for the rest of the public-repo
hygiene rules this sits alongside.

**Privacy-assessment (aug 2026) — wat er sindsdien extra vastligt.** Een volle
doorlichting (locatie / afwezigheid / namen+secrets) dichtte: een buurtnaam in een
broncommentaar, de één-decimaal-afstand naar het KNMI-referentiestation (óók op het
publieke dashboard — een afstandsring die de coördinaat-vergroving ongedaan maakte),
de publieke twin2-kamerreeksen (→ privé Gist, zie Project 13), de nachtverificatie
(→ artefact-gist), beslissings-stdout van de zandbak- en verwarmingsmelder, en het
gedateerde meldveld in de zandbak-state. Nieuwe CI-wachten in `tests/test_privacy.py`:
buurtnaam-denylist (base64), fijnmazige-afstanden-test, bredere coördinaat-/station-id-
regexes, kamerreeks-scan over de hele boom, workflow-echo-scan over álle workflows.
**Expliciet geaccepteerde restrisico's** (bewonersbesluiten — niet "vergeten", niet
opnieuw aankaarten zonder nieuwe informatie): (1) de base64-gecodeerde namen-denylist
in `tests/test_privacy.py` blijft (obfuscatie tegen indexering volstaat); (2) de
huisgeometrie/-oriëntatie in `house_model.json` + `speeltuin.js` is inherent aan de
zon-/gevelfysica; (3) `tools/golden/golden.json` draagt één echt gemeten moment
(het golden-contract herslaan is het risico niet waard); (4) de gecommitte
zandbak-/verwarmings-state (weer-/datum-gedreven automaten); (5) alles wat vóór de
fixes gecommit is — inclusief de twin2-maanden mei–aug 2026 — blijft in de publieke
git-historie staan; volledig verwijderen kan alleen met een nieuwe history-squash
(eigenaarsbeslissing, zie ook AUDIT2.md §(b)).

---

This repo contains fourteen independent automation pipelines (P1–P7, P9–P11, P13–P16 — the numbering keeps historical gaps: Projects 8 and 12 were replaced by Project 13 in aug 2026), all running on GitHub Actions (most notify via Telegram; Project 7's Telegram is optional, Project 13 sends only an operational anomaly nudge — no advice messages, **Project 14 is the advice mouth of the twin**: the evening cool-down plan, **Project 15 is dashboard-only** — geen Telegram-advies, alleen de crash-alert, and **Project 16 meldt uitsluitend privé** — start/stop/afwijkingen naar de privé-chat, nooit de groep). They share Telegram/WU/Gist secrets and a few **deliberate read-only** data hand-offs (Project 5 reads Project 1's `data.json`; Project 13 reads Project 6's `window_data.json`; Projects 9/10/14 reuse Project 13's pure modules (`vent_physics`/`vent_io`, P10/P14 also `vent_forecast`/`vent_suggest`) read-only; Project 11 aggregates the published artefacts of 1/5/7/13; Project 16 reads Project 1's `data.json` and is the only *second writer* of the irrigations-Gist), but are otherwise separate. The daily jobs are fired at their local target time by the **Timing Orchestrator** (`.github/workflows/orchestrator.yml`, a self-driven 15-min klok-loop); each project keeps a ~30–60 min later fallback cron + a dedup guard-job. **Projects 1, 5 en 16 draaien uurlijks** (dedup-venster = het lopende klokuur i.p.v. de dag; 1 en 5 sinds aug 2026) zodat hun dashboards met de dag meebewegen; hun *berichten* schalen niet mee — die vallen op één moment per dag, beslist door het script zelf (zie "Meldmoment" bij Project 1).

---

## Project 1: Soil Moisture Monitor

**Goal:** Daily soil moisture monitoring and irrigation recommendations for a garden in Utrecht Oost (sandy soil with clay component).

### Files
- `soil_model.py` — FAO-56 Penman-Monteith ET0 model + data fetching
- `check_and_notify.py` — runner + Telegram notifications
- `.github/workflows/daily-check.yml` — orchestrator-dispatch **elk uur** + fallback cron 06:40 lokaal + guard-job
- `soil_state.json` — meld-bookkeeping (`last_advice_date`), committed by the action, like `sandbox_state.json`
- `docs/index.html` — dashboard (vanilla HTML + Chart.js 4.4 + chartjs-plugin-annotation)
- `data.json` — **generated by the action, never edit manually**; leeft sinds de privatisering (aug 2026) in de **privé artefact-gist** (`ARTEFACT_GIST_ID`, geschreven via de Gist-API i.p.v. gecommit) — het bevat o.a. het volledige irrigatie-logboek, en een meerweeks gat daarin was in de publieke commit-historie een afwezigheidssignaal. Zonder het secret valt de writer terug op het oude lokale pad (bootstrap/tests). Dashboards lezen 'm client-side (localStorage `artefact_gist_id` + token, `artefactReadJSON` in shared.js); anonieme bezoekers zien een koppel-hint

### Meldmoment — de run draait vaker dan hij meldt (aug 2026)
De workflow draaide één keer per ochtend; sindsdien dispatcht de orchestrator hem
**elk uur**. Reden: binnen een dag verandert er wél iets. `partial_factor` schaalt
today's ET0 met de fractie instraling die al gevallen is, `precip` telt alleen de
regen tot nu, de forecast wordt ververst en een zojuist gelogde beurt water landt
meteen in de balans — op een ochtendrun staat today's ET0 dus op ~0 en loopt hij
in de loop van de dag vol. Uurlijks draaien maakt het dashboard daarmee een
live-beeld i.p.v. een momentopname van 06:00.

Het **advies-bericht** schaalt bewust niet mee (dat zou 24 Telegrams zijn). Het
wordt één keer per dag bepaald: op de eerste run op of ná `NOTIFY_AT` (**06:00**),
en daarna niet meer die dag — ook niet als de prioriteit later omslaat. Bewust
"op of ná" en niet "om precies": valt de run van 06:00 uit, dan meldt die van
07:00 alsnog i.p.v. de dag over te slaan. Zelfde semantiek als `PLAN_HOUR` in de
raam-adviseur; de gedeelde poort is `shared_const.past_local_time`, het
dag-geheugen `soil_state.json`. Het slot wordt verbruikt **ook als er niets te
melden viel** — anders perst een rustige ochtend later op de dag alsnog een
bericht eruit zodra de prioriteit kantelt. `FORCE_NOTIFY` (handmatige dispatch)
stuurt altijd en verbruikt het slot juist **niet**: een testbericht mag het
ochtendadvies niet stilleggen. Bijkomend gevolg: de "Ik heb water gegeven"-knop
dispatcht sinds aug 2026 helemaal niets meer (zie de privacy-regel bij de modal) —
de eerstvolgende uurlijkse run verwerkt de invoer.

Twee gevolgen voor de workflow, allebei nodig zodra de cadans uurlijks is:
- **De guard kijkt vanaf 06:00, niet vanaf middernacht.** De fallback-cron bestaat
  om het *advies* te redden als de orchestrator uitvalt. Met een middernacht-venster
  zouden de nachtelijke verversingsruns er altijd al staan en zou de guard de cron
  áltijd skippen — precies in het scenario waarvoor hij bestaat.
- **Checkout gepind op de branch-tip** (`ref: ${{ github.ref_name }}`) — de job leest
  zijn eigen gecommitte stand terug (`docs/data.json` voor de θ-seed, `soil_state.json`
  voor het meldslot) terwijl de window/vent-loops de hele dag door naar main committen.
  Zelfde pin en zelfde reden als `shade-notify.yml` (dubbel bericht uit een oude
  momentopname). De data-commit draagt nu `[skip ci]`: 24 verversingen per dag mogen
  niet 24× de pytest-suite starten.

### Per-run flow
1. Fetch Weather Underground PWS history (30 days)
2. Fetch Open-Meteo (past 30 days + 7-day forecast)
3. Merge: WU wins for precip/temp, Open-Meteo supplies solar radiation (Rs)
4. Fetch `irrigations.json` from GitHub Gist
5. Run FAO-56 ET0 per day
6. Run soil water balance per zone (lawn + shrubs)
7. Write `data.json` → artefact-gist (of lokaal, pre-activatie) — geen Pages-deploy meer
8. Alleen in het advies-slot (06:00, zie hierboven) en bij priority medium/high → send Telegram notification

### Scientific model (do not change without explicit ask)
- ET0: FAO-56 Penman-Monteith using Tmax, Tmin, RHmean, u2, Rs, elevation, lat, doy
- **Dual Kc (FAO-56 ch. 7):** ETc = E + T, met
  - T = Kcb × Ks × temp_factor × ET0 (transpiratie uit wortelzone)
  - E = Ke × ET0 (directe bodemverdamping uit oppervlaktelaag), Ke = min(Kr · (Kc_max − Kcb), few · Kc_max) (Eq. 71), Kr lineair tussen REW en TEW (Eq. 74)
  - Effectieve Kc = (E + T)/ET0
- temp_factor = 0 below 5°C, linear 0→1 between 5–8°C, op 5-daagse rolling Tmean (lucht-Tmean als proxy voor bodemtemperatuur, gedempt)
- **Bodemtemperatuur-overlay (`Tsoil_shallow`/`Tsoil_root`, aug 2026) — additief, stuurt niets aan.** Open-Meteo levert bodemtemperatuur in dezelfde uurlijkse call die de bodemvochtlagen al ophaalde (forecast: 6/18 cm; archive: 0–7/7–28 cm — zelfde splitsing als `OM_SM_LAYERS_*`), dus dit kost geen extra request, dependency of secret. Ze staan er om een nooit-gemeten aanname toetsbaar te maken: `temp_factor` is de énige plek waar bodemtemperatuur het model binnenkomt en draait op een `SOIL_TEMP_WINDOW`-daags loopgemiddelde van de *lucht*-Tmean, gedempt omdat de bodem naijlt. Of die proxy klopt — en of 5 dagen het juiste venster is — kon niemand nagaan zonder een reeks om tegen te leggen. **De proxy blijft ongewijzigd tot die meting er is**; hem aanpassen is een domeinbeslissing die doorwerkt in Project 5 (groei-accumulatie + dormancy-guard), en het effect zit sowieso alleen in de schouderseizoenen (boven 8 °C staat `temp_factor` op 1.0). Vastgelegd door `tests/test_soil_model.py::test_bodemtemperatuur_stuurt_de_waterbalans_niet_aan`.
- Kcb: seasonal via linear interpolation over monthly anchor points (jan→dec)
- Twee buckets: diepe wortelzone (`water`) en oppervlaktelaag (`De`, depletie van 0..TEW)
- Regen/irrigatie vult oppervlaktelaag eerst tot TEW; overschot infiltreert naar wortelzone
- Drainage = excess wortelzone-water boven veldcapaciteit (instantaan, dezelfde dag)
- Ks stress factor: linear decrease when depletion > p × AWC (FAO-56 Eq. 84)
- p (depletion fraction): 0.40 voor gras, 0.50 voor struiken (FAO-56 Tabel 22)
- Interceptie: canopy-saturation curve `I = C · (1 − exp(−P / C))` met C = 1.0 mm (gras) / 1.5 mm (struiken). Smooth: kleine events worden grotendeels onderschept, grote events verzadigen de canopy bij C.
- Oppervlaktelaag-parameters: TEW 18 mm, REW 8 mm, Ze 0.10 m (FAO-56 Tabel 19, sandy-loam → klei-versterkte zand)
- few = min(1 − fc, fw), met fc = 0.95 (gras) / 0.90 (struiken — dichte beplanting + mulch, FAO-56 Eq. 76/ch. 11), fw = 1.0 (regen of sproeier) / 0.30 (druppelirrigatie struiken)
- Kc_max = 1.20 (sub-humide klimaat, u2 ≈ 2 m/s, FAO-56 Eq. 72)
- Soil params: FC 0.20, WP 0.09 v/v — clay-amended sand (ophoogzand) calibration for Utrecht Oost
- Zones: lawn (Zr 0.20m), shrubs (Zr 0.50m — gewogen sierbeplanting + 25% volwassen fruitbomen) — each with own Kcb curve
- Irrigation rates: sprinkler 20mm/hr (lawn), drip 2mm/hr (shrubs)
- Wind: anemometers (Open-Meteo + WU PWS) zijn op 10m; FAO-56 Eq. 47 log-law correctie naar 2m wordt toegepast (u2 = u10 × ~0.748)
- **WU stralingsbiascorrectie (`wu_bias.py`):** het WU-station heeft een radiatieve warm-bias die lineair met de instraling meeschaalt (gediagnosticeerd in Project 7). Op WU-gemeten, niet-forecast dagen wordt `Tmax` gecorrigeerd met `T − SOLAR_BIAS_SLOPE · max(0, instraling_W/m²)` vóór ET0; driver = de eigen WU-pyranometer (`solarRadiationHigh`, dagpiek — valt op Tmax-piek), met de Open-Meteo dagpiek als fallback. `Tmean` wordt gecorrigeerd met de Open-Meteo 24u-mean (laag-risico: enkel de koude `temp_factor`); `Tmin` (nacht) blijft ongemoeid. Rauwe `Tmax/Tmin/Tmean` blijven behouden; correcties zijn additief (`Tmax_corr`, `Tmean_corr`, `bias_corr`, `bias_solar_src`). Forecast/pre-WU/archief-dagen blijven ongecorrigeerd. `SOLAR_BIAS_SLOPE` wordt gekalibreerd door Project 7 (zie daar).
- **State carry-over:** `theta_end` per zone wordt elke run weggeschreven in data.json. De volgende run leest dit als `seed_theta` zodat het 35-daagse warmup-venster niet elke run vanaf 30%-uitputting hoeft te starten — convergeert naar consistente initiële conditie.

### data.json schema (additive only — never break existing fields; privé artefact sinds aug 2026)
```json
{
  "generated_at": "ISO timestamp",
  "source": "string",
  "wu_days": 28,
  "soil": {"FC": 0.20, "WP": 0.09},
  "zones": {"lawn": {"Zr": 0.20}, "shrubs": {"Zr": 0.50}},
  "irrigations": {"2026-04-22": 10.35, "2026-04-22_lawn": 16.7},
  "theta_end": {"as_of": "YYYY-MM-DD", "lawn": 0.14, "shrubs": 0.16},
  "seed_source": "previous_run | default_30pct",
  "days": [{
    "date": "YYYY-MM-DD",
    "forecast": false,
    "hasWU": true,
    "Tmax": null, "Tmin": null, "Tmean": null, "RHmean": null,
    "u2": null, "Rs": null, "precip": null,
    "Rs_peak_wm2": null, "wu_solar_peak": null,
    "Tmax_corr": null, "Tmean_corr": null, "bias_corr": null, "bias_solar_src": "wu | om",
    "Tsoil_shallow": null, "Tsoil_root": null, "Tsoil_src": "om_forecast | om_archive",
    "ET0": null, "ET0_om": null,
    "lawn_theta": null, "lawn_depletion": null, "lawn_ETc": null,
    "lawn_Kc": null, "lawn_Kcb": null, "lawn_Ke": null,
    "lawn_E": null, "lawn_T": null, "lawn_De": null, "lawn_few": null,
    "lawn_irrigation": null, "lawn_drainage": null, "lawn_interception": null,
    "shrubs_theta": null, "shrubs_depletion": null, "shrubs_ETc": null,
    "shrubs_Kc": null, "shrubs_Kcb": null, "shrubs_Ke": null,
    "shrubs_E": null, "shrubs_T": null, "shrubs_De": null, "shrubs_few": null,
    "shrubs_irrigation": null, "shrubs_drainage": null, "shrubs_interception": null
  }]
}
```

### Frontend conventions
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
- Two zone columns side by side (gauge + recommendation + minutes advice)
- "Ik heb water gegeven" modal: input in minutes → convert to mm → write to Gist via GitHub API. **Bewust géén workflow_dispatch meer** (aug 2026, geldt voor álle dashboards): een browser-getriggerde run is publiek zichtbaar in de Actions-lijst (actor + minuut) en dateert elke huiselijke interactie; de uurlijkse run pikt het logboek vanzelf op

---

## Project 2: Personal Weather Briefing

**Goal:** Daily personal weather briefing via Telegram, structured around fixed time blocks relevant to daily routine.

### Files
- `weather_briefing.py` — fetch Open-Meteo + build Telegram message
- `.github/workflows/weather-briefing.yml` — cron at 01:00 UTC

### Logic
- Fetches Open-Meteo hourly forecast for Utrecht
- Parses 24h window: temp, apparent_temp, precip, pop, uv_index
- Builds message per time block. **De blokken zijn een privacy-grens (privacy-sweep aug 2026)**
  en staan daarom NIET in de repo: een weekrooster van vertrek-, opvang-, kantoor-, thuiskomst-
  en sportvensters ís de "wanneer is het huis leeg"-kalender waar de banner bovenaan dit bestand
  over gaat, en het stond hier voorheen letterlijk in de broncode én gepubliceerd op het
  (inmiddels verwijderde) iPad-dashboard.
  - De echte tijden leven in het secret **`BRIEFING_BLOCKS`** (JSON: `weekday`/`weekend`-lijsten
    van `[label, sh, sm, eh, em, dagen|null, icoon]` + `weekend_days`), zelfde status en zelfde
    patroon als `TADO_ZONE_ALIASES`.
  - Secret afwezig of onparseerbaar → `DEFAULT_BLOCKS`: generieke dagdelen (Ochtend 07–10,
    Middag 12–15, Avond 18–21) voor beide sets. De briefing draait dan gewoon door, alleen niet
    op maat — bewust het publieke gedrag, zodat wie de repo leest het ritme niet leert.
  - Voeg hier nooit echte tijden, dagen of labels toe "ter illustratie"; een voorbeeld in een
    comment is net zo publiek als de constante zelf.
- UV windows via linear interpolation between hourly values, rounded to 30 min
- Windows shorter than 15 min are filtered out
- **Geen vakantiemodus meer (aug 2026):** de oude hand-aanpasbare locatie + thuisdetectie
  zijn verwijderd — een locatiewissel betekende een publieke commit met de bestemming en
  een afwijkende kop in het publieke run-log. De locatie ligt vast (Utrecht); tijdelijk
  stil = de stille modus (zie "Stille modus" bij de shared modules). Een test bewaakt dat
  het mechanisme niet terugkeert.
- UV thresholds: UV_MODERATE = 3.0, UV_HIGH = 5.0
- `DRY_RUN=1` env var: print output without sending to Telegram (for local testing)

### UV cloud correction
Open-Meteo's `uv_index` field is only weakly cloud-corrected and reports clear-sky-like values on overcast/rainy days. We therefore fetch `uv_index_clear_sky` and apply the Josefsson & Landelius (2000) cloud modification factor `CMF = 1 - 0.75 * (cloud_fraction)^3.4` using the hourly `cloud_cover` from the same call. The corrected value is what `uv_windows()` thresholds against. If `uv_index_clear_sky` is missing for a given hour, fall back to the raw `uv_index`.

---

## Project 3: Sandbox (Zandbak) Notifications

**Goal:** Daily Telegram notifications about opening, closing, or covering the sandbox, based on weather forecast and current state.

### Files
- `sandbox_notify.py` — weather logic + Telegram
- `sandbox_state.json` — current state (committed by Action after each run)
- `.github/workflows/sandbox-notify.yml` — scheduler + skip logic + manual dispatch

### State machine
Three states in `sandbox_state.json`:
- `open` — sandbox is aired out
- `dicht` — closed against cats, dry expected, will open tomorrow
- `afgedekt` — tarp on, rain expected

State updates automatically after each notification. Manual override via `workflow_dispatch` with `override_status` dropdown.

### Timing
Two crons in `Europe/Amsterdam` time: `08:00` (morning) and `19:00` (evening). GitHub Actions' native `timezone:` field handles DST automatically, so no UTC drift. The workflow itself decides `morning` vs `evening` based on the local hour (`< 12` → morning) — `sandbox_notify.py` does not contain its own skip-window logic.

### Rain threshold
≥30% probability OR ≥1mm expected.

### Relation to other projects
Fully independent — does not touch `soil_model.py`, `check_and_notify.py`, `daily-check.yml`, or `data.json`. Shares Telegram secrets only.

---

## Project 4: Verwarmingsexperiment (Heating Experiment Notifier)

**Goal:** One Telegram message every Monday evening naming the **morning-recovery arm** for the coming week, so a paired-week A/B experiment runs itself. Replaces the daily random night-setpoint suggestion (aug 2026).

### Files
- `heating_experiment_notify.py` — weekly arm picker + experiment log + Telegram
- `heating_experiment_state.json` — the arm log (committed by the action), like `sandbox_state.json`
- `.github/workflows/heating-temp-notify.yml` — orchestrator target maandag 21:00 + fallback cron ma 21:40 + guard-job; `contents: write` (commits the log); **filename deliberately kept** (orchestrator dispatch target, guard's `gh run list --workflow` key, run history)

### Waarom dit experiment, en niet meer het nachtsetpoint
- **Het nachtsetpoint is geen lever.** Whole-house UA naar buiten = 163 W/K: lager dan 16 °C zetten kost €0 (het setpoint bindt nooit), 1 K warmer aanhouden ~€32/seizoen, 2 K ~€63 (150 nachten × 8 u, 92% ketelrendement, €1,45/m³). De enige realistische uitkomst is de bevestiging dat je het niet omhoog moet zetten — eenrichtingsverkeer, dus niet het meten waard. Het setpoint ligt daarom **vast op 16.0 °C** (`NIGHT_SETPOINT`) en wordt in elk bericht herhaald: als het meeschommelt is het een confounder.
- **De ochtend-opstook wél.** Een harde blast om 06:00 duwt aanvoer- én retourtemperatuur omhoog en kan een condenserende ketel uit condensatie trekken; een zachtere, vroegere ramp houdt de retour laag en het rendement hoog. Enkele procenten, onzichtbaar zonder meten, en de fysica geeft het antwoord niet al weg.

### Design (do not casually change — dit is de experimentopzet)
- **Twee armen:** `early` (tado early start/voorverwarmen AAN) en `hard` (early start UIT, comfortblok start hard om `HARD_START` 06:00).
- **Wekelijks alterneren, nooit in blokken.** Twee maandblokken verschillen per *seizoen* i.p.v. per instelling (januari is kouder dan november → de arm die daar valt lijkt slechter om de verkeerde reden). Wekelijks zien beide armen hetzelfde weerbereik.
- **Armkeuze is puur datum-afgeleid:** pariteit van `monday.toordinal() // 7`. Bewust **niet** het ISO-weeknummer — een jaar met 53 weken geeft daar twee gelijke armen op de jaargrens. Gevolg: een gemiste maandag, een dubbele dispatch of de zomerstop kan de alternatie niet uit de pas laten lopen, en de state is puur logboek, geen besturing.
- **Eerste dag na de omschakeling valt af.** Met τ ≈ 23 u settelt het huis ~65% in 24 u, ~92% in 48 u. Omschakeling maandagavond → dinsdagochtend valt af, **woensdag t/m de volgende maandag** zijn de meetdagen (`analysis_window`, in het bericht + het logboek).
- **Meet gas, niet `callForHeat`.** Die vlag is NONE/LOW/MEDIUM/HIGH → 0/25/50/100, een klepstand-proxy, geen energie — die haalt een verschil van ~1,3 kWh/nacht nooit boven de ruis. Normaliseren op graaddagen en gepaarde weken vergelijken. **Die meetkant zit (nog) niet in dit project**: dit script levert alleen het bericht + het armlogboek waar de gasanalyse straks tegenaan gelegd wordt.
- **Stookseizoen-poort:** `SEASON_MONTHS` okt–apr; daarbuiten geen bericht en geen weekregel (er valt niets op te stoken). De alternatie schuift daar niet van, want die is datum-afgeleid. `force`-input (env `FORCE_SEND=1`) negeert de poort voor een testrun.
- `DRY_RUN=1` print zonder te sturen **en zonder de state te schrijven** — een testdispatch mag het experimentlogboek niet vervuilen (anders dan bij de raam-adviseur is er hier geen roterend token dat wél weg moet).

#### heating_experiment_state.json (additief)
```json
{"experiment": "morning_recovery", "last_updated": "ISO",
 "weeks": [{"week": "2026-W45", "arm": "early", "switched_at": "2026-11-02",
            "analyse_from": "2026-11-04", "analyse_through": "2026-11-09"}]}
```
Upsert op `week` (herhaalde dispatch stapelt niet), gesorteerd op `switched_at`, afgekapt op `MAX_WEEKS` 200. `previous_arm()` leest de vorige week hieruit — bij een koude start meldt het bericht "eerste week" i.p.v. een verzonnen bewering over een week die het experiment niet draaide.

### Relation to other projects
Fully independent — no weather data, no other project's artefacts. Shares `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (privé-chat) only.

---

## Project 5: Grasmaai-adviseur (Mowing Advisor)

**Goal:** Tell when the lawn is due for a mow again, and recommend the cutting height (30/40/50mm) based on the weather — biased toward a strong root system.

### Files
- `mowing_advisor.py` — growth model + Telegram + writes `docs/mowing_data.json`
- `.github/workflows/mowing-notify.yml` — orchestrator-dispatch **elk uur** (zodra de bodem-check van dát uur geslaagd is) + fallback cron 07:00 lokaal + guard-job + manual dispatch; checkout gepind op de branch-tip
- `docs/mowing.html` — dashboard (vanilla HTML + Chart.js 4.4 + annotation), separate from the soil dashboard but reuses the same Gist + `localStorage` token (`gist_id`, `gh_token`)
- `mowing_data.json` — **generated by the action, never edit manually**; net als data.json geprivatiseerd naar de artefact-gist (aug 2026) — het maai-logboek is gedateerde handmatige-actie-data
- `mowing_state.json` — tiny notification bookkeeping; **sinds de privacy-sweep (aug 2026) in de privé artefact-gist** i.p.v. gecommit. `last_seen_mow_date` is de datum van een handmatige huishoudelijke actie en een gat in die reeks is een afwezigheidssignaal; een hash i.p.v. de datum lost dat niet op, want het veld *verandert* op de run waarin er gemaaid is, dus de commit dateert de handeling alsnog. Alleen het bestand uit de publieke historie halen sluit dat spoor. Zonder het secret het oude lokale pad (bootstrap/tests)

### Per-run flow
1. Read the mow log from the **same Gist** as the soil project, file `mowings.json` (shape `{"YYYY-MM-DD": {"length_mm": 40}}`, length ∈ {30,40,50}). Browser writes it via the "✂️ Ik heb gemaaid" modal; Python reads it **read-only**.
2. Read `data.json` (het bodem-artefact, uit de artefact-gist) **read-only** for the growth driver.
3. Accumulate grass growth since the last mow, decide ready/optimal day + cutting height.
4. Write `mowing_data.json` → artefact-gist; send Telegram only when there's something to say.

### Growth model (the brain)
- Daily growth unit `GU = lawn_T × heat_derate(Tmax)`, where `lawn_T` (actual transpiration from `data.json`) already encodes season, cold, drought and demand via FAO-56. The heat derate (1.0 ≤24°C → `HEAT_FLOOR` 0.25 ≥35°C) reflects that cool-season turf keeps transpiring in heat but stops elongating. Cold/water stress are **not** re-applied (already inside `lawn_T`). **Zaadpluim-seizoen-uitzondering (`BOLT_SUPPRESS_HEAT_DERATE`):** in `BOLT_MONTHS` (mei–juni) vervalt de hitte-demping (`growth_heat_factor` → 1.0). Koel-seizoensgras (vooral straatgras/Poa annua) schiet ónder hitte-/droogtestress in de aar: de bloeistengels groeien dóór terwijl de bladlengte stilstaat. De demping modelleert enkel die stilgevallen bladlengtegroei en zou de zaadpluim-groei — juist de reden om te maaien — wegdrukken, waardoor het model in een hittegolf veel te laat tot maaien aanzet (gediagnosticeerd juni 2026: een 34–39°C-golf hield de accumulatie op ~⅓ van de drempel terwijl er al aren stonden).
- Accumulate GU since the last mow (mow day resets the accumulator). **Ready** when `accum ≥ READY_GU_effective` and not dormant.
- `READY_GU` default 11.0; **self-calibrates** to the median accumulated-growth-between-logged-mows once ≥4 intervals exist (clamped 8–24). A `LEAD_GU` (2.5) **"bijna maairijp"** heads-up (`soon` kind) fires a day or two before the threshold is crossed — names the next dry maaidag so you can plan a cut before seed heads form.
- **Dormancy guard:** 7-day mean GU < 0.4 → winter, suppress all nudges.
- **Cutting height — priority cascade (1: diepe wortels, 2: zaadpluimen voorkomen, 3: strak gazon), evaluated top-down so a higher priority always wins:**
  - *P1a* — 50mm when heat/drought is coming (≥2 days ≥27°C in next 5, or `lawn_depletion ≥ 55%`): a tall canopy shades/cools the soil and keeps roots deep.
  - *P1b* — **⅓-regel / anti-scalp:** an overgrown lawn (`accum ≥ READY_GU × OVERGROWTH_FACTOR`) is never cut shorter than the previous mow (floor `max(40, last_length_mm)`) — removing >⅓ of the blade stalls root growth.
  - *P2* — 40mm in the **seed-head/bolting season (May–June)**: regular moderate cuts behead the stalks before they ripen.
  - *P3* — 30mm only when cool (<22°C), moist (<35% depletion), in a growth month (Apr–Oct), **and** not bolting/overgrown — beauty only when it costs the roots nothing.
  - default → 40mm (root-friendly middenstand).
- **Fallback:** if `data.json` is missing/stale (>36h), switch to GDD-only mode (own Open-Meteo Tmean fetch, base 6°C) and flag it in the message/dashboard.

### Notification cadence
Tiny `mowing_state.json` (`last_notified_date`, `last_notified_kind`, `last_advice_date`, `last_seen_mow_date`). One message/day max; re-nudge after 3 unmowed days; silent when not ready, dormant, or on a cold start (no real mow logged yet). A newly logged mow resets the notification memory. **Terugkeer-por (aug 2026):** op het eerste advies-slot ná het uitzetten van de stille modus (`notify_prefs.cleared_at` ≤48u oud) vuurt één por los van de RENUDGE-klok als het gazon maairijp is (`return_nudge_due`) — bewust bínnen het gewone slot, zodat de stempel in het publieke state-bestand er als elke andere ochtend uitziet.

**Meldslot (aug 2026).** De workflow draait sinds de uurlijkse cadans elk uur mee met de bodem-check, maar het advies blijft één bericht per dag: het wordt bepaald op de eerste run op of ná `NOTIFY_AT` (**06:15**) — een kwartier ná het bodemadvies (06:00), zodat de twee ochtendberichten in vaste volgorde binnenkomen. Bewaakt door `test_maai_advies_valt_ná_het_bodemadvies`. Binnen dat slot gelden de bestaande cadans-regels ongewijzigd; `last_advice_date` legt alleen vast dát er vandaag beslist is, en wordt — net als het meldgeheugen — gereset door een nieuw gelogde maaibeurt (anders slikt het uurlijkse ritme die bestaande reactie in). Zelfde poort en zelfde motivatie als bij Project 1; zie daar voor het guard-venster (vanaf 06:15) en de checkout-pin.

### Twee vlakke stukken in de groeicurve — geen tekenfout
De accumulatiecurve op `docs/mowing.html` heeft er structureel twee, en `chartNote()` in `docs/js/mowing.js` schrijft eronder wélke je ziet (gevoed door twee additieve serie-velden, `partial` en `depletion`, plus `params.DROUGHT_DEPLETION_PCT` — dezelfde constante die het hoogte-advies al gebruikt, dus geen nieuwe tunable):
- **De knik op "vandaag"** — de dag is nog niet om. `partial_factor` uit `data.json` schaalt today's ET0 naar "verdamping tot nu", dus `lawn_T` (en daarmee de groei-eenheid) telt alleen de groei tot nu; op een ochtendrun is dat ~0,01 tegen ~2 voor een volle dag. Die punt is dus geen volle dag naast zijn buren. **De uurlijkse cadans lost dit grotendeels vanzelf op** — de punt loopt in de loop van de dag vol (gemeten: een run om 01:15 lokaal gaf `partial_factor` 0.913 en een volstrekt normale groeidag).
- **Het plateau aan de rechterkant — dit is de "flat top", en die hóórt er te staan.** De 7-daagse voorspelling rekent per definitie zónder beregening. In een droge zomerweek loopt `lawn_depletion` binnen ~4 dagen naar 90 %+ (de graszone houdt maar ~22 mm beschikbaar water bij ~5 mm/dag ETc), de FAO-56 `Ks`-factor knijpt de transpiratie dicht en de accumulatie valt stil. Dat is een échte modeluitspraak — "zonder water stopt de groei", precies het signaal om te sproeien — en gladstrijken zou de waarschuwing wegpoetsen. Gemeten op drie opeenvolgende dagen (8–10 aug 2026) dezelfde vorm: forecast-`lawn_T` 4.0 → 0.5 met depletie 36 % → 93 %.

### Relation to other projects
Independent except for **one deliberate read-only consumption** of `docs/data.json` (never imports `soil_model`, never writes `data.json`). Draait elk uur, telkens ná de geslaagde bodem-run van dát uur (de orchestrator poort daarop met `soil_success_since "$hour_start"`) — in de praktijk ~15 min erna. No new secrets — reuses Telegram + `GIST_ID`/`GIST_TOKEN`.

---

## Project 6: Tado Window Advisor (raam-koeladvies)

**Goal:** On warm summer days, cool the house by telling — per room — when to open windows (outside cooler than the room) and when to close them (heat-in). Ventilation (roosters) handles continuous air quality; this stays primarily a thermal decision — the one exception is a small, scoped fresh-air tie-break within an active warm-day run (see "Decision logic" below). Advice only — no window is actuated.

### Files
- `window_advisor.py` — hourly brain: tado auth → per-room temps → decide → Telegram + writes `window_data.json` (naar de privé artefact-gist, zie hieronder)
- `tado_auth_bootstrap.py` — **one-time** local device-code authorization, seeds the refresh token into the secret Gist
- `.github/workflows/window-notify.yml` — kwartiercadans via een self-driven loop (cron-kicks elke ~20 min, daarna 20 iteraties op `:00/:15/:30/:45` mark per run, ~5u wall time) + manual dispatch (`dry_run` input), `permissions: contents: write` (alleen nog nodig voor de bootstrap-terugval — met `ARTEFACT_GIST_ID` gaat het artefact naar de privé-gist en valt er niets te committen), checkout gepind op `ref: ${{ github.ref_name }}`
  - **…want een loop-overdracht checkt anders een uren-oude stand uit (aug 2026).** `actions/checkout` pakt standaard `github.sha`: de stand op het moment van *inplannen*. De cron-kicks vuren elke ~20 min maar een loop draait ~5u, dus de concurrency-guard houdt een kick tot uren vast en de overnemende run start op een SHA van vóór al die iteraties (gemeten 5 aug 2026: run gestart 15:45, `head_sha` van 14:15). Twee gevolgen, allebei zichtbaar in productie: (1) `smoothed_solar` vindt in die uitgecheckte `outside_history` geen samples binnen zijn 45-minutenvenster meer en valt terug op de énkele instantane meting — precies de demping die de stralingsbiascorrectie nodig heeft, weg op het moment dat een nieuwe loop begint; twee processen publiceerden zo dezelfde stationsmeting van 28,1 °C als 27,2 en 26,2 °C. (2) De `git pull --rebase` zet het bestand van de nieuwe run bovenop, dus de samples die de vorige loop intussen committe verdwijnen uit de historie (gat 14:00→15:45). Zelfde pin en zelfde reden als `shade-notify.yml`; `vent-notify.yml` en `station-accuracy.yml` dragen 'm nu ook. Bewaakt door de gedeelde `assert_checkout_pinned`-fixture in `conftest.py`.
- `docs/window.html` — dashboard (vanilla HTML + Chart.js 4.4 + annotation), **token+artefact-gist-gated sinds de privacy-sweep (aug 2026)**: zonder koppeling toont de pagina alleen een privé-melding. Cross-linked with the soil + mowing dashboards. `docs/grafiek.html` (de temp×vocht-scatter over dezelfde reeks) draagt dezelfde poort — beide laden nu `shared.js` en dragen de `🔑 Account`-knop
- `window_data.json` — **generated by the action, never edit manually**; leeft sinds de privacy-sweep (aug 2026) in de **privé artefact-gist** (`ARTEFACT_GIST_ID`, dezelfde als `data.json`/`vent_data.json`) i.p.v. onder `docs/`.
  **Waarom:** het artefact draagt per kamer **48 uur temperatuur én luchtvochtigheid op kwartierresolutie** — inclusief de raamloze badkamer, waar de vochtpieken het douche-ritme van het huishouden tekenen en dagen zónder pieken als afwezigheid lezen. Dat is hetzelfde spoor waarvoor `vent_data.json` al privé werd (daar de gemélde raamstanden), alleen dan gemeten i.p.v. gemeld — en het stond op drie ongepoorte pagina's tegelijk (window, grafiek, het inmiddels verwijderde iPad-dashboard). Hiermee is de "bewuste, nog niet opgeloste residu" uit de tweede privatiseringsronde gesloten. Zonder het secret valt `artefact_io` terug op het oude lokale pad (bootstrap/tests)

### Rooms in scope
tado zone names, matched case-insensitively. `ROOMS` = the **advice** rooms (raam open/dicht + Telegram): **Living room, Nursery, bedroom, office**. `SENSOR_ROOMS = ROOMS + ["Shower"]` = every zone we read + publish to `window_data.json`; the windowless bathroom (`Shower`) rides along as a **sensor-only** room (no cooling advice — no window to open — but its temp/humidity/heating are published so the ventilation twin can use them). The gate + decision loop iterate `ROOMS`; ingestion + the dashboard `rooms` iterate `SENSOR_ROOMS`.

### tado heating status (voor de tweeling)
Elke zone-`/state` levert naast temp/RH ook de **verwarmingsstatus** (`parse_heating`: primair `activityDataPoints.heatingPower.percentage`, fallback `setting.power`+setpoint). Per kamer schrijven we `heating` (bool) + `heating_power` (%) in `window_data.json`, en **per history-sample een `heat`-vlag** (additief; afwezig = niet stoken). Dit is puur een read-out die Project 13 (`vent_twin`) gebruikt om gestookte kamers uit de kalibratie te houden — het raakt het koeladvies niet.

### Hourly flow
1. Read the rotating tado refresh token from the **secret Gist** (`tado_token.json`), exchange it for an access token, and **immediately write the rotated refresh token back** (tado rotates on every refresh).
2. tado API: `/me` → home id; `/homes/{id}/zones`; per matching zone `/state` → inside temperature + humidity.
3. Outside temp **now** from WU PWS current obs (`metric.temp`), fallback Open-Meteo current hour. On a WU reading the **stralingsbiascorrectie** (`wu_bias.py`) is applied first — driver = the **median of the WU pyranometer's raw ~5-min readings over the last `SOLAR_AVG_WINDOW_MIN` (45) minutes**, preferably via the `history/all` endpoint (`fetch_wu_recent_solar`), with a **locally-computed median** over the same window from our own persisted 15-min samples as fallback (`smoothed_solar`, reading the additive `outside_history[].solar` field — no extra endpoint dependency, self-heals as history accumulates), then the instantaneous WU `solarRadiation` now-reading, then Open-Meteo `shortwave_radiation` — so `outside_now` (and therefore the microklimaat-bias-blend, `decide()`, and `outside_history.temp`) reflect the corrected temperature. **Why averaged, not instant:** irradiance genuinely swings hundreds of W/m² within seconds under passing/broken cloud, while the radiation shield's warm bias has thermal lag over several minutes — a single instant sample imported that cloud noise 1-for-1 into the correction, showing up as spiky "gecorrigeerde" temp peaks around 12–15u on variably-cloudy days. The Open-Meteo fallback path is left uncorrected (already a model value).
   - **De `history/all`-terugval was een veldnaam, geen entitlement (aug 2026).** Tot dan stond hier genoteerd dat het endpoint "op elke aanroep een non-200 gaf, vermoedelijk een WU-productniveau-gat". Dat was nooit waargenomen: `fetch_wu_recent_solar` las `solarRadiation` — de veldnaam van het *current*-endpoint — terwijl history-records `solarRadiationHigh` dragen (zoals `station_accuracy.py` en `soil_model.py` al deden). `vals` bleef dus leeg en die tak returnde `None` **zonder te printen**, dus de logs toonden alleen de terugval en nooit een oorzaak. Nu leest hij `solarRadiationHigh` (→ `solarRadiationAvg` → `solarRadiation`) en print **elke** onbruikbare uitkomst apart: geen records, records zonder instraling, of niets binnen het venster. **Let op bij het beoordelen van de correctie-grootte:** hiermee wisselt de driver op werkende dagen van "mediaan van 4 instantane kwartiersamples" naar "mediaan van ~9 vijf-minuten-maxima" — een andere statistiek op dezelfde as als de kalibratie (Project 7 fit óók op `solarRadiationHigh`), maar wel systematisch hoger op wisselend bewolkte dagen. Een herijking van `SOLAR_BIAS_SLOPE` hoort ernaast; de gecodeerde 0.00421 (mei-venster) staat al hoger dan de 0.0036 die de laatste volledige run aanbeveelt.
4. Open-Meteo hourly forecast (2 days) → day-max gate + "open again ~HH:00" lookahead. Forecast timestamps are made timezone-aware (Open-Meteo returns naïve local times) so they compare safely with `datetime.now(TZ)`.
5. Per-room decision with hysteresis, update per-room state in the Gist (`window_state.json`).
6. Telegram via the **notification layer** (see "Notification cadence"): a flip is a *candidate*, not automatically a message — per-room daily budget, a duration gate on the prediction, and a separate "what did we actually tell the user" memory decide what goes out. Per-room advice → privé-chat (`TELEGRAM_CHAT_ID`, the `send_telegram` default); the once-a-day **dagplan** → the group (`TELEGRAM_CHAT_GROUP_ID`). The operational alerts (token-persist failure, `run_guarded` crash) stay on the privé-chat.
7. **Always** write `window_data.json` (even on suppressed/cool days) — this is the dashboard artefact. Het gaat naar de privé artefact-gist, dus de workflow committeert niets meer onder `docs/`. Telegram cadence is unchanged.

### Dashboard prediction (`window_data.json` → `docs/window.html`)
The dashboard predicts, per room, *when* the window can be opened today (or "keep closed today") by combining the forecast with the station and the room-temperature trend — all computed in `window_advisor.py`:
- **Station bias correction (smart blend):** `bias = WU_now − Open-Meteo_now` (`station_bias()`) is the local microclimate/calibration offset. It is added to the future forecast and **decays linearly over `BIAS_DECAY_H` (12h)** — near-term hours are anchored to the station. WU unavailable → `bias = 0`.
- **…maar het dooft uit naar de geleerde modelbias, niet naar nul (`om_bias.py`, juli 2026).** De uitdoving liep vóórdien naar **0**, in de veronderstelling dat het ruwe model op termijn zuiver is. Dat is het niet: Open-Meteo leest op onze locatie structureel te warm, 's nachts het sterkst — gemeten over 25 dagen (~15.700 geverifieerde forecast-punten) tegen het eigen station **+1,4 °C 's nachts (22–07u) en +0,8 °C overdag**, bij élke vooruitblik. Gevolg: het hele nachtvenster ligt vanaf een ochtend-/middagrun 12–18u vooruit en draaide dus op de ónvergeleken modelwaarde inclusief de volle warme bias — precies waar het raamadvies op leunt (gediagnosticeerd toen de forecast voor middernacht 27,5 °C gaf terwijl het station de nacht ervóór 20,5 mat en het model 23,3 zei). `correct_forecast` splitst nu twee lagen: de **blijvende** modelbias (geldt op elke vooruitblik) plus de **transiënte** stationsoffset daarbovenop (dooft uit over `BIAS_DECAY_H`, want het anker blijkt maar ~6u informatief — r=0,66 op 0–3u, ~0 voorbij 6u). Leeg leerboek → `clim = 0` → bit-voor-bit het oude gedrag.
- **Eén geijkte reeks voor álle consumenten (`corrected_hourly`).** `day_max_temp`, `upcoming_max_temp` en `next_reopen`/`reopen_is_brief`/`reopen_hour` draaiden op de **ruwe** `om["hourly"]` en vergeleken die met gemeten binnentemperaturen — twee verschillende schalen, met de modelbias er ongefilterd in. `main()` bouwt de geijkte reeks nu één keer en geeft 'm aan alle vijf door, dus de warme-dag-gate, de heropen-hint en de open-tijd-voorspelling zien exact hetzelfde als het dashboard.
- `outside_history[].src` (additief): de bron van elk sample (`wu`/`open-meteo`), zodat `om_bias` alléén tegen echte stationsmetingen verifieert — op een Open-Meteo-terugval ís de "meting" ditzelfde model en zou de gemeten modelfout per definitie ~0 zijn. Oudere samples zonder `src` worden herkend aan `temp == om` (exacte gelijkheid verraadt de terugval).
- **Room-temp trend:** a rolling per-room inside-temp history (and outside-now) is kept in `window_data.json`; each run appends the current sample and trims to `HISTORY_KEEP` (~48). The trend `slope` (°C/h, least-squares over `TREND_WINDOW_H` hours, clamped to ±`TREND_MAX_SLOPE`) is projected forward but **damped** (`min(hours, TREND_CAP_H)` then flat) — a heuristic, **not** a thermal house model.
- **Crossover:** the first future hour (≤ `PREDICT_HORIZON_H`) where `inside_proj > COMFORT_HIGH` **and** `out_corr ≤ inside_proj − OPEN_MARGIN` is the predicted open time; it closes again only on warmte-instroom (`out_corr ≥ inside_proj − CLOSE_MARGIN`) → `open_intervals` — the open-trigger and the stay-open/close-trigger are deliberately asymmetric (`OPEN_MARGIN` vs `CLOSE_MARGIN`), mirroring `decide()`'s own hysteresis, so an open segment doesn't snap shut the instant the projected temp dips back into the dead band. No crossover today → "vandaag dicht houden". **`currently_open`:** the open-trigger only ever encodes the plain "cool" condition — it doesn't know about a dead-band hold, banking, dehumidify or fresh-air open. Without correction, a room already open for one of those other reasons showed a gap on the per-room timeline (`docs/window.html`) until the next *plain-cool* crossover, contradicting the OPEN chip right above it. `predict_open_intervals(..., currently_open=advice=="open")` forces the very first (in-range) grid point open in that case; from there the same asymmetric stay-open/close-trigger applies, so the segment persists until a genuine heat-in rather than closing after a single grid step (a first attempt that only forced the first point without this asymmetry snapped shut almost immediately — the dead-band condition it was meant to fix). Same static-approximation limitation as the dehumidify/fresh-air triggers not being projected forward.
- **Ventilatie-RH (schimmel):** per room the outside RH is converted to the room's temperature via `convert_rh()` (`vent_rh`) — the RH the room would approach if ventilated with outside air, since absolute vapour pressure is conserved when air changes temperature (Magnus/Tetens `_es`, FAO-56 Eq. 11). Computed from the **raw** WU temp + its own RH reading (a consistent sensor pair, *not* the radiation-bias-corrected temp), Open-Meteo `relative_humidity_2m` + `temperature_2m` as fallback. The dashboard shows it behind the indoor humidity as `(X% buiten)`, tinted green when below indoor RH (ventilating dries → less mould risk) and clay when above (ventilating adds moisture, e.g. a warm humid summer day). **`vent_rh` is no longer purely informational — it now also feeds `decide()` (see "Humidity-balanced decision" below).**
- Sparklines clamp to a minimum span (~3.5°C) and draw a faint `COMFORT_HIGH` reference line, so a stable room reads flat instead of magnifying measurement noise.
- `outside_history` also records the raw Open-Meteo value of the same hour (`om`) next to the used `temp`, so the chart can look *backwards* and show **weerstation (gemeten) vs. Open-Meteo (ruw model)** — making station/model divergence (e.g. a station reading too warm on a sunny evening) visible. The `om` field is additive; older samples without it just leave a gap in the model line until history accumulates.
- Dashboard panels: station-vs-model bias readout + warm/cool gate (with its own outside trend arrow + sparkline, mirroring the rooms), per-room cards (inside temp, open/dicht stamp, trend arrow + sparkline, humidity, status line), a temperature chart with three outside series (station-measured + used/calibrated + raw Open-Meteo model, past and future) plus per-room inside projections (`proj`, truncated to `TREND_CAP_H` — see below), `COMFORT_HIGH`/`WARM_DAY_MAX` lines, a "nu" marker, and a day-aligned x-axis (date labels at midnight, hour labels at 06/12/18u); a **separate buitenvocht-grafiek** (`#rh-chart`) with the two RH@20° lines (station-measured + calibrated forecast) and the `RH_COMFORT`/`RH_HARD_CAP` thresholds — **temperature and humidity are deliberately two charts**, sharing one hard-pinned time axis (`timeScale(xMin, xMax)`, computed once over history+forecast) so the same moment sits at the same x in both; they lived in one chart with the RH on a second y-axis until juli 2026, but three outside temp lines + one line per room + two RH lines was no longer readable (and the vocht-lines start later than the temp-lines, so auto-scaling would misalign the two axes); a per-room open-window timeline; and a **temperature × humidity scatter** (`#th-chart`) where each room (and `buiten`, plotted from its measured RH) is one dot at its current `(inside, humidity)` with a single angled trend arrow (`dx` = temp trend, `dy` = humidity trend, projected ~2h) showing where it's heading, plus `RH_COMFORT`/`RH_HARD_CAP` reference lines — the visual of the humidity-balanced decision.
- **`proj` (per-room chart line) stops after `TREND_CAP_H`, it doesn't flat-line to the horizon:** `project_inside()` damps the trend to flat beyond `TREND_CAP_H` (4h) — extending `proj` all the way to `PREDICT_HORIZON_H` (18h, "10:00 tomorrow" from a typical evening run) drew an hours-long horizontal tail that was just the last trended value repeated, not a forecast. `proj` is `None` beyond `TREND_CAP_H` so the dashed room line on the temperature chart simply ends where the near-term trend stops being informative, instead of implying a flat overnight prediction the model doesn't actually have. (`open_intervals`, which drives the timeline/status text, is unaffected — it still searches the full `PREDICT_HORIZON_H` for open/close crossovers, just not via `proj`.) A real overnight per-room forecast would need Project 13's calibrated twin extended well past its current 2h (`end_h`) daily run and read here — out of scope for this fix, tracked as a possible future project-13-feeds-project-6 addition.
- **Humidity trend (scatter `dy`):** the rolling history additively records `hum` (indoor RH per room, measured outside RH in `outside_history`); `room_trend(history, now, key="hum", clamp=RH_TREND_MAX)` reuses the temp least-squares slope to give `hum_trend`/`outside_hum_trend` (%RH/h). Like `om`, older samples lack `hum`, so arrows are temp-only until history fills.
- **`outside_history[].solar`** (additive): the raw WU pyranometer reading (pre-biascorrectie) at each sample, persisted purely so `smoothed_solar()` has a rolling window to average — see the Hourly-flow bullet above. Not otherwise surfaced on the dashboard; older samples lack it, same additive-gap pattern as `om`/`hum`.

#### window_data.json schema (additive only — never break existing fields; privé artefact sinds aug 2026)
```json
{
  "generated_at": "ISO UTC", "as_of_local": "ISO+02:00", "source": "window_advisor",
  "gated": false, "gate_reason": "warme dag | koele dag — advies onderdrukt",
  "outside_now": 26.5, "outside_smoothed": 26.2, "outside_source": "wu | open-meteo", "om_now": 25.0,
  "outside_humidity": 60,
  "outside_trend": -0.05, "outside_hum_trend": 1.2, "bias": 1.5, "day_max": 27.0, "warm_day": true, "warm_ahead": true,
  "om_bias": {"night": 1.5, "day": 0.5, "n_night": 109, "n_day": 181, "updated_at": "ISO+02:00",
              "window_d": 14, "pending": [{"t": "ISO", "fc": 27.5}], "errors": [{"t": "ISO", "e": 1.6}]},
  "params": {"COMFORT_HIGH": 23.5, "OPEN_MARGIN": 1.5, "CLOSE_MARGIN": 0.5, "WARM_DAY_MAX": 22.0, "LOOKAHEAD_H": 12,
             "RH_COMFORT": 60.0, "RH_HARD_CAP": 72.0,
             "ROOM_COMFORT": {"Living room": {"low": 19.5, "high": 22.0}}},
  "outside_history": [{"t": "ISO", "temp": 24.0, "om": 23.2, "hum": 58, "solar": 214.2, "src": "wu"}],
  "forecast": [{"dt": "ISO", "out_raw": 27.0, "out_corr": 28.5, "is_future": true}],
  "rooms": {"Living room": {
    "inside": 26.2, "humidity": 48, "heating": false, "heating_power": 0,
    "vent_rh": 36, "advice": "open | dicht", "trend": -0.05,
    "hum_trend": 0.8, "rh_offset": 0.0, "rh_veto": false, "dryout": false,
    "open_reason": "cool | bank | dryout | fresh_air | null",
    "comfort_low": 19.5, "comfort_high": 22.0,
    "open_now": false, "predicted_open": "20:00",
    "open_intervals": [{"start": "20:00", "end": "08:00", "start_h": 5.0, "end_h": 17.0}],
    "status_text": "Open rond 20:00",
    "history": [{"t": "ISO", "temp": 26.0, "hum": 48, "heat": 1}], "proj": [26.2]
  }}
}
```

### Decision logic (tunable constants at top of script)
- `OPEN_MARGIN 1.5`, `CLOSE_MARGIN 0.5`, `WARM_DAY_MAX 22.0`.
- **Per-room comfort band** `ROOM_COMFORT = {room: (low, high)}` — Living room `19.5–22.0`, Nursery `17.0–18.0`, bedroom `16.0–18.0`, office `20.0–22.0`. `high` is the cool/open trigger, `low` the stop-overcooling/close trigger. `COMFORT_HIGH 23.5` is only the fallback (`low = high = COMFORT_HIGH`) for any room **not** in `ROOM_COMFORT` → reduces to the old single-threshold behaviour.
- **OPEN** when `inside > high + humidity_offset(vent_rh)` and `outside ≤ inside − OPEN_MARGIN` (the muggy/dry humidity shift is described below) — or earlier still, see **"Pre-cooling before a hot day"** below.
- **CLOSE** when `outside ≥ inside − CLOSE_MARGIN` (heat-in), or `inside ≤ low` (cool enough — don't overcool) **unless banking cooling** (see below).
- In-between (`low < inside ≤ high`) → keep current advice (dead-band → no flapping), **unless** a warm day ahead or the fresh-air tie-break actively wants it open (see below) — those can newly *open* a closed room from inside the dead band, not just hold an already-open one.
- **Pre-cooling before a hot day (`open_reason` = `"bank"`):** waiting until a room is already uncomfortably warm (`> high`) to start cooling wastes the cool overnight hours before a heatwave. When `warm_ahead` is true, the *proactive* open-trigger drops from `high` to `low` — a closed room starts banking cooling as soon as it's back at its comfortable minimum and outside is cooler (`inside > low + humidity_offset(vent_rh)` and `outside ≤ inside − OPEN_MARGIN`), instead of waiting for it to overheat first. Once open, the existing dead-band/banking hold (above) keeps it open and lets it drift below `low` overnight, same as before — this only changes when a *closed* room starts opening, not how far it's allowed to cool once open. The forward open-time predictor (`predict_open_intervals`) uses the same lowered threshold on a `warm_ahead` run, so the predicted "open rond HH:MM" text stays consistent with the live decision.
- **Fresh-air tie-break (`open_reason` = `"fresh_air"`):** when nothing thermal is at stake — the room isn't about to overcool (`inside > low`), outside is meaningfully cooler (`outside ≤ inside − OPEN_MARGIN`), and the air is genuinely pleasant (`vent_rh ≤ RH_FRESH_MAX` 55%) — a closed room tie-breaks toward **open** purely because fresh air has some value when it costs nothing. Scoped narrowly: only evaluated within an already non-gated (active warm-day) run (`fresh_air_ok`, gated by `not gated`); a cool/suppressed day stays purely thermal, so the top-level cooling-only gate below is unaffected. Unknown humidity (`vent_rh is None`) is conservative — no tie-break, since mugginess can't be ruled out.
  - **De drempels zijn in augustus 2026 fors aangescherpt** (van `outside ≤ inside` + `vent_rh ≤ RH_COMFORT`). De oude eis overlapte met de sluitconditie van `decide()` (`outside ≥ inside − CLOSE_MARGIN`) in een band van 0,5 °C breed; omdat `open_desire()` eerst getoetst wordt won open, waarna 0,1 °C wiebel in het volgende kwartiersample het weer dichtklapte — een gegarandeerde flapper. Dit was de reden achter vrijwel élk overtollig bericht, terwijl het per definitie de reden is die er thermisch het mínst toe doet. Een tie-break hoort geen hoofdrol te spelen. Bovendien moet de meldlaag de duur-poort én de vocht-vooruitblik (`vent_rh_ahead` over het kandidaat-venster, boven `RH_COMFORT` → geen bericht) halen vóór frisse lucht een Telegram oplevert.
- **`SOFT_OPEN_MARGIN` (1.0 °C):** de minimale buitenmarge voor de níet-thermische open-redenen. Moet altijd **> `CLOSE_MARGIN`** blijven — dát is de invariant die het flapperen structureel uitsluit, en `tests/test_window_advisor.py::test_open_en_sluit_conditie_overlappen_nooit` loopt het hele (binnen, buiten)-vlak af om te bewijzen dat open- en sluitconditie elkaar nergens meer raken (met de oude drempels: 624 overlappende toestanden).
- **Humidity-balanced decision (humid house, dislikes warmth):** ventilating to cool can also drag in muggy air, so `vent_rh` (the projected room RH after ventilating, see "Ventilatie-RH" above) now shifts the open decision. The whole thermal logic is unchanged on normal dry days; only the open trigger and a veto are touched. Constants at the top of `window_advisor.py`:
  - `humidity_offset(vent_rh)` = `RH_TEMP_K · (vent_rh − RH_COMFORT)`, clamped to `[−RH_BONUS_MAX, +RH_PENALTY_MAX]`. **Muggy** (`vent_rh > RH_COMFORT 60%`) **raises** the open threshold (the room must get hotter before a window opens); **dry** outside air gives a small bonus that lowers it. `RH_TEMP_K 0.15` spans nearly the full 0–2°C penalty across the 60→72% band (target→veto); the bonus is deliberately small (`RH_BONUS_MAX 0.5` vs `RH_PENALTY_MAX 2.0`) so ordinary days barely change.
  - **Hard veto (`RH_HARD_CAP 72%`):** if ventilating would push the room past this projected RH, `decide()` returns `dicht` — never ventilate into that-muggy air, and close an open window if outside turns that muggy (e.g. a humid downpour).
  - **Dehumidify trigger (`open_reason` = `"dryout"`):** a muffe-but-not-warm room (indoor `humidity ≥ RH_DRYOUT_MIN 65%`) **opens** when the outside air is clearly drier (`vent_rh ≤ humidity − RH_DRYOUT_MARGIN 8%`), there's no heat-in (`outside ≤ inside − SOFT_OPEN_MARGIN` — was plain `outside ≤ inside`, zie de flapper-toelichting hierboven), and it won't overcool (`inside > low`).
  - `open_reason()` (bool wrapper `open_desire()`) is the single source of truth for `decide()`, the dashboard `open_now`, and the Telegram/dashboard "why" tag — it classifies *why* a room wants open (`"cool"` | `"bank"` | `"dryout"` | `"fresh_air"`) or returns `None`, so advice, dashboard and message text can't drift or mislabel each other. The forward open-time predictor shifts its threshold by the **current** `humidity_offset` (no per-hour RH forecast — a known static approximation) and by the pre-cooling `low`-vs-`high` swap on a `warm_ahead` run; the dehumidify and fresh-air triggers aren't projected forward *inside `decide()`* (same static-approximation limitation). **De meldlaag kijkt sinds augustus 2026 wél vooruit op vocht:** `correct_forecast` draagt de uurlijkse `rh` additief mee en `vent_rh_ahead(fc, inside, now, hours)` geeft de ongunstigste kamer-RH over het kandidaat-open-venster — rekenend met het paar `out_raw` + `rh` en **niet** `out_corr` (`convert_rh` behoudt de dampinhoud, dus temp en RH moeten van hetzelfde consistente paar komen; zelfde argument als waarom `vent_rh` de rauwe WU-temp gebruikt). Wordt de lucht binnen dat venster muffer dan `RH_COMFORT`, dan gaat er geen frisse-lucht-bericht uit. Per-room `rh_offset`/`rh_veto`/`dryout`/`open_reason` are written to `window_data.json` and surfaced as a humidity chip on each card; het Telegram-bericht noemt de reden voluit via `REASON_TEXT` (`buiten is koeler` / `koelte tanken voor de warme dag` / `ontvochtigen — buiten is droger` / `frisse lucht`) en `URGENT_TEXT` voor de urgente sluitingen.
  - **Dashboard status text (`status_text`) matches the `advice` chip, not just a stateless recheck:** `open_now`/`status_text` are derived from `open_reason()` re-evaluated fresh each run, which can legitimately differ from `advice` (a stateful hysteresis machine — dead-band/banking holds the *previous* advice even when a fresh recheck wouldn't newly open). Without accounting for that, a room whose advice is held `"open"` by the dead band could show a contradictory "Vandaag dicht houden" even though the OPEN chip is showing. `status_text` therefore checks `advice == "open"` as a fallback ("Blijft open") before ever falling through to "Vandaag dicht houden", so the chip and the status line never contradict each other.
  - **Status text also can't promise more than the timeline shows (`open_status_tail`):** whenever a room is currently open — via `"cool"`/`"bank"`/`"fresh_air"` or the `advice == "open"` hysteresis fallback above — `currently_open=True` was passed to `predict_open_intervals`, so `intervals[0]` is always the *same* running-open segment the per-room timeline (`docs/window.html`) draws. `open_status_tail(intervals)` builds ` tot ~HH:MM[, weer open rond HH:MM]` from `intervals[0]["end"]` (+ `intervals[1]["start"]` if a reopen is already predicted) and every "currently open" branch appends it
  - **…maar een sluittijd op de forecast-horizon is géén voorspelling (`open_end_is_horizon`, augustus 2026).** `predict_open_intervals` sluit het lopende segment zodra het raster voorbij `PREDICT_HORIZON_H` (18u) loopt, en `_close` legt die rand vast in exact hetzelfde veld als een echte warmte-instroom. Het dashboard presenteerde de rand van het kijkvenster dus als een precieze sluittijd: op 1 augustus 2026 rapporteerden om 13:15 **alle vijf** de kamers `end: "07:15"` — precies nu + 18u. `open_end_text()` (gebruikt door `open_status_tail` én de Telegram-berichten) zegt daarom "de hele nacht door" zodra `end_h ≥ PREDICT_HORIZON_H − 0.01`, en alleen anders een kloktijd (`"Nu open{tail}"` / `"Blijft open{tail}"`, reason-suffixes included). Without this, "Blijft open" promised the window would stay open all day while the timeline right below it already showed a temporary heat-in close and later reopen — the same inconsistency as the chip/status-text bug above, one layer further down.
- **Smoothed decision temp (`SMOOTH_WINDOW_H 0.75`):** before `decide()`/`open_now`, the (already bias-corrected) outside temp is replaced by the **median** over the last `SMOOTH_WINDOW_H` of `outside_history` (incl. the current sample). Quarter-hourly readings can swing >2°C — more than the 1.0°C dead-band — when a short, heavy rain shower briefly drops the outside temp by evaporative cooling and then recovers; the median ignores these lone dips so a passing shower no longer flips the advice (and you don't want a window open during a downpour anyway). The **raw** corrected reading still drives `outside_now`, `bias` and `outside_history.temp` (history is never the smoothed value, so the median can't compound); `outside_smoothed` is the additive readout of the value `decide()` actually saw, and Telegram shows it too so the printed °C justifies the advice.
- **Banking cooling (`warm_ahead`):** if the max temp in the next 24h ≥ `WARM_DAY_MAX`, a room is **not** closed just because it dipped below its `low` — windows stay open through the night to keep banking coolness for the warm day ahead, as long as outside stays cooler. Heat-in still closes. On a cool day ahead the old "cool enough → close" behaviour applies. `warm_ahead` is a forward-looking 24h check (not calendar-day) so it's correct deep at night.
- **Cooling-only gate:** cool forecast day (max `< WARM_DAY_MAX`) and no warm room → no advice.
- **Reopen hint** (`— buiten zakt rond HH weer onder binnen`) on a "Sluit" message only shows when outside is currently *above* the reopen threshold (`outside > inside − OPEN_MARGIN`), i.e. a genuine heat-in close. If outside is already below it, the hint would be meaningless and is suppressed.
- **Brief-heat-in hold (`MIN_CLOSE_H 1.0h`):** an *open* room is **not** closed for a heat-in moment that the forecast says is already over within `MIN_CLOSE_H` — if `next_reopen()` (first forecast hour where `out_raw ≤ inside − OPEN_MARGIN`) lands within the window, `decide()` holds the previous advice instead of flipping to `dicht`. Not worth shutting a window for ~15 min only to reopen. Only applies when the window is currently open (a closed room stays closed) and the muf hard-veto still takes precedence. Threshold is forecast-hour-granular (Open-Meteo is hourly), so it effectively means "the very next forecast step already shows it cool enough → ignore the dip".

### tado auth (the catch)
Since March 2025 tado uses the OAuth2 **device-code flow** (no username/password). Refresh tokens **rotate** (each refresh revokes the previous) and live ≤30 days; hourly runs keep the chain alive. The refresh token lives **only** in the secret Gist + Actions secrets — **never committed** (public repo). Public app `client_id` is hardcoded (not a secret). If the chain breaks, re-run `tado_auth_bootstrap.py`.

### Notification cadence
Per-room state machine like the sandbox project, één controle per 15 minuten. **Een advieswissel is sinds augustus 2026 een *kandidaat*, geen bericht** — daarvóór stuurde elke wissel van elke kamer in elke tick een Telegram, een plafond van ~96 berichten per kamer per dag, en in de praktijk gemeten 7 flips tussen 08:00 en 13:15 (elke keer met binnen en buiten binnen ~0,4 °C van elkaar). Vijf poorten, alle vijf in `window_advisor.py` als pure functies:

- **Cooldown per berichtsoort per kamer** (`notify_decision`/`record_notification`): `OPEN_MSG_COOLDOWN_H` 6u + `CLOSE_MSG_COOLDOWN_H` 6u, gestempeld in `state["msg_at"][kamer][soort]` — bewust **buiten** het dagblok, want dat reset om middernacht.
  - **Dit was tot aug 2026 een kalenderdag-budget (`MAX_*_MSGS_PER_DAY` 1) en dat brak structureel.** De koelcyclus loopt dwars door middernacht — 's avonds open, de volgende ochtend dicht — maar het budget niet. Een open-bericht dat om welke reden dan ook onderdrukt werd, bleef als kandidaat staan (`notify_decision` toetst de stáánde mismatch `advice == "open" and notified != "open"`, niet de flip) en vuurde alsnog op het eerste moment dat een poort het toeliet: de dagwissel. Daar at het het open-budget van de níeuwe dag op, waardoor de open-flip van diezelfde avond wéér onderdrukt werd en het bericht opnieuw naar 00:00 schoof. Eenmaal over middernacht kwam het er nooit meer vanaf. Gemeten 11–12 aug 2026 op Nursery en bedroom: `decide()` zei open om 20:15 resp. 20:30, het Telegram-bericht kwam om 00:00 — bijna vier uur van de beste koelte per nacht, elke nacht opnieuw. Living room en office ontsnapten alleen doordat ze later op de dag sloten (15:45/16:30) en dus vóór middernacht weer openden.
  - Een cooldown telt vanaf het vórige bericht en heeft geen grens die gestolen kan worden. Zelfde mechaniek als `URGENT_COOLDOWN_H`, dat om precies dezelfde reden al een cooldown was. Op het waargenomen record (11–12 aug 2026, alle vier de kamers, replay van de echte artefacten) levert hij **hetzelfde aantal berichten** als het oude budget — ~1 open + 1 dicht per kamer per dag — alleen op het moment dat de flip valt i.p.v. op de dagwissel. `state["day"]` draagt sindsdien alleen nog `plan_sent` + de urgentie-teller.
- **Versheidspoort op de open-kandidaat** (`OPEN_MSG_MAX_AGE_H` 2u, `state["open_since"]` via `track_open_since`/`open_candidate_age_h`): een open-wens die al langer staat is geen nieuws meer maar een late herhaling, en "zet de ramen open" om 00:00 over iets dat sinds 20:15 speelt wekt de ontvanger voor koelte die al grotendeels verdampt is. Zwijgen is dan beter. Staat bewust vóór de cooldown, zodat een verlopen kandidaat de cooldown niet opnieuw start en zo het échte bericht van de volgende avond wegdrukt. Dekt de gevallen die de cooldown zelf niet vangt (bijv. een open die bij de flip nog op de duur-poort strandde). `open_since` wordt gewist zodra de kamer weer dicht wil, zodat de volgende open vers begint.
- **Duur-poort op de vóórspelling** (`sustained_open_h ≥ MIN_OPEN_H` 1.5u): het dashboard toonde letterlijk "Nu open tot ~13:15" om 13:15 — een raam van een kwartier, terwijl het echte koelvenster die dag pas om 18:45 begon. Zo'n blip is geen bericht waard. De poort zit **in de meldlaag, niet in `decide()`**: `decide()` is puur en kent de voorspeller niet, en de voorspeller roept zelf `currently_open=(advice=="open")` aan — daar een duur-eis in leggen maakt het circulair. Het dashboard blijft dus het eerlijke momentane advies tonen; Telegram toont de handelbare deelverzameling.
- **Meldgeheugen los van het advies** (`state["notified"]`, `notified_advice()`): zodra de meldlaag mag onderdrukken, loopt de fysieke advies-state (`state["rooms"]`, het hysterese-geheugen van `decide()`) uiteen met wat de ontvanger te horen kreeg. Zonder aparte boekhouding krijg je de spiegelversie van de flapper-bug: een onderdrukte open, gevolgd door een keurig verstuurd "Sluit" voor een raam dat niemand heeft opengezet. Een open-bericht mag alleen als `notified != "open"`, een dicht-bericht alleen als `notified == "open"`, en `notified` wijzigt **uitsluitend** als er echt iets verstuurd is.
- **Urgente uitzondering** (`urgent_reason`): mag door de cooldown heen, maar smal gedefinieerd en alléén op een kamer waarvan wij gemeld hebben dat hij openstaat — `"muf"` (`vent_rh ≥ RH_HARD_CAP`, schimmelrisico) of `"hitte"` (`outside ≥ inside + URGENT_HEAT_C` 2.0). Met `URGENT_COOLDOWN_H` 3u en `MAX_URGENT_MSGS_PER_DAY` 2 zodat urgentie zelf niet kan gaan flapperen. Het normale dicht-bericht gaat vóór: urgent budget wordt pas aangesproken als de gewone weg nog in cooldown zit. Een urgent bericht stempelt bewust géén `msg_at` — het verbruikt de normale cooldown niet.

**Dagplan (naar de groep).** Eén keer per dag, op de eerste niet-onderdrukte run op of ná `PLAN_HOUR` (8), idempotent via `day.plan_sent`: `build_day_plan` neemt per kamer **alle** open-vensters die de duur-poort halen (tot `MAX_PLAN_WINDOWS` 3 — de vooruitblik loopt 18u, alles opsommen maakt van een overzicht een tabel) en houdt **élke** advies-kamer in het plan, óók die zonder venster; **een lópend venster (`start_h ≤ 0 < end_h`) ontsnapt aan de duur-poort** — die poort weegt of een *voorspeld* venster het openzetten waard is en rekent daarom vanaf nú, maar op een raam dat al openstaat is dat de verkeerde vraag: er valt niets meer te wegen en de sluittijd is juist het enige dat er nog te plannen valt. Toch poorten gaf het omgekeerde van een plan: op 3 augustus 2026 stonden alle vier de kamers open met sluittijden rond 09:15–09:30, maar Living room en Nursery hadden nog géén anderhalf uur te gaan, vielen daardoor uit het plan en werden vervolgens afgedrukt als `⚪ blijft vandaag dicht` — precies het tegendeel van de werkelijkheid én van de OPEN-chip op het dashboard. Op een voorspeld venster blijft de poort onverkort staan; `day_plan_message` maakt daar één regel per kamer van via `plan_window_text`: `staat al open, dicht rond HH:MM` / `open HH:MM–HH:MM` / `open vanaf HH:MM, de hele nacht door` (horizon-segment → geen verzonnen kloktijd, zie `open_end_is_horizon`), meerdere vensters aan elkaar met "; daarna ", en `⚪ blijft vandaag dicht` voor een kamer zonder venster. **Het plan noemt dus expliciet ook de sluittijden** — het eerste-venster-only-plan verzweeg zowel wanneer een raam weer dicht moest als een tweede opening later op de dag, en de kamers zonder venster ontbraken helemaal. Haalt geen enkele kamer een venster → één regel "Vandaag blijven de ramen dicht". Gaat naar `TELEGRAM_CHAT_GROUP_ID`; **ontbreekt dat secret, dan wordt het dagplan overgeslagen** in plaats van stilletjes naar de privé-chat te vallen (`send_telegram` doet `chat_id or os.getenv("TELEGRAM_CHAT_ID")`). Op een gated (koele) dag zwijgt het project, dagplan incluis.

**Berichtteksten** (`room_message_line`/`advice_message`): kop volgt de inhoud ("Ramen open"/"Ramen dicht"/"Raam-advies", `⚠️ Raam dicht — nu` bij urgentie), daaronder per kamer de temperaturen plus wáárom (`REASON_TEXT`) en hoe lang (`open_end_text`).

`DRY_RUN=1` prints instead of sending (token + advies-state are still persisted — rotation must not be skipped) maar **start bewust géén cooldown**: één handmatige testrun mag de echte berichten van die dag niet stilleggen. `fetch_open_meteo` retried via `http_util.get_json` (geen retry → ~17% iteratieverlies bij incidentele 5xx-hiccups gemeten).

#### window_state.json (secret Gist, additief)
```json
{
  "rooms":      {"office": "open"},
  "notified":   {"office": {"state": "open", "at": "ISO+02:00"}},
  "msg_at":     {"office": {"open": "ISO+02:00", "dicht": "ISO+02:00"}},
  "open_since": {"office": "ISO+02:00"},
  "day": {"date": "YYYY-MM-DD", "plan_sent": true,
          "rooms": {"office": {"urgent": 0, "last_urgent": null}}},
  "last_updated": "ISO", "last_notification": "ISO"
}
```

### Relation to other projects
Independent. **Schrijft `window_data.json` elke run naar de privé artefact-gist** (privacy-sweep aug 2026) — daarvóór werd het onder `docs/` gecommit en publiek geserveerd. De tado **refresh token and per-room advice state still live only in the secret Gist** (`tado_token.json`, `window_state.json`) and are **never committed**. Reuses Telegram: raam-advies + operational alerts naar de privé-chat (`TELEGRAM_CHAT_ID`), en **alleen het dagplan** naar de groep (`TELEGRAM_CHAT_GROUP_ID`, hetzelfde secret als de weerbriefing/nachtvoorspelling). Verder `GIST_TOKEN` en de WU-secrets.

---

## Project 7: Weerstation-nauwkeurigheid (Station Accuracy Diagnostic)

**Goal:** Quantify *whether* and *when* the WU PWS reads inaccurately — especially the suspected warm bias on sunny (late-)afternoons — by comparing its hourly temperature against Open-Meteo ERA5 and stratifying the deviation.

### Files
- `station_accuracy.py` — fetch WU hourly history + Open-Meteo ERA5 archive, pair by hour, stratify the bias, write `docs/accuracy_data.json` + print a report (optional Telegram summary)
- `.github/workflows/station-accuracy.yml` — **maandelijkse cron** (1e van de maand 04:10 lokaal, `ACCURACY_DAYS` valt op de cron terug op 40) + manual dispatch met `days`/`notify`, `permissions: contents: write` (commits the dashboard JSON **+ de shards**), checkout gepind op de branch-tip (het archief mag niet vanaf een oudere momentopname gecommit worden). Vóór aug 2026 draaide dit alléén op aanvraag — en dat was precies het probleem: het archief groeide alleen als iemand eraan dácht en de gekalibreerde constante verouderde stilzwijgend (0.00421 stond maanden ná de laatste aanbeveling nog in `wu_bias.py`). De cron-run is **uitzonderingsstil**: hij stuurt alleen een Telegram als het evaluatieprotocol een herijking dráágt (`recalibration_signal`), niet bij elke verschuiving van de fit.
- `docs/accuracy.html` + `docs/js/accuracy.js` — het **ijk-dashboard**: naast de bestaande stratificatie-grafieken drie panelen die de ijkbeslissing zelf tonen — (1) *moet de constante bijgesteld?* (het oordeel van `recalibration_signal`, niet een losse fit), (2) *referenties naast elkaar* (ERA5 vs KNMI, met de **sd** vetgedrukt als beste — dát is de vloer waar de hellingfit tegenaan loopt, niet de bias), en (3) *buurstations* met het nacht/dag/zon-profiel per station en het coherentie-oordeel. De scatter draait op `wu_solar` zodra het artefact die kolom draagt (de as waarop de correctie in productie draait) met de uitgerolde helling als lijn erover; oudere artefacten vallen terug op de grid-instraling. Cross-linked with the other dashboards
- `docs/accuracy_data.json` — **generated by the action, never edit manually**
- `data/station_history/<YYYY-MM>.json` + `tools/station_backfill.py` — de gecommitte maand-shards met de gekoppelde uren; de backfill zaait ze uit de `scatter` van een bestaande `accuracy_data.json` (rerunnable)

### Method
- **Reference = Open-Meteo ERA5** (archive, ~5-day lag). A grid-scale model, *not* ground truth, so a raw `WU − model` gap blends (a) sensor error and (b) real microclimate. They're separated by *behaviour*: a radiative/siting fault scales with solar radiation, worsens at low wind, and (for radiative) vanishes at night; a constant offset is equal day and night.
- Pulls WU **hourly** history (`v2/pws/history/hourly`, per-day calls) — distinct from the soil project's daily endpoint.
- Open-Meteo archive hourly: `temperature_2m`, `shortwave_radiation`, `cloud_cover`, `wind_speed_10m` (timezone=UTC for clean hour alignment).
- Pairs on the common UTC hour, `bias = WU − model`, then aggregates: diurnal curve (per local hour), bias vs cloud bins, bias vs solar bins, bias vs wind bins, the headline "sunny late-afternoon" subset (13–19u local, <25% cloud) vs the rest, and least-squares slopes (°C per 100 W/m², °C per km/h).
- **Calibration output for `wu_bias.py`:** the bias is also fit against **two** radiation drivers — Open-Meteo grid solar *and* the WU station's own pyranometer (`solarRadiationHigh`, co-located → captures direct-sun/broken-cloud bursts the grid smooths away). The report compares their bias↔solar correlations and prints the recommended driver + `SOLAR_BIAS_SLOPE` (= the chosen `slope_per_100 / 100`). The co-located WU driver wins when its correlation is equal-or-tighter. This is the single source of truth for the constant in `wu_bias.py` — re-run to recalibrate and paste the printed value. (`accuracy_data.json` gains additive `wu_solar_slope_per_100`, `solar_bias_corr`, `wu_solar_bias_corr`, `recommended_slope`.)
- **De scatter draagt sinds aug 2026 óók `wu_solar`** (additief). Hij had alleen de Open-Meteo-instraling, terwijl de correctie in productie op de WU-pyranometer draait — elke modelvorm-analyse op dit artefact toetste dus een andere as dan er gebruikt wordt.

### Archief (`data/station_history/<YYYY-MM>.json`)
`accuracy_data.json` is een **momentopname** van het laatst opgehaalde venster en wordt elke run overschreven; alle eerder gekoppelde uren bestonden daardoor nog maar op één plek — de gedownsamplede `scatter` in het gepubliceerde dashboard-JSON. Elke run append't de paren nu aan maand-shards (zelfde maand-shard-patroon als de twin2-historie), **idempotent op het UTC-uur**: een tweede run over een overlappend venster werkt de rij bij i.p.v. te stapelen (ERA5 herziet zijn archief soms). `bias` wordt bewust **niet** opgeslagen maar afgeleid in `load_archive()`, zodat hij na zo'n herziening niet uit de pas kan lopen met zijn eigen operanden. Env-override `STATION_HISTORY_DIR` (tests). Alleen meetdata — `WU_STATION_ID` gaat er nooit in.

**Waarom dit er is:** de helling is één constante die op één seizoen (apr–jun) is gefit en met de hand wordt overgeschreven. Elke serieuze vervolgvraag — schuift de helling met het seizoen, helpt een windterm, houdt een modelvorm stand op een vooruit-geschoven validatievenster — heeft een gróeiende reeks nodig. Zonder archief gooide elke run de vorige steekproef weg. De 1438 uren van 17 apr – 15 jun 2026 zijn met `tools/station_backfill.py` uit de bestaande scatter geseed; die rijen dragen geen `wu_solar`/`rh` (van vóór die export) — een latere run over dezelfde periode vult ze alsnog aan.

### Tweede referentie: KNMI De Bilt (`knmi_ref.py`, fase 1 — **nog niet in productie**)
ERA5 is een reanalyse op gridschaal en draagt zelf ~1,2 °C RMSE; dat is de vloer waar
elke modelvorm-vraag tegenaan loopt (op die ruis scheelt geen enkele kandidaat-term
meer dan ~1%). KNMI-station **De Bilt (260) ligt ruim 4 km** verderop: een officieel
gesiteerde hut, via de klassieke scriptservice `daggegevens.knmi.nl/klimatologie/
uurgegevens` — **geen API-key, geen nieuwe dependency, jaren historie**, dus meteen
toepasbaar op de uren die al in `data/station_history/` staan. ERA5 blijft ernaast
staan: standhouden tegen twee ónafhankelijke referenties is een sterkere
overfit-bewaking dan welk CV-schema ook op één referentie.
**Gemeten en bedraad (aug 2026).** `tools/knmi_probe.py` (workflow `knmi-probe.yml`,
geen secrets, committeert niets) bevestigde de responsvorm records-voor-records en
woog de referentie op 1437 gearchiveerde uren:

| referentie | n | bias | rmse | sd |
|---|---|---|---|---|
| KNMI 260 | 1437 | +0.88 | 1.45 | **1.15** |
| ERA5 | 1437 | +0.88 | 1.67 | 1.42 |

Dezelfde gemiddelde bias — twee ónafhankelijke referenties die het over de
grootte van de stationsfout eens zijn — maar 19% minder spreiding. Zo'n 0,27 °C
van wat als stationsruis werd gefit, was ERA5's eigen gridfout. `attach_knmi`
hangt de kolom sindsdien additief aan elke gekoppelde rij en het archief bewaart
'm; de **stratificatie in het rapport blijft bewust op ERA5** (dat is de reeks
die terugloopt tot april), de KNMI-kolom is er om tegen te scóren via
`tools/bias_backtest.py --reference knmi`. Niet-fataal: hapert de scriptservice,
dan blijft `knmi` None en draait alles ongewijzigd door.

**De buur-coherentietoets liftt sinds aug 2026 mee op dezelfde maandrun** (en op
dezelfde KNMI-uren — geen tweede fetch): het antwoord op "is de warme, windstille
nacht van ons of van de buurt?" bepaalt of de correctie een interceptterm mág
hebben, en dat is een blijvende vraag die elk seizoen opnieuw gesteld hoort te
worden — 's winters kan een hitte-eiland zich anders gedragen. Meeliften geeft die
herhaling gratis; een losse handmatige probe zou het bij één zomermeting laten.
`.github/workflows/neighbour-probe.yml` blijft bestaan als ad-hoc runner.

**Eerste uitkomst (45 dagen, jun–aug 2026) — GEDEELD, en beslissend:**

| station | n | nacht | dag | °C/100W | 0–5 km/h | 5–10 | 10–15 |
|---|---|---|---|---|---|---|---|
| **ons** | 1056 | **+0.77** | +1.31 | **+0.313** | +1.73 | +0.59 | −0.12 |
| buur 1 | 1056 | +0.87 | +1.37 | +0.189 | +1.98 | +0.62 | −0.10 |
| buur 2 | 1054 | +1.64 | +1.04 | +0.082 | +3.20 | +1.25 | +0.32 |
| buur 3 | 1050 | +1.04 | +1.20 | +0.097 | +2.30 | +0.70 | −0.05 |

's Nachts zijn wij de **koelste van de vier** en vertonen alle vier dezelfde vorm
(windstil +1.7…+3.2, boven 10 km/h terug naar ~0) — hitte-eiland t.o.v. De Bilt,
geen sensorfout. Op de zonhelling zijn wij juist de **uitschieter** (~4 sd boven
het buurgemiddelde): de stralingsfout die `wu_bias` corrigeert ís van ons. De twee
vragen vallen dus tegengesteld uit, en dat is de gunstigste uitkomst: de term die
we corrigeren is bevestigd, de term die we niet toevoegden is weerlegd.

Let op de tijdconventie (`HOUR_SHIFT`): KNMI-uur `h` is de momentopname op `h` UT
(24 rolt naar 00 van de volgende dag), terwijl het WU-uur een *emmer* met
`tempAvg` is — een halfuur-scheefheid die er altijd al in zat en met twee
referenties voor het eerst meetbaar is. Sub-uurlijk kan deze bron niet; daarvoor
zijn buur-PWS'en of het KNMI Data Platform (API-key + netCDF/EDR) nodig.

### Evaluatieprotocol (`bias_eval.py` + `tools/bias_backtest.py`, fase 2)
Vóór dit protocol werd elke modelvorm-vraag beantwoord met een fit en een blik op
de RMSE — in-sample, op één seizoen, tegen een referentie die zelf ~1,2 °C ruis
draagt. Zo praat je jezelf een verbetering van 1% aan die de volgende maand
omdraait. Vier poorten, allemaal zuivere functies (geen numpy — dit draait in CI):
1. **nulmodel + de uitgerolde constante als lat**, met `skill` erbij (zelfde
   patroon als `rmse_naive`/`skill` in `vent_learned.json`);
2. **forward-chaining** (train op maand 1..n, toets op n+1) — dát is hoe de
   constante gebruikt wordt; dag-geblokte CV staat ernaast als ondergrens, met
   hele dagen in of uit want opeenvolgende uren lekken;
3. **A/A-ruisvloer**: dezelfde modelvorm, alleen een andere dag→fold-toewijzing.
   Winst kleiner dan die spreiding is geen winst (zelfde rol als de A/A-run in
   `tools/vent_experiment.py`);
4. **parameterbudget** — ~60 onafhankelijke dagen dragen geen vijf vrije params.

`accept()` eist alle drie: beter op forward-chaining, beter in *élke* fold (een
gemiddelde die uit één maand komt is een seizoenstoevalligheid), én winst boven
de ruisvloer. **Eerste uitkomst (apr–jun, ERA5, grid-driver): elke extra term
valt af** — wind, zon-vorig-uur en zon×bewolking verliezen allemaal op
forward-chaining. Alleen het *herijken van de bestaande helling* haalt de poorten.
Dat is precies de volgorde die de assessment voorspelde: de winst zit in de
constante, niet in de vorm.

**Tegen de KNMI-referentie draait die uitkomst om — en dat is een valkuil, geen
vondst (aug 2026).** Met `--reference knmi --driver wu_solar` (2832 uren, 4 folds)
halen `intercept + helling`, `+ wind` en `alles` wél alle drie de poorten, en fors:
forward-chaining 1.044 (uitgerold) → 0.939 met een windterm, ~35× de A/A-vloer.
Toch is er **niets uitgerold**, om één reden: bij *nul* instraling leest het WU-
station nog altijd +0,56 °C warmer dan De Bilt (+1,08 bij windstil, −0,14 boven
15 km/h). Dat kán geen stralingsfout van de kap zijn — er is geen straling. Het is
stedelijk microklimaat over die ruim 4 km (of de schuurmuur die 's nachts nastraalt),
en dat is écht de temperatuur in de tuin, niet iets om weg te corrigeren. Een vrije
intercept- of losse windterm leert precies dát nachtprofiel; uitrollen zou de
gecorrigeerde buitentemperatuur op windstille nachten ~1 °C te koud maken —
precies de conditie waarin de raam-adviseur besluit om koelte te tanken.
De toets die dit hard maakt: `helling x wind (nul 's nachts)` (`solar·(a + b·wind)`,
per constructie nul zonder zon, dus immuun voor het microklimaat-verschil) is de
enige windvariant die **niet** door de poorten komt (verliest in 2/4 folds). Alle
winst zat in de nachtoffset. **Meer seizoenen lossen dit niet op** — het is geen
precisieprobleem maar een identificeerbaarheidsprobleem; daarvoor is een referentie
nodig die óns microklimaat deelt maar een andere kap heeft (buur-PWS'en).
**Die toets is gedraaid en zegt GEDEELD** (zie hieronder): de nachtoffset is de
buurt, niet ons station. **Uitkomst van fase 3: de correctie blijft ongewijzigd** —
een zuivere zon-term met de bestaande constante. Dat is een resultaat, geen uitstel.

**Traagheid van de kap is apart getoetst en afwezig op uurschaal** (aug 2026,
KNMI-referentie + eigen pyranometer, 1712 daguren). Drie sporen, alle drie negatief:
de instraling van het vórige uur draagt 3% van het huidige gewicht (+0.011 vs
+0.351 °C/100 W/m²) en verbetert de RMSE met 0.0001; een EWMA-driver is optimaal
bij τ→0 en verslechtert monotoon (0.949 momentaan → 0.952 bij 30 min → 0.978 bij
1u → 1.193 bij 4u); en de hysterese ochtend-vs-middag bij gelijke instraling
wisselt van teken (−0.44, −0.07, +0.17, 0.00) i.p.v. systematisch positief te zijn.
Conclusie: de tijdconstante ligt **onder de ~15–30 min die uurdata kan oplossen**,
dus de momentane instraling is op die schaal de juiste driver. Fijner meten kan
alleen met 5-minuutsdata aan béíde kanten (het `history/all`-endpoint voor ons,
buur-PWS'en als sub-uurlijke referentie) — mogelijk, maar de uurschaal schat de
winst op ~0.01 °C, dus geparkeerd.

### Buur-PWS-coherentie (`neighbour_pws.py` + `tools/neighbour_probe.py`, route A)
De toets die de bovenstaande knoop doorhakt. Enkele WU-buurstations op honderden
meters délen ons microklimaat maar hebben een andere kap; KNMI levert het
gemeenschappelijke frame (referentietemperatuur, instraling **en** wind — anders
vergelijk je vooral anemometers op verschillende hoogtes) en elk station brengt
alleen zijn eigen temperatuur in. `verdict()` meet onze nachtbias tegen de
**warmste** buur, niet het gemiddelde: met drie buren op verschillende plekken is
de spreiding groot, en één afwijkende buur mag ons niet vrijpleiten.
- **`gedeeld`** → microklimaat. De +1 °C op windstille nachten is écht de
  temperatuur hier; `wu_bias` blijft een zuivere zon-term en fase 3 verandert niets.
- **`uitzondering`** → onze plaatsing. Dan is een interceptterm verdedigbaar en
  wordt de fase-3-beslissing een andere.
- **`onbeslist`** bij te weinig nachtelijke uren — liever geen uitspraak dan een halve.

De buren zijn goedkope sensoren met hun eigen fouten, en dat geeft niet: dit is een
*coherentie*-toets, geen ijking. De vraag is niet wie gelijk heeft maar of het
signaal gedeeld wordt. **De station-id's staan in het secret `WU_NEIGHBOUR_IDS`
(komma-gescheiden) en nooit in de repo** — drie id's verraden de locatie net zo
goed als `WU_STATION_ID`, dat om precies die reden al een secret is. Het rapport
nummert ze als "buur 1/2/3"; een test bewaakt dat er geen id in de broncode staat.

### Relation to other projects
Read-only with **one deliberate output**: it never imports or writes other projects' artefacts, but it is the **calibration source** for `wu_bias.py`'s `SOLAR_BIAS_SLOPE` (a hand-copied constant, no runtime coupling). Reuses the `WU_*` and Telegram secrets only. `WU_STATION_ID` is a secret and is **never** written to `accuracy_data.json` or logs.

---

## Project 8 — vervangen door Project 13 (aug 2026); zie git-historie + AIRFLOW_ASSESSMENT.md

---

## Project 9: Zonwering-adviseur (Shade Advisor)

**Goal:** On warm days, tell per window when to close (and reopen) the operable sun shading — one morning day-plan message plus a single reminder at the first close-moment. Pure sun geometry + Open-Meteo forecast; no thermal simulation, no tado.

### Files
- `shade_advisor.py` — plan/reminder brain (env `SHADE_MODE=plan|reminder`, like the sandbox morning/evening pattern)
- `shade_state.json` — tiny day-state (**alleen** `date`/`plan_sent`/`reminder_at`/`reminder_sent`), committed by the action; the orchestrator reads `reminder_at` from it via `gh api`. De oude `windows[]`-payload is geschrapt (aug 2026): die codeerde welke zonwering die ochtend open gemeld stond — een afgeleide van de privé openingen-log in een publiek bestand. De reminder-fase herrekent het plan zelf uit de live bronnen (en geeft stil op als er geen actionabel raam meer is, bv. al dichtgemeld)
- `.github/workflows/shade-notify.yml` — orchestrator target 08:15 (plan) + fallback cron 08:40 + guard-job; reminder is purely orchestrator-dispatched (no own cron); `contents: write` (commits the state)

### Logic
- Considers **all windows with an operable `shade` layer** in `house_model.json` (runtime-derived, no hardcoded list): per 15-min step over today 06:00–22:00 the **avoidable gain** `ΔW = transmitted(current reported stand) − transmitted(fully closed)` via `vent_physics.per_window_solar`. Coverage-lamella: delta is closed-vs-current-stand, not vs bare glass. Already-reported-dicht windows fall out naturally (ΔW≈0).
- Close interval per window = hysteresis span (`SHADE_CLOSE_WM 150` in, `SHADE_OPEN_WM 80` out; biggest-integral span wins). Day matters = day-max ≥ `SHADE_WARM_DAY_C 22.0` (mirror of `WARM_DAY_MAX` — below it solar gain is free heating) **and** ≥1 window with ≥ `SHADE_MIN_DELTA_WH 500` Wh avoidable.
- **Reminder** (first close-moment): only sent when the predicted load actually materializes now (`SHADE_MATERIALIZE_FRAC 0.6` × threshold on the current Open-Meteo radiation; overcast → hold and retry next dispatch, past the window's open-time → give up silently). One reminder/day max; repeated dispatches are no-ops on the state.
  - **…maar alleen bij een checkout op de branch-tip (`ref: ${{ github.ref_name }}`, aug 2026).** De hele dedup hangt aan de `reminder_sent`-vlag in de *gecommitte* `shade_state.json`, en `actions/checkout` pakt standaard `github.sha` — de stand op het moment van dispatchen. Een tweede dispatch die vlak vóór de commit van de eerste vertrekt, leest daardoor een momentopname van 15 s geleden en stuurt hetzelfde bericht nóg een keer. Zo ontstonden op 2 aug 2026 twee identieke "nu dichtdoen"-berichten om 08:30: bij de overdracht van de ene orchestrator-klok-loop naar de volgende vuurden de láátste tick van de oude (06:30:07Z) en de éérste tick van de nieuwe (06:30:22Z) vlak na elkaar, allebei terecht op `reminder_sent: false`. Dit is de énige orchestrator-dispatch die op een gecommit bestand poort i.p.v. op het run-ledger (`handled_since`, dat een dispatch meteen registreert) — en dat kan hier ook niet anders, want de herhaalde dispatches zíjn de materialisatie-herkansing. De concurrency-groep serialiseert de twee runs al, dus de tip is genoeg: run 2 ziet de commit van run 1 en is weer de no-op die de orchestrator veronderstelt. Vastgelegd in `tests/test_shade_advisor.py` (de state-momentopname-test toont het dubbele bericht, de workflow-test bewaakt de pin).
- Reads the openings log (with the reported `*_shade` stands) read-only from the `GIST_ID` Gist, like Project 13. Telegram to the privé-chat. `DRY_RUN=1` prints (state is still written).

### Relation to other projects
Read-only on Project 13's pure modules (`vent_physics.per_window_solar`/`sun_position`, `vent_io.fetch_weather`/`openings_at`/`load_house`/`load_openings_log`; krijgt zijn ankers via `vent_io.make_context` → `RunContext` — expliciet argument, vergeten = TypeError) + `house_model.json` + the openings-Gist. Never writes any Project 13 artefact. No new secrets.

---

## Project 10: de kinderkamer-nachtvoorspelling (Night Forecast)

**Goal:** Evening Telegram message (orchestrator target 18:45) predicting the nursery's temperature overnight with the calibrated twin, plus door/window scenarios and a tog/slaapzak-advies.

### Files
- `night_forecast.py` — forward sim + scenario's + tog table + message; sinds aug 2026 **niet meer stateless**: elke avondrun legt zijn dicht-scenario-voorspelling vast in `data/night_forecast_log/<YYYY-MM>.json` (één rij per lokale datum, óók op stille avonden, niet onder `DRY_RUN` — een testdispatch mag het datum-slot niet opeten; **zonder** `reported_open` — dat was een gedateerde raamstand-afgeleide in een publiek gecommit bestand, en night_verify scoort toch onvoorwaardelijk tegen de ruwe metingen; de runner heet publiek `kinderkamer-nacht`), zodat `tools/night_verify.py` hem de ochtend erna afrekent tegen de kinderkamer-metingen die al in de twin2-shards staan → `night_verify.json` in de **privé artefact-gist** (wekelijks via twin-eval.yml; sinds de privacy-assessment aug 2026 — per-nacht kinderkamerscores horen niet onder `docs/`, lokale terugval gitignored). Vóór dit spoor was de voorspelling precies één keer gevalideerd (9 nachten) en daarna nooit meer.
- `.github/workflows/night-forecast.yml` — orchestrator target 18:45 + fallback cron 19:15 + guard-job; `contents: write` (commit van het voorspellingslog) + checkout gepind op de branch-tip; in-job retry sleeps 300s (not 600) so a retried message still lands near the 19:00 target

### Logic
- `vent_io.build_timeline(..., end_h=hours-until-tomorrow-08:00)` (~13h at 18:45) with 24h warmup history (mass-node equilibration, the `vent_twin.main()` pattern); `fetch_weather`'s `forecast_days=2` covers the horizon. Params via `vent_io.merged_params(house, load_learned())` — reads `docs/vent_learned.json`; seed from the actual tado temps in `window_data.json` (`collect_actual`), missing rooms → outside temp. Krijgt zijn ankers (buur/grond) én de **ontbiaste om_bias-driver** via `vent_io.make_context` → `RunContext` (expliciet argument aan `build_timeline`/`simulate`; vergeten = TypeError — de oude "must rebind the module global"-valkuil is structureel weg). Die driver blijft belangrijk: het tog-advies hangt aan het nachtgemiddelde van het `dicht`-scenario, dus een systematisch te warme nacht rekende structureel een tog te dun.
- **Three scenario sims** (`scenario_timeline`/`all_open_timeline`): future timeline steps get overridden per scenario (past keeps the reported log; the original timeline is never mutated; `nursery_vent`, the rooster, stays open in all three — it's never toggled). (1) `dicht` — small window + `nursery_stair` door both forced closed. **This is the assumed real state and drives the whole message**: door + small window closed overnight, only the rooster ventilating, is the normal routine, so its stats are the headline forecast and the tog advice. (2) `open` — small window forced open, `nursery_stair` still forced closed. (3) **`all_open`** — small window **and every window/door in the house** (`house_model.json`'s full `windows`+`doors` sets, incl. `nursery_stair`) forced open — the most-ventilated scenario. Windows with no operable pane (`max_open_area_m2` 0, e.g. fixed glass) get the `"open"` state too but contribute no area — the sim is a no-op for them. Scenarios 2 and 3 are computed purely as **informational** comparisons ("raampje ook open zou −1.3° schelen om 07:00", "alles open zou −2.3° schelen om 07:00") — neither is a recommendation to actually open anything, and no comfort-band gating is applied to either. If the openings log currently reports the small window open, the header flags the mismatch ("voorspelling gaat uit van dicht").
- **Massaknoop mee-ijken — sinds aug 2026 via het ankerpad van de tweeling zelf (`vent_forecast.anchor_seed`).** De 24u-warmup is een blinde sim en drijft weg; alleen de lucht herankeren liet de massaknoop (veruit de meeste capaciteit) de drift vasthouden en de geijkte lucht er binnen een paar uur weer doorheen trekken — massa-ijken was met afstand de grootste winst (9 held-out nachten: RMSE 1,46 → 0,86 °C). De *manier* van ijken is daarna A/B-getest op avond-oorsprongen (18/19u, 13u-horizon, 76 dagen shards, `tools/horizon_backtest.py --tm-mode ewma --origin-hours 18,19`): de **delta-shift** (massa schuift mee met het luchtanker, mét sensor-bias-inversie — precies wat de 12u-vooruitblik van het dashboard doet) won van de eigen EWMA-ijking (τ=8u) die hier stond met nursery 0,61 vs 0,70 °C en gepoold 0,80 vs 1,03 — en op de kamers met een `sensor_outdoor_frac` was de EWMA-variant zónder inversie zelfs slechter dan niet herankeren (office 1,49 vs vrijloop 1,29). `anchor_now`/`anchor_mass_now` zijn dus weg; één gedeelde ankerimplementatie (`vfc.latest_actual` met de nachteigen 30-min-versheid + `vfc.anchor_seed`), en het verificatiespoor (`night_verify`) meet de omschakeling live. Kamers zonder verse meting houden hun sim-waarde (fail open). Warmup-`tm_seed` uit metingen is géén alternatief: over 24u drijft het model gewoon opnieuw weg (gemeten 1,34).
- **Gordijnroutine uit gedeelde config**: het `routines`-blok in `house_model.json` (via `vio.apply_routines`, op béíde fasen) verving de eigen `apply_shade_routine`-hardcode — dezelfde config stuurt nu ook de 12u-vooruitblik van de tweeling (zie Project 13).
- **Onzekerheidsmarge in het bericht**: één regel "Typisch X–Y° om 07:00" uit de empirische band (`vio.load_uncertainty`/`vio.band_for`, dichtstbijzijnde trusted uur-cel; excl. weersvoorspelfout en dat zegt de regel er eerlijk bij). Ontbreekt het bestand → geen regel.
- **Tog table** (`TOG_TABLE`, standard toddler sleeping-bag guidance) on the `dicht`-scenario's night-mean: ≥24° 0.5 tog · ≥21° 1.0 · ≥18° 2.5 lange pyjama · ≥16° 2.5 warm · else 3.5.
- **Send gate:** always in `SEASON_MONTHS` (mei–sep); outside only when the predicted night-max ≥ `NIGHT_INTEREST_C 19.0`. Deliberately **no WU refinement** (forecast-driven sim, tado seed → keeps WU secrets out of this workflow). `DRY_RUN=1` prints. Sent to the **group chat** (`TELEGRAM_CHAT_GROUP_ID`), like the weather briefing — not the privé-chat.

### Relation to other projects
Read-only on Project 13 (`vent_physics`/`vent_io` pure modules + `docs/vent_learned.json`) and Project 6's `window_data.json` (seed/now-temp, privé artefact-gist). Openings log read-only from the Gist. Writes nothing. No new secrets — reuses `TELEGRAM_CHAT_GROUP_ID` (weather-briefing's secret) instead of the privé `TELEGRAM_CHAT_ID`.

---

## Project 11: Weekjournaal (Weekly Digest)

**Goal:** One Sunday-evening Telegram digest (orchestrator target zondag 20:00) summarizing the week across the pipelines — pure aggregation of the already-published artefacts, no new data fetching.

### Files
- `weekjournaal.py` — per-section pure functions over the local checkout artefacts (env-path overrides for tests)
- `.github/workflows/weekjournaal.yml` — fallback cron zo 20:40 + guard-job; `contents: read`; no in-job retry (no external API besides Telegram, which has its own retry)

### Sections (each independently optional — missing/stale artefact → section silently omitted)
- 🌱 **Tuinwater** (`docs/data.json`): week-window (today−6..today, non-forecast days) Σ precip / Σ ET0 / Σ per-zone irrigation + current `lawn_status`/`shrubs_status` depletion.
- 🌾 **Maaien** (`docs/mowing_data.json`): mows this week from `mowings`, `accum_today` vs `params.READY_GU_effective`, next-mow prediction / maairijp / winterrust.
- 🧠 **Tweeling** (`docs/vent_learned.json`, env-override `VENT_LEARNED_PATH`): RMSE now vs the last non-`held` point ≥ `RMSE_LOOKBACK_D 6.5` days back (fallback: earliest) + skill + trend arrow.
- 🌤️ **Weer** (`docs/data.json`): Tmax range (bias-corrected where available), week precip, warmest day.
- 📡 **Station** (`docs/accuracy_data.json`): overall bias one-liner, only when the (manual-dispatch) check is younger than `STATION_MAX_AGE_D 30` — stale → omitted rather than misleading.
- All sections `None` → no message. Defensive truncation at `MAX_LEN 4000` (< Telegram's 4096; `send_telegram` doesn't chunk).

### Relation to other projects
Read-only aggregation of the published artefacts of Projects 1, 5, 7, 13 from the local checkout (the `mowing_advisor` `open()`-pattern). Stateless. Telegram secrets only.

---

## Project 12 — met pensioen (aug 2026); zie git-historie + AIRFLOW2_ASSESSMENT.md

---

## Project 13: Ventilatie-tweeling (Digital Twin)

**Goal:** A self-calibrating grey-box *digital twin* of the house — the inverse of Project 6: there the model tells you which windows to open; here **you report which windows / vents / doors are open** and the twin **predicts each room's temperature**, **shows the error** against the real tado temps, and **learns its own parameters online** so it improves the longer it runs. Rebuild of the retired Projects 8 + 12 (aug 2026): twin 1's gevalideerde fysica woordelijk geport, het leer-vangnet-complex bewust weggelaten (zie "Learning regime"). **Telegram: only the operational anomaly nudge ("klopt de raamstand nog?", privé-chat) + the shared `run_guarded` crash alert — no advice messages.** `DRY_RUN=1` prints instead of sending.

### Files
- `vent_physics.py` — pure fysicakern (zon/gevel, druknetwerk + gedempte herkansing, eenzijdige
  ventilatie, 2-knoops RC met tussenwoning-termen, trap-stratificatie) + `RunContext` — de
  frozen dataclass die de oude module-globals (`_LAT/_LON/_NEIGHBOR_TEMP/_GROUND_TEMP`)
  vervangt: expliciet doorgegeven, vergeten = TypeError (de night_forecast-les structureel
  opgelost). Ook het parameter-oppervlak (PRIORS/BOUNDS, `CD` vast).
- `vent_io.py` — loaders (incl. de `PHYSICS_REV`-poort in `merged_params`), openingen-log-
  reconstructie (`ac_room`/`paused`-sleutels), `fetch_weather(lat, lon)` + WU-verfijning
  (`refine_outside_now`), `build_timeline` (om_bias-gecorrigeerde driver; additieve `end_h` —
  P10 rekt hem tot de volgende ochtend), `apply_routines` (de vaste dagritmes uit het
  `routines`-blok in `house_model.json` — zie hieronder), `make_context()`, de maand-shard-I/O
  (append/load/refresh; env `VENT_HISTORY_DIR`), het **forecast-log**
  (`append_forecast_shard`/`load_forecast_log`, `data/forecast_log/<YYYY-MM>.json`, env
  `VENT_FORECAST_LOG_DIR`: elke 3 klokuren één compact kolom-snapshot van wat Open-Meteo
  nú voor de komende 48u voorspelt — de dataset waarmee `tools/horizon_backtest.py
  --weather forecast` het perfecte-forecast-gat gaat sluiten), en de gedeelde
  onzekerheidsband-lezer (`load_uncertainty`/`band_for`, gebruikt door P10 én P14).
- `vent_fit.py` — online kalibratie (`calibrate`), de AC/verwarmings/pauze-filters + de
  structurele kamer-uitsluiting (`filter_excluded_rooms`), en de **deadlock-proof
  anomalie-poort** `anomaly_step` (zie "Learning regime").
- `vent_forecast.py` — de **12-uurs vooruitblik** (`FORECAST_H`): `anchor_seed`/`forecast` (de
  op de tado-meting geherankerde tweede sim, zie "Vooruitblik") + `driver_export` (de
  browser-payload voor de speeltuin). Zuivere functies, geen I/O.
- `vent_twin.py` — runner + dashboard-bouwer (slank schema), anomalie-nudge (privé-chat) +
  "leren hervat"-variant; append't elke run de verse samples/weer-uren aan de shards.
- `.github/workflows/vent-notify.yml` — checkout gepind op de branch-tip (zelfde
  loop-overdracht als de raam-adviseur, zie daar); self-driven quarter-hour loop (cron-kick `9,29,49` —
  a few min after the window run so `window_data.json` is fresh), `permissions: contents: write`,
  concurrency group `airflow-advisor` (**deliberately kept name** — serializes against any
  pre-rename loop run still alive).
- `docs/vent.html` + `docs/js/vent.js` — dashboard: **meldmodal** (writes `house_openings.json`
  in the non-secret `GIST_ID` Gist + `workflow_dispatch`; incl. de airco-dropdown en de
  huis-brede pauze-toggle), plattegrond met stroompijlen, kamerkaarten, temperatuurgrafiek
  (**24u terug + 12u vooruit**, met sinds aug 2026 een **p10/p90-band** om de vooruitblik per
  kamer uit `docs/js/uncertainty.json` — hulpdatasets met een "_"-label, gefilterd uit
  legenda/tooltip; ontbreekt het bestand → kale lijn), leercurve, speeltuin (gedeelde
  `speeltuin.js`, met een eigen **3u terug + 12u vooruit**-scenariografiek).
- `docs/js/vent_core.js` — de **browserkern**: de helft van `vent_physics` die van de raamstand
  afhangt (surrogaat → fresh/mix → deur-/ventilatiegeleiding → stratificatie → 2-knoops
  RC-assemblage → 14×14 stelsel per substap). Plain globals + een CommonJS-export voor de
  golden-test. `docs/js/surrogate.json` = het gedistilleerde luchtstroom-surrogaat (0.39 MB,
  build-artefact van een deterministische solver — commit it).
- `vent_data.json`, `vent_learned.json`, `vent_forecast.json` — **generated by the action,
  never edit manually**; sinds de tweede privatiseringsronde (aug 2026) leven ze in dezelfde
  **privé artefact-gist** als `data.json`/`mowing_data.json` (`ARTEFACT_GIST_ID`) — niet meer
  onder `docs/`. Reden: de gescrubde artefacten (zie "Privacy-scrub" hieronder) toonden nog
  altijd de gerapporteerde raamstanden zelf, en dus de plattegrond met open/dicht-cues, aan
  iedereen. `vio.load_learned()` is ook de read-back die de online kalibratie van run naar
  run laat doorlopen — die leest nu dus óók uit de gist. Zonder het secret het oude lokale
  pad (bootstrap/tests). Het dashboard (`vent.html`) is nu zelf token+artefact-gist-gated:
  zonder koppeling toont de pagina alleen een privé-melding.
- `tools/vent_seed.py` — **parameter-seeding uit de shards**: replay van ~5 dagen historie door
  de productie-onlinefit (ververst eerst het shard-weer uit het archief), acceptatiepoort
  RMSE ≤ 0.9 °C + geen **BOUNDS**-gerailde params (een bewuste huismodel-grens, `@floor(model)`,
  telt niet mee — anders keurt de seeding haar eigen ontwerp af), schrijft
  `docs/vent_learned.json` met `seed_src`-stempel.
  **Ook draaien bij elke toekomstige `PHYSICS_REV`-bump** — een revisie deployt dan met
  her-geseede params i.p.v. live vanaf de priors te leren (de reset-schok-klasse is daarmee weg).
- `tools/horizon_backtest.py` — **de maat waar alles op beoordeeld wordt**: rollende-oorsprong
  h-uurs voorspelfout, geankerd op de meting op de oorsprong, tegen persistentie/gisteren/
  klimatologie + een vrijloop-controle. `--keep-learned` negeert de `PHYSICS_REV`-poort zodat
  een fysica-wijziging geïsoleerd te meten valt (zonder is de meting de parameter-reset).
  Sinds aug 2026 óók: `--weather forecast` (rijd vanaf elke oorsprong op de échte gelogde
  Open-Meteo-forecast i.p.v. hindcast — sluit het perfecte-forecast-gat zodra
  `data/forecast_log` gevuld is; leeg log → nette n=0), `--origin-hours` + `--tm-mode ewma`
  (het anker-A/B-harnas waarmee de nachtvoorspelling is omgezet, zie Project 10),
  `--stratify-openings` (fout per raamstand-klasse op de oorsprong — de plek waar de
  koelplan-adviezen op leunen) en `--summary-out` (kopcijfers appenden aan
  `docs/twin_eval.json`, het wekelijkse trendspoor).
- `tools/export_uncertainty.py` — empirische p10/p50/p90-band per (kamer, horizon-uur) uit een
  backtest-dump + het validatie-envelop voor de OOD-waarschuwing. **Niet per run** — het is een
  eigenschap van het model; wekelijks ververst door twin-eval.yml (stond daarvóór stil op een
  handmatige momentopname). Consumenten: de speeltuin, de band op de dashboard-
  temperatuurgrafiek (vent.js), de marge-regel in het nachtbericht en in het koelplan.
- `.github/workflows/twin-eval.yml` — **wekelijkse evaluatiecron** (zo 05:10 lokaal,
  `contents: write`, checkout branch-tip): ERA5-shardverversing (in-job only — de
  kwartierloops committen dezelfde shards, dus die commit hoort niet hier), backtest
  hindcast + échte forecasts (kopcijfers → `docs/twin_eval.json`), verse
  `docs/js/uncertainty.json`, en de nachtverificatie (`tools/night_verify.py` →
  `night_verify.json` in de privé artefact-gist). Zelfde les als de station-accuracy-maandcron: handmatige
  evaluatie veroudert stilzwijgend.
- `tools/export_driver_timeline.py` + `tools/test_golden.js` — de **golden-vector** (3 poorten,
  zie AIRFLOW3_ASSESSMENT.md §5); `tools/golden/*.json` is het gecommitte contract en poort 1+2
  draaien in CI (`node tools/test_golden.js`).
- `tools/airflow_distill.py` + `train_surrogate.py` + `surrogate_runtime.py` +
  `surrogate_backtest.py` + `test_invariants.py` — het surrogaat-spoor. **Alleen nodig als
  `house_model.json`'s geometrie verandert** (`surrogate_runtime` weigert dan te starten i.p.v.
  stil verschoven kolommen te gebruiken). Vereist `requirements-tools.txt` (numpy, torch) —
  bewust géén runtime-dep; de browser heeft niets nodig.
- `tools/vent_experiment.py` — held-out campagneharnas; `tools/vent_diagnostics.py` — artefact-diagnose.
- `tools/twin2_backfill.py` + de twin2-maand-shards — de evaluatie-/seed-dataset (geërfd van
  Project 12): `vent_twin` vult ze elke run bij, de backfill her-mint ze uit de git-historie
  (rerunnable). **Sinds de privacy-assessment (aug 2026) leven de shards als
  `twin2_history_<YYYY-MM>.json` in de privé GIST_ID-gist** i.p.v. gecommit onder
  `data/twin2_history/` — kamer-temp/-vocht per kwartier is gedragsdata (zie de banner).
  Zelfde mechaniek als het openingen-archief: één schrijver (de kwartierloop), lokale dir als
  gitignorede terugval/overlay (`VENT_HISTORY_DIR` voor tests/tools), zelf-uitvoerende migratie
  (`vio.migrate_history_shards`: unie-merge → read-back-verificatie → lokale bestanden weg, de
  loop-commit publiceert de deletie). `vio.load_dataset` leest Gist ∪ lokale dir (lokaal wint
  per tijdstip — zo levert twin-eval's creds-loze ERA5-stap een in-job weer-overlay zonder
  tweede Gist-schrijver). De reeds gecommitte maanden mei–aug 2026 blijven in de publieke
  git-historie staan (zie de banner: verwijderen kan alleen een history-squash).

### Per-run flow
1. Read `window_data.json` (privé artefact-gist) **read-only** — tado per-room temp/RH (+ history + per-sample `heat`-vlag), the ground truth to learn against. **No tado auth.**
2. Fetch Open-Meteo (past days + forecast); refine the outside-now temp/RH from the WU PWS current obs (`refine_outside_now`: `wu_bias`-stralingscorrectie + WU-zon-herschaling van de glas-drive).
3. Read the openings log (`house_openings.json`) **read-only** from the Gist; reconstruct per-15-min stands (incl. the `ac_room`/`paused` special keys).
4. `make_context()` → `RunContext` (lat/lon, buur-/bodem-anker, om_bias-driver) — expliciet doorgegeven aan timeline/sim/fit.
5. Filter the calibration samples: AC-kamer, gestookte kamers (tado `heat`-vlag), huis-brede pauze — gefilterde kamers worden nog wél gesimuleerd en getoond.
6. `anomaly_step` beslist hold vs. leren; niet held → `calibrate()` (één online stap richting het optimum).
7. `simulate()` over het kalibratievenster; daarna een **eigen** 12u-tijdlijn (`window_h=0`,
   mét de vaste dagritmes uit `house_model.json` `routines` — zie hieronder) +
   `vent_forecast.forecast()` — een **tweede** sim over `[nu, nu+12u]`, geankerd op de laatste
   tado-meting. Bewust een aparte tijdlijn: hem aan de kalibratie-tijdlijn plakken maakt élke
   Gauss-Newton-evaluatie ~14 % duurder, en `calibrate` heeft een tijdsbudget.
8. Write `vent_data.json` + `vent_learned.json` + `vent_forecast.json` (artefact-gist);
   append fresh samples/weather hours to the twin2-shards in de privé Gist **+ het
   forecast-log-snapshot** (`append_forecast_shard`, max één per 3 klokuren).

### Vaste dagritmes op de vooruitblik (`routines`, aug 2026)
`house_model.json` draagt een additief `routines`-blok (element-id → `{state, from_h, to_h}`,
lokale klokuren, over-middernacht toegestaan) voor standen die níemand in de openingen-log
meldt maar die elke dag hetzelfde zijn — nu alleen het verduisteringsgordijn van de kinderkamer
(`nursery_window_shade` dicht 19–08, de fix die P10 al hardcodeerde: ~1 °C te warm om 07:00
zonder). `vio.apply_routines` dwingt ze af op de **forecast-tijdlijnen** (de 12u-vooruitblik
hier + beide fasen van de nachtvoorspelling + het koelplan); de laatst gemelde stand 12 uur
doortrekken was 's nachts elke nacht aantoonbaar fout. De **kalibratie op het verleden blijft
bewust op de gemelde log** rijden: de routine dáár ook toepassen verandert de fit-inputs en is
dus een te méten wijziging (re-seed + backtest, zie de ground rules), geen bijvangst.
Sinds de bewonersbevestiging (aug 2026) staat óók **`nursery_stair` dicht 19–08** in de config:
de deur is 's nachts vrijwel altijd dicht, met als zeldzame uitzondering een te warme kamer
(ruwweg >23°) bij koelere buitenlucht — precies de interventie die de stapel/all-open-
scenario's van P10/P14 doorrekenen (scenario-overrides worden ná de routine gemerged en
winnen dus altijd). Bijbehorende regel: **een expliciete melding ín het lopende
routinevenster wint van de routine** (`apply_routines(..., log=log)`) — routines dekken wat
níemand meldt, maar op de avond dat de bewoner de deur wél openzet en dat meldt, mag de
routine het eigen rapport niet overschrijven (anders spreken dashboard en koelplan-baseline
de gemelde stand tegen). Een melding van vóór het venster telt niet.

### Physics (samenvatting — do not casually retune the structure)
Twin 1's validated physics, ported verbatim into `vent_physics.py`: multi-zone druknetwerk (Newton + gedempte herkansing, laminair/turbulent orifice-regime, één wind-referentiehoogte per gevel), eenzijdige ventilatie (de Gids & Phaff), 2-knoops RC per kamer met de tussenwoning-termen (party-muren met gekapt buur-anker, interne gains, dak-sol-air, interzone-geleiding, bodemkoppeling), trap-stratificatie (gemeten-γ-gradiënt + Brown–Solvason-deur-counterflow), sensor-plaatsing-bias als meet-laag, hoekafhankelijk glas (beam-IAM), en de om_bias-ontbiaste buiten-driver + wu_bias-verfijnde nu-meting. **`PHYSICS_REV` 7** stempelt de learned state (mismatch → params terug naar de priors + anomalie-cooloff; daarna her-seeden via `tools/vent_seed.py`). De volledige meetgeschiedenis achter deze termen staat in `AIRFLOW_ASSESSMENT.md` / `AIRFLOW2_ASSESSMENT.md` / `AIRFLOW3_ASSESSMENT.md`.

**Rev 7 (aug 2026) — twee structurele correcties, beide gevonden door geometrie i.p.v. fitten:**
- **Kruipruimte-anker: `GROUND_AIR_COUPLING` 0.5 → 1.0.** `GROUND_SOIL_ANCHOR` 11 °C met
  koppeling 0.5 zette de kruipruimte in juli op 15,8 °C — een STOOKSEIZOEN-aanname het hele jaar
  door toegepast, goed voor een staande put van ~250 W onder living's 55 m² vloer (overdag
  gemaskeerd door de zon, dominant om 05:00). Het bewijs is de per-kamer-handtekening: de term
  schaalt met `ground_m2`, dus hij verbetert exact de drie grond-gekoppelde kamers en laat de
  twee zonder grondkoppeling met rust. **Winter-voorbehoud:** gevalideerd op zomerdata; koppeling
  1.0 maakt de kruipruimte 's winters juist kóuder dan de oude 11 °C-verankering — richting
  fysisch juist, grootte onbeproefd onder 9,2 °C.
- **Per-kamer parametervloer (`vent_physics.param_bounds`).** `house_model.json` kan een
  `rooms.<id>.param_bounds.<naam>.min/max` dragen die de globale `BOUNDS` VERSMALT (nooit
  oprekt). Nu: `living.c_mass ≥ 0.595`. Dit is bewust een **constraint**-wijziging en geen
  waarde: `c_mass` zit in `PER_ROOM_PARAMS`, dus de online fit herleert 'm elk kwartier tegen de
  **nowcast**-doelfunctie — precies de doelfunctie die 'm omlaag duwde. Een getal in
  `vent_learned.json` is binnen uren weg; de grens hoort náást de geometrie die 'm
  rechtvaardigt (150 m³, 55 m² vloer — living had de LAAGSTE `c_mass` van alle kamers). Een
  GLOBALE vloer is getest en verworpen (bedroom-amplitude 0.883 → 1.468). `railed_params`
  markeert zo'n grens als `@floor(model)` — een `BOUNDS`-rail is een saturatie-klacht, een
  huismodel-rail is de constraint die dóét waarvoor hij er is; `tools/vent_seed.py`'s
  acceptatiepoort gaat alleen op het eerste af. De twee gebruiken een **verschillende
  nabijheidsmaat**: `BOUNDS` op een fractie van de bandbreedte (`RAIL_TOL`, ongewijzigd),
  een huismodel-grens op een fractie van de GRENSWAARDE (`MODEL_RAIL_TOL`). Op de brede
  `c_mass`-band (0.2–10.0) is 2 % bandbreedte ~0.19, waardoor `living.c_mass` op 0.728 — 22 %
  bóven zijn vloer van 0.595, dus volledig vrij — permanent als "op de vloer" werd gemeld.

### Vooruitblik (12u) — `vent_forecast.py`
De kalibratie-sim start 72u terug en staat op "nu" dus op een *gesimuleerde* toestand. Voor een
nowcast maakt dat weinig uit (de fit trekt de baan naar de metingen), maar een 12-uurs
voorspelling erft die restafwijking als een bijna zuivere offset over de hele horizon. Daarom is
de vooruitblik een **tweede** sim over `[nu, nu+12u]`, geankerd op de laatste tado-meting:
- de luchtknoop gaat naar de meting via `vent_physics.air_from_sensor` — de omkering van de
  sensor-plaatsingsbias, want de sim-knoop is de wáre lucht en de voeler leest gebiasd. Zonder
  die inversie pas je de blend twee keer toe (~1 °C op een koude nacht voor bedroom/office);
- **de massaknoop schuift met dezelfde delta mee.** De (Ta − Tm)-differentie codeert of de kamer
  op- of ontlaadt en is het waard om te houden; alleen het niveau is scheef. Alleen de lucht
  herankeren laat de massa tot ~0.6 °C inconsistent staan, waarna `h_am` de lucht binnen twee
  stappen terugtrekt (h=1 RMSE 1.76 → 0.48 offline gemeten);
- het anker komt uit de **óngefilterde** metingen (`gamma_measured`): een gestookte of gekoelde
  kamer hoort uit de FIT te blijven, maar zijn actuele temperatuur is en blijft de beste
  startwaarde die er is;
- `predicted_series` snijdt nu af op `now` (het volle kalibratievenster blijft staan —
  `tools/vent_diagnostics.py` paart 'm met `actual_series`) en de toekomst zit in het additieve
  `forecast_series`; de grafiek klemt zelf op `DASHBOARD_PAST_H` (24u). `trend_c_per_h` komt uit
  de vooruitblik i.p.v. uit de sim-staart.

**Gemeten** (`tools/horizon_backtest.py`, 405 rollende oorsprongen, 12u, perfecte-forecast-aanname):
gepoold **0.70 °C** tegen vrijloop 1.12, persistentie 1.20, gisteren-om-deze-tijd 1.25,
klimatologie 1.83 — en de fout PLATEAUT (h=1 0.34 → h=12 0.85) i.p.v. te divergeren, wat een
12-uurs venster überhaupt verdedigbaar maakt. Alleen `bath` verliest van persistentie (raamloos,
0.62 °C totale spreiding) — bewust buiten scope, zie de ground rules. Het herankeren zelf is de grootste enkele winst: 1.12 → 0.70.
**Elke accuraatheid hier gaat uit van een perfecte weersvoorspelling** (de backtest speelt
hindcast-weer af); die fout is nog ongemeten, maar sinds aug 2026 **wordt de dataset om 'm te
meten verzameld**: het forecast-log (`data/forecast_log`, elke 3 klokuren een snapshot van de
échte Open-Meteo-voorspelling) + `horizon_backtest --weather forecast`, wekelijks gedraaid
door twin-eval.yml. Na ~4–6 weken accumulatie levert dat het eerste live-foutgetal.

### Bewijsstatus eenzijdige ventilatie (§6.2-verplichting — afgerond aug 2026)
De open meetverplichting uit `AIRFLOW2_ASSESSMENT.md` §6.2 is met `tools/vent_experiment.py`
ingelost (3 rotaties × 13 held-out 5d-vensters, replay van de productie-onlinefit, A/A-ruisvloer
0.005 °C): **de term blijft.** Getraind kost verwijdering +0.25 °C op 5d-vrijloop en +0.30 op de
zon-plak (≈50× de ruisvloer; office 1.11→1.63, bedroom 1.36→1.73), en het kern-railen ontspant
níet bij verwijdering — `office.f_air@floor` railt in álle armen, en zonder de term grijpt de fit
gewoon een andere compensatie (`bedroom.solar_gain@floor` i.p.v. `vent_eff@floor`). Nuance die
beide eerdere waarnemingen verzoent: op kale priors overschat de term de koppeling fors (−0.35 °C
bíj verwijdering, ongetraind gemeten), en het geleerde `vent_eff@floor` is precies de fit die dat
op maat snoeit — het samenspel (term × geleerde vent_eff) wint held-out ruim. Het vraagje
"C-constanten ~halveren om `vent_eff` van zijn vloer te halen" is in aug 2026 gesloten
(AIRFLOW3 §7): vent_eff staat inmiddels vrij (~0.29) én de raamstand-stratificatie meet in de
open stand een wárme bias — ventilatie verzwakken is de verkeerde richting. Diezelfde ronde
sloot de constante-infiltratieterm (wiskundig onvindbaar naast `ua_env`) en mat
`living_french` eff 0.5→0.9 als exact nul effect; `office.f_air@floor` in alle armen blijft
het overgebleven er-ontbreekt-nog-iets-signaal (dak-kamer, zon-naar-massa-split), en het
living-open +0.43-signaal is deels de terrasdeur-op-hete-dagen-confound.

### Learning regime
- Online damped Gauss-Newton + ridge naar de priors + Huber + recency (`vent_fit.calibrate`), één stap per kwartierrun.
- **Bewust afwezig:** checkpoint/auto-fallback, `backfill_rmse_history`/log-vingerafdrukken, batch-verankering en tarrering — elk groot incident in Projects 8/12 kwam uit dát vangnet-complex, niet uit de fysica. De seeding-tool + de rev-poort vervangen ze.
- **Anomalie-poort deadlock-proof** (`anomaly_step`): een log↔werkelijkheid-mismatch houdt het leren maximaal `ANOMALY_MAX_HOLD_H` (24u) vast, daarna hervat het leren met een `ANOMALY_REARM_H`-cooloff (de zelfvoedende hold die P12 bevroor kan niet terug); revisie-migratie → cooloff i.p.v. hold. Bij hold-start gaat een nudge naar de privé-chat (herhaald op cooldown), plus een "leren hervat"-variant bij escape; de handmatige huis-brede pauze nudget bewust níet (zelfgekozen).
- Leercurve-punten dragen additief `skill`, `rmse_naive` en `wx` (weer-samenvatting), zodat een RMSE-verschuiving toewijsbaar blijft.
- **Structurele kamer-uitsluiting (`exclude_from_fit`, aug 2026).** Naast de drie *tijdvenster*-filters (AC/verwarming/pauze) kan `house_model.json` een kamer permanent buiten de kalibratie zetten: `rooms.<id>.exclude_from_fit: true` → `vent_fit.filter_excluded_rooms` haalt haar vóór alle andere filters uit `actual`, dus uit de fit, de RMSE, `rmse_naive`/skill, de leercurve én de anomaliepoort. Nu: **`bath`** — douche + handbediende mechanische afzuiging zijn drijvers die de fysica niet kent en die géén melding kan repareren (de heat-vlag-filter ving er maar een deel van; douchen ≠ stoken), terwijl haar samples wél de gedeelde globalen meebepaalden. Ze wordt onverkort meegesimuleerd, getoond op haar kamerkaart en meegenomen in het druknetwerk; alleen haar params bevriezen op de priors/seed. `coupled_sensorless_zones` slaat zo'n kamer over — anders zou ze via de sensorloos-gekoppelde achterdeur alsnog meeleren. `tools/vent_seed.py` past hetzelfde filter toe, anders keurt zijn acceptatiepoort een RMSE over een andere kamerverzameling dan de runner rapporteert. `tools/horizon_backtest.py` doet dat bewust **niet**: die scoort *voorspellen*, en een niet-gefitte kamer blijft een geldige voorspeldoelstelling (het is juist de vergelijking die de bath-grondregel hieronder staaft).
  - **Gemeten bij invoering:** de leercurve stapt hierdoor ~+0,08 °C **omhoog**, niet omlaag — over acht 72u-vensters (1–5 aug 2026, offline replay) was bath met RMSE 0,28–0,71 °C juist de bést-gevolgde kamer van het huis (living/bedroom zaten op 1,4–1,5), en er stond geen enkel `held`-punt in de leercurve. De uitsluiting is dus een keuze over *wat er in het objectief hoort*, niet een reparatie van een slecht getal; punten van vóór en ná de omschakeling zijn niet vergelijkbaar.

### Wat de grafieken tonen (`hide_in_charts`, aug 2026)
`house_model.json` kan een kamer `rooms.<id>.hide_in_charts: true` geven. Dat raakt **alleen
lijnen en tabelrijen**: de kamer blijft volledig meedraaien in de fysica, in de plattegrond,
op haar eigen kamerkaart, in de meldmodal en in de airco-dropdown. Uitgesloten zijn nu:
- **`bath`** (model + tado) — zie `exclude_from_fit` hierboven; een kamer die niet meeleert en
  waarvan de uitschieters uit een douche komen, voegt aan een grafiek over raamstanden niets toe.
- **`stair`** (model) — de koker heeft geen sensor, dus haar lijn is hypothetisch: geen meting
  ernaast om 'm tegen te ijken, terwijl ze wél de drukste lijn van de vijf is.

De vlag wordt op twee plekken uitgelezen: per kamer als `hidden` in `vent_data.json`
(→ `docs/js/vent.js`, de 24u-terug/12u-vooruit-temperatuurgrafiek) en als de lijst
`hidden_rooms` in `vent_forecast.json` (→ `docs/js/speeltuin.js`, zowel de
scenariografiek als de per-kamer-tabel eronder). Beide kanten degraderen netjes: een
artefact van vóór deze velden tekent gewoon alles. Onder de temperatuurgrafiek staat
expliciet wélke kamers ontbreken (`hiddenNote`) en naast de leerfout wie er niet in
meegeteld is (`fitExcludedNote`) — een lijn die zonder uitleg wegblijft leest als een storing.

### Wat er in de shards komt (`exclude_from_shards`, privacy-sweep aug 2026)
De derde generieke kamervlag, naast `exclude_from_fit` en `hide_in_charts` — en dezelfde
grondregel: een uitzondering loopt via een generieke vlag of helemaal niet. `rooms.<id>.
exclude_from_shards: true` houdt de kamer uit de twin2-maand-shards (privé Gist);
`vio.shard_excluded_rooms(house)` vertaalt de huismodel-id naar de gepubliceerde
window_data-naam (dáárop zijn de shards gesleuteld) en `append_history_shard(..., house=)`
slaat 'm over. `tools/twin2_backfill.py` past hetzelfde filter toe — anders zet een re-mint
uit de git-historie het spoor gewoon terug. Geen huismodel meegegeven → niets uitgesloten
(fail open, zodat bestaande aanroepers ongewijzigd blijven werken).

Nu: **`bath`**. Badkamervocht op kwartierresolutie is een douche-spoor — de pieken tekenen
het dagritme van het huishouden en dagen zónder pieken lezen als afwezigheid, blijvend in
publieke git. De kamer draait onverkort mee in de fysica, de plattegrond en haar eigen
kamerkaart; ze leverde toch al geen kalibratiedata (`exclude_from_fit`), dus de evaluatie-/
seed-set verliest niets wat het model gebruikte. De 4041 reeds gecommitte badkamer-samples
zijn bij de sweep uit de vier bestaande shards verwijderd. Bewaakt door
`tests/test_vent_io.py::test_geen_badkamer_in_de_gecommitte_shards`, dat de nog gevolgde
artefacten tegen de vlag in `house_model.json` legt (sinds de shard-privatisering hoort die
lijst leeg te zijn).

### Artefact schema (lean, additive only — never break existing fields)
`vent_data.json`: `generated_at`, `as_of_local`, `source: "vent_twin"`, `model_version`, `weather` (outside temp/RH + `outside_source`, wind/gust/shortwave, sun az/el, `neighbor_temp`, `ground_temp`, `wu_solar_scale`), `openings`/`controls` (**gefilterd op de element-ids uit het huismodel** — boekhoud-sleutels als `paused`/`ac_room` en hernoemde ids bereiken het artefact nooit; zie de privacy-scrub hieronder), `rooms.<id>` (`label`, `predicted_temp` (sensor-ruimte), `predicted_air_temp`, `predicted_mass_temp`, `actual_temp`, `error`, `ach`, `solar_w`, `solar_by_window`, `env_w`, `vent_w`, `trend_c_per_h`, `humidity`, `comfort_low/high`, `heating`, `fit_excluded`/`hidden` (de twee structurele vlaggen uit `house_model.json` — zie "Learning regime" en "Wat de grafieken tonen"), `sensor_outdoor_frac`, `predicted_series[]` (kalibratievenster t/m nu), `forecast_series[]` (12u vooruit, geankerd), `actual_series[]`, `params`, plus de stair-velden op de stratify-zone: `stair_gradient_c_per_m`/`stair_crown_c`/`stair_pin_error_c`/`stair_gamma_w`/`predicted_temp_top`/`predicted_temp_bottom`), `flows[]` (`{id, a, b, flow_m3s}`), `learned` (`params`, `rmse`, `rmse_naive`, `skill`, `railed`, `rmse_history`, `held`), `house_meta` (volledige speeltuin-geometrie). `vent_learned.json`: `updated_at`, `model_version`, `physics_rev`, `params`, `rmse`, `skill`, `railed`, `rmse_history[]` (punten: `t`/`rmse`/`held`/`version` + additief `skill`/`rmse_naive`/`wx`), `anomaly` (`held_since`/`cooloff_until`/`nudged_at`/`escaped_at`), `seed_src` (van `tools/vent_seed.py`, zolang er nog geen leercurve is).

**Privacy-scrub (aug 2026) — afwezigheid mag nergens publiek af te lezen zijn.** De pauze- en airco-boekhouding (`paused`/`paused_since`/`ac`, de per-kamer `paused`/`ac`-chips, `learned.paused` en het `paused`-veld per leercurve-punt) staat bewust NIET meer in de publieke artefacten: de huis-pauze is in de praktijk een "niemand meldt betrouwbaar"-schakelaar en een reeks pauze-punten is een machine-leesbare afwezigheidskalender. De modal leest die stand live uit de Gist (token-houders). Gepubliceerde `held` betekent uitsluitend de **anomalie**-hold (zelf-oplossend binnen 24u); pauze- én stille-modus-holds schrijven een gewoon leercurve-punt en exact dezelfde stdout-regels als een leer-run. De stdout van de kwartierrun noemt nooit een airco-kamer, pauzestand of gestookte-kamer-lijst. De **openingen-snapshots** gaan niet meer de gecommitte maand-shards in (elke rij was een minuut-gestempelde menselijke handeling in publieke git-historie — de shards van vóór aug 2026 dragen ze nog, dat is blijvend): het duurzame archief tegen de browser-trim leeft nu maand-geshard in de privé Gist (`house_openings_<YYYY-MM>.json`, action-geschreven — één schrijver per bestand blijft gelden), met een zelf-uitvoerende migratie (seed uit de shards → read-back-verificatie → strippen) in de kwartierrun. `vio.load_dataset` merge't legacy-shard-rijen ∪ archief ∪ live log; offline tools zetten `VENT_OPENINGS_ARCHIVE_DIR` of de Gist-env (twin-eval.yml en ml-dataset.yml dragen die read-only; de ML-export verloor bovendien zijn `paused`-kolom — een run-artefact op een publieke repo is voor elke ingelogde GitHub-gebruiker downloadbaar, dus alleen bewust dispatchen).

**Tweede ronde (aug 2026) — de scrub was niet genoeg.** De gescrubde artefacten toonden nog
altijd wát er open of dicht stond (`openings`/`controls`, de forecast-`steps[].states`) en dus
de plattegrond met open/dicht-cues — dat is precies het signaal waar de scrub niét op poortte
(alleen de afwezigheids-*markers* waren weg, niet de raamstanden zelf). `vent_data.json`,
`vent_forecast.json` en `vent_learned.json` gaan daarom nu zelf naar de privé artefact-gist
(`ARTEFACT_GIST_ID`, dezelfde als `data.json`/`mowing_data.json` — zie de shared-modules-sectie),
en `vent.html` is zelf token+artefact-gist-gated: zonder koppeling toont de pagina alleen een
privé-melding, geen raamstanden, temperaturen of plattegrond. `vio.load_learned()` leest via
hetzelfde pad, dus de online kalibratie blijft ongestoord doorlopen.

**Derde ronde — de privacy-sweep (aug 2026) sloot de aangekondigde residu.** De tweede ronde
noteerde `window.html` (Project 6) nog als bewust openstaand: per kamer een open/dicht-*advies*
plus live temperaturen op dezelfde 15-min-cadans, "zwakker signaal, dezelfde vorm". Bij het
natrekken bleek het sterker dan genoteerd — het artefact eronder droeg per kamer **48 uur
temperatuur én luchtvochtigheid**, inclusief de badkamer (douche-pieken = het dagritme van het
huishouden, dagen zonder pieken = afwezigheid), en het werd door **drie** ongepoorte pagina's
gelezen. `window_data.json` is daarom óók naar de artefact-gist verhuisd en `window.html` +
`grafiek.html` dragen nu dezelfde poort als `vent.html`; het iPad-dashboard is in zijn geheel
verwijderd (het publiceerde bovendien het weekritme van het huishouden als tabel). Zie
Project 6 voor de details en Project 13's `exclude_from_shards` voor de shard-kant.
`vent_forecast.json` (browser-payload, apart bestand omdat vent_data.json bewust een slank
dashboard-schema is): `zones`, `sensor_rooms`, `hidden_rooms` (weergavefilter — bewust
**naast** `sensor_rooms` en niet erin gesnoeid: die lijst is het kolomcontract van
`vent_core.js` + de golden-vector), `room_labels`, `volumes`, `elements[]` (id, kind,
per-stand-fractie, default — de **volgorde is het kolomcontract van het surrogaat**), `doors[]`,
`strat`, `consts`, `ss_windows[]`, `sensor_outdoor_frac`, `par` (thermische params per zone),
`ginter[]`, `ground_temp`, `neighbor_temp`, `vent_eff`, `cp_shelter`, `rho_cp`, `substep_s`,
`t0`, `seed_Ta`/`seed_Tm` (de geankerde toestand op nu), `steps[]` (weer-only drivers per
15 min: `T_out`, `irr`, `t_solair`, `nb_now`, `int_profile`, wind, gemelde `states`),
`past[]` (3u aanloop, alleen `T_out`) en `actual` (gemeten kamertemps over diezelfde aanloop).

### Relation to other projects
Leest `window_data.json` (Project 6, privé artefact-gist) + de openingen-Gist **read-only**; schrijft uitsluitend
eigen artefacten + de twin2-shards (privé Gist sinds de privacy-assessment aug 2026). **P9/P10/P14 importeren `vent_physics`/`vent_io` read-only** met een
ctx-prologue van 3 regels (`vent_io.make_context` → `RunContext`); P11 leest `docs/vent_learned.json`.
Geen tado-auth, geen nieuwe secrets (WU-, privé-chat-Telegram- en Gist-secrets hergebruikt).
`house_model.json`: de twin-2-only velden `subzones` en per-element `exposure` zijn inert;
`front_azimuth_deg` is verwijderd (aug 2026 — dead sinds het pensioen van Project 12, geen enkele consument meer).

---

## Project 14: Koelplan (Cool-down Advisor)

**Goal:** Eén avondbericht (orchestrator-doel 21:15, ná de kinderkamer-nachtvoorspelling) dat de vraag
beantwoordt waar de tweeling voor bestaat: **welke ramen en deuren moeten vanavond open om het
huis echt te koelen** — het adviesluik dat bij de herbouw van P8/P12 bewust wérd weggelaten,
nu als apart project bovenop de gekalibreerde tweeling (P13 zelf blijft advies-stil).

### Files
- `vent_suggest.py` — de zuivere kern: **gecureerde scenario-grammatica** (~15 sims, afgeleid
  uit de geometrie — per raam een solo, per slaapkamer een "stapel" (raam + eigen trapdeur +
  daklicht: de lage-inlaat/hoge-uitlaat-route waar de koker met deuren op 1.0/3.9/7.0 m
  letterlijk voor bestaat), living-dwarsventilatie, een huis-stapel, en "alles open" als
  **plafond dat nooit advies is**; bewust géén 2^n-zoektocht: een vaste grammatica is
  uitlegbaar, contract-testbaar en kan geen fysiek onzinnige combinaties voorstellen),
  de praktische filterlaag (`practical_filter`: regen ≥ 0.2 mm/u, windstoten ≥ 14 m/s en de
  additieve `advice`-vlaggen in `house_model.json` — `night_ok` (bg-buitendeuren nooit vol
  open 's nachts), `rain_ok`, `tilt_ok` (het platte daklicht kiept niet weg bij regen maar
  vervalt), kiepbare ramen vallen terug op "tilt", na het snoeien identieke scenario's worden
  gededupliceerd), de score (`score_plan`: per advieskamer het 07:00-verschil t.o.v. de
  dicht-baseline, alléén voor kamers boven hun comfortband en **geklemd op comfort_low** —
  koelen onder de band is niets waard; onderkoelings-graaduren als straf; een kleine
  actiekost zodat het kleinste effectieve plan wint), de zendpoort (`should_send`: mei–sep +
  minstens één te warme kamer + beste plan ≥ `DELTA_MIN_C` 0.7 — kleiner kan het model niet
  onderscheiden, dus dat is geen bericht waard) en de berichttekst (kop-delta op 0,5 °C
  afgerond; een te warme kamer waar het plan níets aan doet zegt dat expliciet).
- `cooldown_notify.py` — runner: het twee-fasen-patroon van night_forecast (24u aanloop op de
  échte log + routines, herankeren via `vent_forecast.anchor_seed`), dan élk scenario
  **bóvenop de dicht-baseline** (alle beweegbare ramen dicht + `nursery_stair` dicht — de
  avondroutine-aanname; "solo raampje" betekent alléén dat raampje open) gesimuleerd over
  [nu, morgen 08:00] in sensorruimte, gescoord, gerangschikt, met een marge-regel uit de
  gedeelde band (`vio.band_for`) op de kamer met het grootste voordeel. Naar de
  **groepschat**; `DRY_RUN=1` print. Stil buiten het seizoen, zonder te warme kamer of onder
  de ondergrens.
- `.github/workflows/cooldown-notify.yml` — orchestrator target 21:15 + fallback cron 21:45 +
  guard-job; `contents: read` (stateless — leest checkout + Gist, commit niets).

### Eerlijkheidsgrenzen (bewust in het ontwerp)
De deltas zijn model-afgeleid en alleen op wérkelijk bezochte raamstanden gevalideerd
(`uncertainty.json` zegt dat zelf: `measured_on_observed_states_only`); een gesloten huis
wisselt in het model exact nul lucht (infiltratie zit in de geleerde `ua_env`), dus
open-vs-dicht-verschillen zijn een **optimistische bovengrens** — vandaar de zendpoort, de
0,5°-afronding en het plafond-frame. De counterfactual van dezelfde nacht is fundamenteel
onverifieerbaar; wat wél kan: `horizon_backtest --stratify-openings` begrenst de fout per
raamstand-klasse, en gevolgd advies wordt via de openingen-log vanzelf een geobserveerde
stand in de shards.

### Relation to other projects
Read-only op P13's zuivere modules (`vent_physics`/`vent_io`/`vent_forecast`) met de
ctx-prologue, en op `window_advisor.ROOM_COMFORT` (dezelfde comfortbanden als P6/P13's
kamerkaarten — één waarheid voor "te warm"). Schrijft niets. Geen nieuwe secrets
(`TELEGRAM_CHAT_GROUP_ID` + Gist-secrets hergebruikt). Botsingsvlak met Project 6 (dat
's avonds óók open/dicht-advies stuurt, maar per kamer op de gemeten temperatuur): bewust
één bericht per avond op een vast tijdstip; een echte verzoening (P6 dat 's avonds naar het
koelplan verwijst) is benoemd maar uitgesteld.

---

## Project 15: Kampeerkompas (Camping Forecast)

**Goal:** Doorlopend (jaarrond, 4×/dag) overzicht van waar en wanneer dertien streken — Utrecht plus twaalf met naam genoemde Oost-Franse steden/dorpen, noord→zuid: Vitry-le-François, Colmar, Mulhouse, Montbéliard, Dijon, Besançon, Chamonix, Annecy, Chambéry, Grenoble, Valbonnais, Valence (Oostenrijk en Noordwest-Frankrijk vervielen aug 2026, zie "Flexibele super-regio's") — geschikt zijn om te kamperen met tent, peuter en auto: dagen < 30°, nachten > 10° én ruim boven het dauwpunt (droge tent), dagregen zwaarder gewogen dan nachtregen, officiële waarschuwingen van **oranje of hoger** als rode vlag — **geel wordt bewust volledig genegeerd** (bewonersbesluit aug 2026: een gele hittegolfwaarschuwing kleurde vrijwel de hele matrix rood) — en vertrekken na een droge nacht + ochtend. **Dashboard-only:** geen Telegram-advies, alleen de gedeelde `run_guarded`-crash-alert.

### Files
- `camping_forecast.py` — runner: per regio Open-Meteo-forecast (16d) + ECMWF-ensemble, MeteoAlarm-waarschuwingen per land, score → vensters → `docs/camping_data.json`
- `meteoalarm.py` — MeteoAlarm CAP-in-ATOM-feedclient + zuivere parser (stdlib `xml.etree`; de enige XML-bron in de repo — bewust niet in `http_util`, dat is JSON-only transport)
- `.github/workflows/camping-forecast.yml` — fallback-cron `30 0,6,12,18` lokaal + **slot-bewuste guard** + retry + commit (`[skip ci]`); orchestrator-doelen 00:00/06:00/12:00/18:00
- `docs/camping.html` + `docs/js/camping.js` — **standalone** dashboard: bewust niet gelinkt vanaf/naar de andere pagina's, en zonder Chart.js/CDN (matrix + tegels zijn kale divs → CSP `script-src 'self'`, strakker dan de andere dashboards). Draagt sinds ronde 2 (aug 2026) bewust een **eigen posterthema** (retro nationaal park: berg-hero-SVG, eigen `:root`-palet, Alfa Slab One/Barlow Condensed/IBM Plex Mono — géén shared.css/theme.js; één lichte modus). De kwaliteitskleuren zijn met de dataviz-validator geijkt op het crème-oppervlak `#f5ecd7`; "matig" is **stormblauw** en "slecht" **amber** (bewonersbesluit: oranje voelt slechter dan blauw), en rood draagt altijd een glyph (⚠ officieel / ✕ extreem)
- `docs/camping_data.json` — **generated by the action, never edit manually**

### Per-run flow
1. MeteoAlarm-feeds per land (NL/AT/FR) — niet-fataal: uitval → `warnings_status[land]="failed"` (het artefact onderscheidt "geen waarschuwingen" altijd van "feed onbereikbaar", het dashboard toont er een banner voor).
2. Per regio: Open-Meteo-forecast (hourly, 16 dagen; één kapotte regio → `status: "unavailable"`, de rest draait door; álle regio's kapot → raise) + ECMWF-ensemble (`ecmwf_ifs025`, ~51 leden, ~15 dagen; niet-fataal).
3. Score per **kampeernacht** (zie hieronder), vensterdetectie, vertrekadvies, zekerheid.
4. `docs/camping_data.json` schrijven → commit. `DRY_RUN=1` rekent en print maar **schrijft niet** — schrijven is het enige neveneffect, dus een dry run die wél schrijft zou van een echte run niet te onderscheiden zijn.

### Kampeernacht & scoring (do not casually retune — drempels zijn domeinbeslissingen)
- De eenheid is de **kampeernacht**: de cel van dag D beoordeelt het dagdeel (09–21u) plus de nacht D 21:00 → D+1 09:00. Op DST-nachten is die snede 23/25u — min/som-semantiek blijft geldig.
- **Strafpunten** (0 = perfect, `PEN`-dict): hitte (27–30 → 10, ≥30 → 40), nachtkou (10–12 → 8, 8–10 → 31, 5–8 → 40 — de 8–10-band ligt bewust bóven `CAT_GOED`, want een nacht onder de 10° schendt het harde criterium en mag nooit in een venster vallen; bij elke her-tuning van `CAT_GOED` moet deze waarde er strikt boven blijven, bewaakt door een test), dauwmarge min(T−Td) van de nacht (<2° → `dauw_krap` 12, <1° → `dauw_nat` 15 — zie hieronder), dagregen (1–3 mm → 8, 3–8 → 20, ≥8 → 40; droge som maar kans ≥ `POP_DAY_UNSETTLED` 60% → `wisselvallig` 12, kans ≥ `POP_DAY_LIKELY` 85% → `wisselvallig_nat` 32 — zie hieronder), nachtregen bewust ~half (0.3–1 → 5, 1–5 → 12, ≥5 → 30; droge som maar kans ≥ `POP_NIGHT_UNSETTLED` 60% → 5, `nachtregen_wisselvallig`, aug 2026 — zie hieronder), windstoten (≥35 → 10, ≥45 → 25).
- **`wisselvallig` had tot 20 aug 2026 maar één trap: 8 punten, ongeacht of de kans 61% of 97% was, en geheel in `MINOR_REASONS`** — dus zelfs een dag met vrijwel zekere regen kon nooit boven "top" uitkomen (gemeld door de gebruiker: 21 aug toonde donkergroen terwijl het de hele dag zou gaan regenen — de deterministische som bleef net onder `DAY_RAIN_DRY_MM`, dus de score liep uitsluitend via de kans). Net als dagregen zelf (licht/matig/zwaar) is de kans nu een ladder van twee trappen: onder `POP_DAY_LIKELY` (85%) blijft het een "kort buitje" (`wisselvallig`, 12 punten — een reëel maar klein ongemak, net niet meer "top"); erboven is het "vrijwel de hele dag nat" (`wisselvallig_nat`, 32 punten — een écht probleem, landt in "matig"). `wisselvallig` staat sinds deze fix niet meer in `MINOR_REASONS` (12 ≥ 12 — de bestaande grens tussen licht en echt), zodat geen enkele trap nog "top" kan opleveren, ook helemaal alleen niet. Het nachtelijke spiegelbeeld (`nachtregen_wisselvallig`) heeft bewust nog maar één trap — niet gemeld, niet aangepast.
- **Nachtregen had tot aug 2026 geen kans-signaal en geen plafond (gemeld door de gebruiker: "de komende 7 dagen overal veel regeniger dan het dashboard toont").** Twee losse gaten, allebei gedicht:
  - `wisselvallig` (droge modeluitkomst, hoge kans) bestond alleen overdag — het nachtdeel had geen enkel kans-signaal, dus een 0%-kans-op-droge-nacht in het ECMWF-ensemble bleef onzichtbaar zolang de deterministische run <0.3mm liet vallen. `night_metrics()` draagt nu `pop_max` (zelfde opbouw als `day_metrics`) en `score_day()` heeft dezelfde precedentie als overdag: een gemeten hoeveelheid wint altijd van de kans, de kans (`POP_NIGHT_UNSETTLED` 60%) vult alleen het gat als de deterministische som droog is. `pop_night_max` staat additief in het artefact.
  - `nachtregen_zwaar` (elke hoeveelheid ≥5mm) scoorde altijd exact 30 punten — toevallig precies `CAT_GOED`, dus een stortbui 's nachts (gemeten: 25.2mm, Elzas 24 aug) kon nooit boven "goed" uitkomen. Dagregen heeft hiervoor al een apart plafond (`DAY_RAIN_RED_MM` 20mm → rode vlag `stortregen`, buiten de score om); nachtregen kreeg het nachtelijke spiegelbeeld: `NIGHT_RAIN_RED_MM` 10mm (helft van de daggrens) → rode vlag `stortregen_nacht`.
- **Dauw trekt een top-dag altijd naar "goed", nooit naar "matig" (20 aug 2026).** De gebruiker: een droge dag gaat verreweg voor een droge tent, maar dauw moet wél zichtbaar blijven. Tot deze fix stond `dauw_krap` in `MINOR_REASONS` op precies `CAT_TOP` (10) — een verder perfecte dag met alléén een krappe dauwmarge bleef dus "top" i.p.v. te zakken naar "goed" (empirisch getroffen: 28 van de 179 dagen in het toenmalige artefact, en dauw komt sowieso vaak voor — 65% van alle dagen droeg `dauw_krap` of `dauw_nat`). `dauw_krap` (12) en `dauw_nat` (15) liggen nu allebei boven `CAT_TOP` maar ruim onder `CAT_GOED` (30): dauw alléén duwt een top-dag naar "goed", nooit verder — "nat" weegt bewust nog steeds zwaarder dan "krap". `dauw_krap` staat sinds deze fix niet meer in `MINOR_REASONS`.
- **Lichte problemen stapelen niet op elkaar (`MINOR_REASONS`, aug 2026).** De goedkoopste trap van elke ladder (`hitte_naderend`, `koele_nacht`, `dagregen_licht`, `nachtregen_licht`, `wind_fris` — stuk voor stuk ≤10 punten) telt niet bij elkaar op: `_score_reasons` neemt de som van de **echte** problemen (alles ≥12 punten) plus alléén het zwaarste lichte probleem, apart berekend voor het dagdeel en het nachtdeel. Reden: vier losse, op zichzelf onschuldige ongemakken (bv. een fris windje, een iets te warme middag, een krappe dauwmarge, een kans op een bui) mochten een dag niet uit een kampeervenster duwen — vóór deze regel gebeurde dat wél (gemeten 18 aug 2026 in Utrecht: 38 punten uit vier lichte redenen). Een "echt" probleem (matig/zwaar tier, bv. `dagregen_matig`) telt onverkort mee, ook naast andere problemen — dit dempt alleen het optellen van lichte ongemakken, niet het samenkomen van meerdere echte problemen.
- **De celscore is het zwaarste van de twee helften, niet hun som (`score_day`, aug 2026).** Eerst opgeteld ("dagdeel + nachtdeel"), maar dat gaf precies het spiegelbeeld-probleem van de vorige bullet: twee helften die elk op zichzelf keurig "goed" scoorden (bv. 30 + 24) konden samen over de "matig"-grens heen naar "slecht" kieperen — het overzicht toonde dan een rode cel terwijl `cat_day`/`cat_night` op de tegel eronder allebei groen stonden (gemeld 13 aug 2026, Salzburgerland 16 aug). Met `max(score_dag, score_nacht)` kan de gecombineerde cel per constructie nooit slechter zijn dan wat de dag- en nachttegel zelf al laten zien. Gevolg: "stapelen" van *echte* problemen gebeurt alleen nog binnen één helft (twee nachtproblemen tellen samen op), nooit meer tussen dag en nacht — vastgelegd in `tests/test_camping_forecast.py`.
- **Categorie:** ≤10 top, ≤30 goed, ≤45 matig, anders slecht. **Rood** (harde stop, overschrijft elke score): MeteoAlarm-waarschuwing van **oranje of hoger** die dag- of nachtvenster raakt, óf — voorbij MeteoAlarms ~2-4-daagse horizon — extreme voorspelde waarden (Tmax ≥ 33, nacht ≤ 5, stoten ≥ 60 km/u, dagregen ≥ 20 mm). Het geel-filter (`severe_warnings`/`WARN_MIN_LEVEL`) leeft in `camping_forecast.py`, bij het domeinbesluit — `meteoalarm.py` blijft de generieke parser die ook geel parst. Let op: hierdoor tonen ook `warning`/`warnings_active` uitsluitend oranje+ (inhoudswijziging, geen vormwijziging).
- **Venster:** ≥ `MIN_NIGHTS` (3) aaneengesloten nachten met cat ∈ {top, goed}; matig breekt het venster; een horizon-afgekapte nacht telt niet mee. **Vertrek:** droog als laatste nacht ≤ 0.3 mm én vertrekochtend (06–12u) ≤ 0.3 mm; anders schuift `beste_vertrek` naar de laatste droge ochtend die ≥ 3 nachten overlaat.
- **Zekerheid:** per dag de ensemble-ledenfracties P(nacht>10°), P(dag<30°), P(droge dag), P(droge nacht); de **zwakste** fractie bepaalt de tier (≥0.80 hoog, ≥0.55 middel), afgetopt op de horizon (dag ≥ 10 → max middel, ≥ 13 → laag); zonder ensemble een pure horizon-ladder (<3d hoog, <8d middel). Een venster draagt de zwakste tier van zijn dagen.

### Dag/nacht-splitsing & verwachting (ronde 2, aug 2026)
- **Dag/nacht-tegels:** naast de gecombineerde cel splitst `split_parts` de score in een dag- (09–21u) en nachtdeel (21–09u) via de vaste partities `DAY_REASONS`/`NIGHT_REASONS` (dekken `PEN` exact en disjunct — test bewaakt) en `DAY_FLAGS`/`NIGHT_FLAGS`; `"waarschuwing"` splitst op vensteroverlap. Deel-categorieën (`cat_day`/`cat_night`) lopen door dezelfde `category()`-ladder. De regiokaarten tonen brede dagtegels met smalle kwart-nachttegels ertussen; de matrix blijft de gecombineerde kampeernacht wegen (som van beide delen — een cel kan dus slechter zijn dan beide deel-tegels apart, dat is bewust).
- **`verwachting_text`:** autotekst "wat je kunt verwachten" per venster + per regio (komende `VERW_DAYS` 5 dagen als er geen venster is): dag-/nachtkarakterbanden, de `SLAAPZAK`-ladder voor de peuter (≥18° dun · ≥14 gewoon · ≥10 warm+mutsje · eronder "eigenlijk te koud"), regendagen bij naam, dauwclausule op de bestaande `DEW_MARGIN_*`-drempels. Drempels zijn domeinbeslissingen; tests pinnen erop.
- **`main_reason` + de "waarom?"-toggle (aug 2026):** additief per-dag-veld met de zwaarste reden van de zwaarste helft — dezelfde helft die de celkleur bepaalt, dus het ene woord dat de kleur verklaart (gelijkspel → de dag). De matrix toont er achter een toggle (standaard uit) een reden-icoon mee, **alleen op matig/slecht-cellen**: top/goed behoeven geen uitleg, rood houdt ⚠/✕. Iconengroepen: ☂ regen · ☀ hitte · ❄ koude nacht · 💧 dauw · 💨 wind. De tooltip noemt de reden altijd voluit ("vooral: …" via `REDEN_TEKST` in camping.js) — dat is ook het mobiele pad. Oud artefact zonder het veld → de toggle doet niets (graceful).

### Flexibele super-regio's (ronde 3, aug 2026)
Twee tegels onder de matrix beantwoorden de vraag *"in welke grote regio
zitten we mét verplaatsen het beste?"*: `SUPER_REGIONS` partitioneert de
twaalf niet-Utrecht-streken op geografie in **Noordoost-Frankrijk**
(vitry_le_francois/colmar/mulhouse/montbeliard/dijon/besancon — Bourgogne/
Franche-Comté/Elzas) en **Oost-Frankrijk** (chamonix/annecy/chambery/
grenoble/valbonnais/valence — de Zuidoost-Alpen-hoek) — een test bewaakt dat
de partitie exact en disjunct dekt. Deze knip verving (bewonersverzoek,
aug 2026) een eerdere versie met alle twaalf streken in één "Oost-Frankrijk"-
groep, die op haar beurt **Oostenrijk** en **Noordwest-Frankrijk**
(salzburgerland/tirol/karnten/steiermark resp. normandie/bretagne) opvolgde
toen de focus op naam genoemde Oost-Franse steden verschoof. Per super-regio rekent `flex_route` (klein dynamisch
programma over (subregio, nachten-op-deze-plek), server-side, stdlib) de
goedkoopste route uit met **minimaal `MIN_NIGHTS` nachten per plek**:
- Dagkosten = de bestaande celscore van de gekozen subregio; **verkassen kost
  `MOVE_PENALTY` (8)** — één "licht ongemak"-equivalent, zodat de route niet
  voor 2 punten winst met de tent gaat slepen. **Rood = `RED_DAY_PENALTY`
  (10000, was 5000 vóór de dauw-fix van 20 aug 2026 — die kromp de marge op
  de pinning-test tot 8) bovenop de score**: een big-M die élke gewone route
  domineert (test pint `RED_DAY_PENALTY > FORECAST_DAYS × (som niet-minor PEN
  + max minor + MOVE_PENALTY)`), dus routes rangschikken eerst op
  onvermijdelijke rode dagen, dan pas op score — maar er bestáát altijd een
  route. De ruimere marge is bewust: elke PEN-hertuning laat deze test
  strakker aantrekken, en de vorige twee her-tuningen (wisselvallig,
  20 aug 2026; dauw, 20 aug 2026) deden dat allebei.
- Tie-breaks deterministisch (lexicografisch (kosten, verkassingen), dan de
  eerste subregio) — 4×/dag draaien mag de route niet laten wiebelen op
  dict-volgorde. Bewust **stateless/indicatief**: geen cross-run-hysterese; de
  kopcijfers (`nights_ok`/`moves`) zijn stabieler dan de route zelf en leiden
  de tegel. In de horizonstaart mag de route nog verkassen (eindverblijf <
  `MIN_NIGHTS` — vastpinnen zou de route bevoordelen waar de zekerheid toch al
  "laag" is).
- **De getoonde dagwaarden zijn altijd de échte cat/score/conf van de gekozen
  subregio** — de strafgetallen sturen alleen de routekeuze. Kopcijfers tellen
  alleen volledige nachten (`night_partial` uitgesloten, net als de vensters);
  `windows` op de route hergebruikt `detect_windows` ongewijzigd, bewust zónder
  vertrekadvies/verwachting (die vergen uurlijkse rows per gekozen regio).
- Frontend (`flexSectionHTML`/`flexTileHTML` in camping.js): kop "X van N
  nachten goed · k× verkassen", een eigen heatmap-rij (hergebruikt
  `mx-cell`/`cat-*`/`conf-*`/`win-mark`; verkasdag = donkere linkerrand,
  `.flex-move` — status nooit op kleur alleen), de route als
  `label datum – datum → …`-regel, en **★ beste keuze** op de tegel met de
  meeste goede nachten (gelijk → minste verkassingen). Oud artefact zonder
  `super_regions` → sectie afwezig (zelfde graceful patroon als `verwachting`).

### MeteoAlarm (verwachtingen vs. werkelijkheid)
De parser is bewust defensief: element-toegang via lokale tagnaam (CAP 1.1/1.2-namespaces), `awareness_level` ("2; yellow; Moderate") wint van kale CAP-`severity`, Minor/groen valt af, fr/en-taalduplicaten worden ontdubbeld, ontbrekende `expires` → onset + 24u. **De `area_patterns` per regio zijn best-effort** (AT waarschuwt per district/Gau, FR per departement) — elke run logt een steekproef areaDesc-regels; leg die bij twijfel naast de patterns. De regiocoördinaten zijn representatieve kampeerdalen (geen bergtoppen) en bewust aanpasbaar.

### Timing (4×/dag — het zandbak-patroon veralgemeend)
Orchestrator: vier dispatch-blokken met elk een **eigen dedup-anker** (`day_start`/06:00/12:00/18:00-epochs) + halfopen `nowm`-vensters — anders dedupt slot 1 alle latere slots weg; bewust geen modulo-21600-bucket (UTC-gebonden, verschuift met DST). De fallback-guard in de workflow ankert op het **lopende 6-uursslot**, niet op middernacht — met 4 runs/dag zou een middernacht-venster de fallback altijd laten skippen (de soil/mowing-les, zie "Meldmoment" bij Project 1).

### camping_data.json schema (additive only — never break existing fields)
Kop: `generated_at`, `as_of_local`, `source`, `horizon_days`, `params` (alle drempels + `ensemble_model` + `WARN_MIN_LEVEL`), `warnings_status` per land. Per regio: `id/label/country/lat/lon/elevation_m`, `status` (`ok|unavailable`), `ensemble` (`ok|unavailable`), `verwachting` (autotekst, ronde 2), `days[]` (`date`, `tmax`, `tmin_night`, `dew_margin_night`, `rain_day_mm`, `rain_night_mm`, `pop_day_max`, `gust_max_kmh`, `score`, `cat`, `red_flags[]`, `reasons[]`, additief ronde 2: `cat_day`, `cat_night`, `red_flags_day[]`, `red_flags_night[]`, `main_reason`, `warning`, `probs` (de vier ledenfracties), `conf`, `night_partial`, additief aug 2026 (nachtregen-kans-signaal): `pop_night_max`), `windows[]` (`start`, `end_night`, `vertrek`, `nights`, `droog_vertrek`, `beste_vertrek`, `tmin_min`, `tmax_max`, `rain_total_mm`, `conf`, additief ronde 2: `verwachting`), `warnings_active[]` (alleen oranje+). Additief ronde 3: `MOVE_PENALTY` in `params` en top-level `super_regions[]`: `id/label/region_ids[]`, `status` (`ok|unavailable`, unavailable = stub zonder `days`), `days[]` (`date`, `region`, `region_label`, `move`, `cat`, `score`, `conf`, `night_partial`, `tmax`, `tmin_night`, `dew_margin_night`, `rain_day_mm`, `rain_night_mm`, `red_flags[]`, `main_reason`), `segments[]` (`region`, `region_label`, `start`, `end_night`), `moves`, `nights_ok`, `nights_total`, `red_days`, `windows[]` (zelfde vorm als de regio-vensters, zonder vertrek/verwachting).

### Relation to other projects
Fully independent — geen artefacten van andere projecten, geen Gist, geen tado. Hergebruikt alleen `http_util`/`shared_const`/`notify` en de Telegram-secrets voor de crash-alert. Bewust géén nav-links van of naar de andere dashboards.

---

## Project 16: Gardena bewatering-automaat (Smart Irrigation Controller)

**Goal:** Bestuurt de twee kranen van het GARDENA smart system (kraan 1 = gras-sproeier 20 mm/u, kraan 2 = struiken-druppelslang 2 mm/u) op basis van het FAO-56-bodemmodel van Project 1, meet + registreert kraan-opentijd automatisch in het irrigatielogboek zodat de waterbalans klopt, en archiveert de bodemsensor als groeiende ijk-dataset. **Meldt uitsluitend privé** (start/stop van elke automatische beurt + operationele afwijkingen, `TELEGRAM_CHAT_ID`); geen dashboards-artefact onder `docs/` — het (token-gated) paneel op het bodem-dashboard leest de Gist rechtstreeks.

### Files
- `gardena_api.py` — transport: token (client_credentials), één `GET /locations/{id}`-snapshot per run, `parse_snapshot`, kraan-commando's (`START_SECONDS_TO_OVERRIDE`/`STOP_UNTIL_NEXT_TASK`). Retries alleen op transiënte netwerkfouten, nooit op een HTTP-status.
- `gardena_control.py` — runner + zuivere beslis-/meterfuncties; `run_guarded`, alle tunables bovenin.
- `tools/gardena_bootstrap.py` — eenmalige lokale ontdekking (location/kraan-service-ids/sensor-id → `gardena_config.json`; zaait `garden_automation.json` alleen als het nog niet bestaat). Apparaatnamen blijven in de terminal — nooit in Actions draaien.
- `.github/workflows/gardena-control.yml` — uurlijks via de orchestrator (onvoorwaardelijk, geen soil-poort: leest de branch-tip `data.json` van de vórige bodem-run en bewaakt zelf `MAX_DATA_AGE_H`) + fallback-cron alleen rond de twee beslismomenten (05:35/22:35) + guard-job op het lopende klokuur; checkout gepind op de branch-tip; commit alleen `data/gardena_history` (`[skip ci]`). **Bewust géén in-job herkansing** — API-fouten eindigen ín het script als exit 0 + privé-alert met cooldown, want een herkansing/rode run eet het API-budget op (orchestrator herdispatcht elke tick zolang er geen groene run staat).
- `data/gardena_history/<YYYY-MM>.json` — sensor-maand-shards (station_history-patroon: idempotent op sensor-timestamp `t`, update-not-append, env-override `GARDENA_HISTORY_DIR`). **Whitelist afgedwongen door een test:** alléén sensor- en sensorbatterij-velden — nooit kraandata, ids of vlagstanden.
- `tools/gardena_sensor_eval.py` — **de sensor als toetssteen voor Project 1's waterbalans** (handmatige diagnose, geen netwerk, draait op de gecommitte artefacten). Sensor en model meten niet hetzelfde: de sensor-% is een ongedocumenteerde schaal (70 % kán geen θ zijn), de prikker zit op ~5–10 cm waar het model géén toestandsvariabele heeft (de oppervlaktelaag `De` loopt alleen door verdamping leeg en blijft onder de dichte canopy 92–96 % vol, terwijl de wortelzone al 26–37 % uitgeput is), en één prikker is geen zone-gemiddelde. De tool kiest daarom **geen** mapping maar rekent er vier naast elkaar door, en de maat die telt is de **dynamiek** (dag-op-dag-verschillen — daar overleeft een onbekende schaal en een ruimtelijke offset niet in), niet een RMSE. De prikker zit in de **struiken** (bewonersopgave aug 2026 — `gardena_config.json` draagt geen zoneveld, dus dit is opgegeven kennis; `SENSOR_ZONE`/`--zone`). Scherpste dieptetoets is een flinke regen- of druppelbeurt op **uurresolutie**: regen wordt in FAO-56 §7.4.5 van béíde bakken tegelijk afgetrokken, dus ze verschillen niet in óf ze stijgen maar in hoe snel ze vól zitten (oppervlak na ~2 mm, wortelzone struiken pas na ~20 mm) — een vormtoets die ook werkt als de sensorschaal niet-lineair is. Eerste analyse + de vooraf vastgelegde voorspelling: `SOIL_SENSOR_ASSESSMENT.md`. **Nog geen enkele modelparameter is hierop aangepast** en dat hoort ook niet te gebeuren op grond van niveauverschillen — zie de ground rule over bodemparameters.
- Paneel: `docs/js/index.js` (`initGardenPanel`, alleen gebouwd mét Gist-credentials — het bestaat niet in de DOM voor anonieme bezoekers), geen eigen HTML.

### Gist-bestanden (in de bestaande `GIST_ID`-Gist) — één schrijver per bestand
- `gardena_config.json` — schrijver: bootstrap (eenmalig). location_id + kraan-service-ids (lawn/shrubs) + sensor_id.
- `garden_automation.json` — schrijver: browser (paneel). `auto_lawn` ("Gazon-automaat") + `paused`. Het paneel dispatcht bewust géén workflow bij een schakeling — de uurlijkse run pikt de stand op.
- `gardena_state.json` — schrijver: de action. Sessie, dag-geheugen (`day` — bewust in de Gist en niet in een gecommit state-bestand: committijden zijn publiek), opentijd-meter, `last`/`recent`/`next`, health, alert-cooldowns. State + registraties gaan in **één atomaire multi-file-PATCH** zodat een halve schrijf nooit dubbel kan registreren.
- `irrigations.json` — **gedeeld met de dashboard-modal van Project 1**: de action merge't additief met exact de browser-semantiek (hele minuten, mm op 0,1 in `_meta`, verse read vlak vóór de PATCH). Geaccepteerd restrisico: het theoretische write-window met een gelijktijdige handmatige invoer is minuten groot en de merge is additief.

### Beslissingen (do not casually retune — domeinbeslissingen)
- **Slots** zoals het bodemadvies (`past_local_time` + dag-geheugen): gras op de eerste run in [05:00, 09:00), struiken op de eerste run in [22:00, 24:00). Een genomen "nee" verbruikt het dagslot (een rustige ochtend mag 's middags geen sproeier worden); een uitvoeringsblokkade (kraan bezet, data ouder dan `MAX_DATA_AGE_H`, API-fout) verbruikt het niet en herkanst het volgende uur binnen het venster.
- **Wanneer:** `lawn_status`/`shrubs_status` prioriteit ∈ {medium, high} — hetzelfde criterium waarop het bodemadvies een mens zou laten sproeien (regen-dekking zit daar al in). Gras alleen met `auto_lawn` aan; struiken jaarrond. Vorstgrens (`FROST_SKIP_TMIN_C`), weeklimiet (`WEEKLY_CAP_MM`, noodrem tegen modelfouten, telt álle registraties mee) en `MIN_SESSION_MIN` ervoor.
- **Hoeveel:** `proposal_min` uit het model; gras gekapt op `LAWN_MAX_MIN` 45 (één START-commando), struiken op de minuten tot de eerstvolgende lokale 05:00 (`SHRUBS_END_H`) — nooit twee kranen tegelijk, en een diepe struiken-aanvulling spreidt bewust over meerdere nachten (het model herbeslist elke avond).
- **Chunking:** commando's zijn ≤ `MAX_CMD_SECONDS` 5400 (Irrigation Control-limiet); elke uurlijkse run her-overridet vóór het verlopen (geen gaten), de laatste chunk eindigt op de doeltijd → het normale einde is de **hardware-autoclose**. Valt de pijplijn uit, dan sluit de kraan binnen ~90 min vanzelf — dat is de vangrail, en waarom een gemiste run de sessie beëindigt i.p.v. hervat.
- **Opentijd-meter** (`meter_step`): reconstrueert per kraan de voltooide open-intervallen uit opeenvolgende snapshots (activity + timestamp + duration, altijd geklemd op [vorige check, nu]; onzin-timestamps degraderen naar ±een half uur, nooit naar garbage). Volledig-binnen-het-gat-beurten krijgen een half-venster-schatting. **De geregistreerde mm komen altijd uit de meter**, ook voor eigen sessies — eerlijker dan commando-rekensommen bij vroegtijdige stops.
- **Registratieregels (bewonersbesluit):** kraan 2 (druppelslang) bewatert per definitie de struiken → álle opentijd wordt geregistreerd, ook handmatige app-beurten (stil bericht "Geregistreerd" als het geen eigen sessie was). Kraan 1 (sproeier) wordt ook voor andere dingen gebruikt (speelbadje) → opentijd telt alléén mee zolang `auto_lawn` aan staat; uit = de bewoner logt zelf via de modal (anders dubbel). Een openstaande kraan wordt op een beslismoment nooit gekaapt (start wordt uitgesteld).
- **Bewaking:** kraan niet dicht op de geplande eindtijd → STOP + alert; START zonder gemeten opentijd → alert; `SCHEDULED_WATERING` gezien → app-schema's horen uit te staan → alert + sessie los; sensor stil/batterij laag/rf offline → alert; 429 → alert + rust tot de volgende run. Alles gededupliceerd via cooldowns in de Gist-state.

### Privacy-grens (bewonersbesluit — zelfde status als de `TADO_ZONE_ALIASES`-grens)
De standen van `garden_automation.json` en alle beslisinformatie (sessies, planning, dag-geheugen) zijn privé: nooit in run-logs, commits, `docs/`-artefacten of de groepschat. Concreet afgedwongen: de stdout van `gardena_control.py` is **vormvast** (codeert nooit een beslissing, vlagstand of hoeveelheid — ook de Telegram-verzendregel wordt onderdrukt; test vergelijkt de log van een sproei-run met die van een stille run), de cadans is constant (uurlijks vanaf de merge, vóór de secrets bestaan; API-fouten = exit 0, geen rode clusters), het paneel bestaat alleen in een browser mét Gist-credentials, registraties zijn byte-compatibel met handmatige invoer, en de sensor-shards dragen een afgedwongen veld-whitelist. `DRY_RUN=1` rekent alles door maar rapporteert via privé-Telegram — niet naar stdout. `FORCE_ZONE`/`FORCE_MINUTES` (workflow_dispatch) start een korte echte testsessie zonder dagslot-verbruik.

### Relation to other projects
Leest Project 1's `docs/data.json` read-only (het beslissingscriterium) en **schrijft als enige tweede partij het irrigatielogboek** (`irrigations.json`) — met de browser-semantiek, zie boven; verder eigen Gist-bestanden + eigen shards. Nieuwe secrets: `GARDENA_APP_KEY`/`GARDENA_APP_SECRET`; hergebruikt `GIST_ID`/`GIST_TOKEN` + privé-Telegram. Schema's in de GARDENA-app horen **uit** te staan — de automaat is de enige bestuurder; de app blijft de handbediening (en handmatige druppelbeurten worden gewoon geregistreerd).

---

## Shared modules: `wu_bias.py`, `om_bias.py`, `notify.py`, `gist_io.py`, `artefact_io.py`, `http_util.py`, `shared_const.py`

Seven small cross-project Python modules (everything else is self-contained):
- **`wu_bias.py`** — the WU station's radiative temperature-bias correction — `correct_temp(temp_c, solar_wm2)` and
  `bias_estimate(solar_wm2)` plus the calibrated `SOLAR_BIAS_SLOPE` (°C per W/m², source-agnostic
  driver). Imported by **soil_model.py** (Tmax/Tmean on WU days), **window_advisor.py** (outside-now
  on WU readings) and **vent_io.py** (buiten-nu-verfijning `refine_outside_now`, Project 13). Calibrated by
  Project 7. Zero third-party deps. See the soil "WU stralingsbiascorrectie" bullet and Project 7 for
  the full picture.
- **`om_bias.py`** — het spiegelbeeld van `wu_bias.py`: daar corrigeren we een *meetfout* van
  het eigen station met een door Project 7 gekalibreerde constante, hier een *modelfout* van
  Open-Meteo — en die constante kan niet vastliggen (hij schuift met het seizoen en het
  weertype), dus leert de module hem **online** uit de eigen historie. Zuivere functies over
  gewone dicts (`record_forecast`/`verify_pending`/`learn`/`bias_for`/`correction_for`); het
  logboek zelf leeft additief in `window_data.json` (veld `om_bias`, privé artefact-gist), waar de aanroeper
  het persisteert. Geleerd via echte **forecastverificatie** (elke run wordt de forecast voor
  een uur 6–18u vooruit vastgelegd en na afloop afgerekend tegen wat het station toen mat) —
  níet via de nowcast-fout, want de modelfout op lange termijn is meetbaar groter (+1,4 vs.
  +1,0 's nachts) en leren op de nowcast zou structureel ondercorrigeren. Twee emmers,
  **nacht en dag**: een 24-slots uurprofiel bleek op een holdout niet te generaliseren (het
  middagpiekje uit de ene hittegolfweek gold de volgende niet meer, MAE 1,31 vs. 1,23 voor
  één constante), twee emmers wél. Mediaan i.p.v. gemiddelde (één onweersnacht mag de
  correctie niet meeslepen), geklemd op `MAX_BIAS` 3 °C, en 0 zolang een emmer onder
  `MIN_SAMPLES` zit — dan gedraagt de aanroeper zich exact als vóór de module. Leren gebeurt
  met een harde nacht/dag-knip, *toepassen* met een gladde overgang van `TRANSITION_H` (1u)
  rond de grenzen (zelfde patroon als `neighbor_night_cap` in de tweelingen), anders zet de
  correctie een sprong van ~1 °C tussen twee forecast-uren waar `predict_open_intervals` een
  kunstmatige kruising op vastpakt. Gemeten op holdout: nacht-MAE 1,69 → 1,20, RMSE
  2,21 → 1,55. Geïmporteerd door **window_advisor.py** (leert + persisteert het logboek) en
  door **vent_io.py** (`build_timeline` — de enige plek waar de buitentemperatuur de
  fysica binnenkomt, dus ook voor de kinderkamer-nachtvoorspelling). Omdat de geleerde params van
  de tweeling de bias absorberen, gaat een herijking van de correctie samen met een
  `PHYSICS_REV`-bump: zie Project 13. Het logboek wordt bij deploy geseed met
  `tools/om_bias_backfill.py`, zodat de correctie niet dagen later als *stap* in de
  driver landt.
- **`notify.py`** — shared Telegram sender (`send_telegram`, transient-failure retry, never raises) plus
  `sanitize_error(e)`: secret-safe exception rendering (scrubs `apiKey=`/token query params, Telegram
  bot tokens and Gist-IDs out of URLs in exception text). **Ook de thuisbasis van de
  stille modus (aug 2026):** `notify_prefs.json` in de `GIST_ID`-gist — geschreven door
  uitsluitend de browser (toggle "🔕 Meldingen" in de vent-meldmodal, token-gated):
  `{"quiet": bool, "since": ISO, "cleared_at": ISO}`. Adviesberichten geven per call site
  `muted_in_quiet=True` mee (weerbericht, zandbak, maai-, bodem-, raam-advies + dagplan +
  urgente sluitingen, zonwering, nachtvoorspelling, koelplan, tweeling-nudges,
  verwarmingsexperiment); bij actieve stilte wordt niet verstuurd maar is het gedrag voor
  aanroeper én stdout **exact** dat van een geslaagde verzending (zelfde
  `[telegram] ✓ verzonden`, return True) — elke meld-state stempelt as-if-sent en géén
  publiek spoor (commit, artefact, log) verschilt van een gewone dag. Dat is de
  ontwerpkern: de activatie mag nergens publiek af te lezen zijn, dus een muted pad mag
  nooit een logregel, veldwaarde of state-overgang veranderen. Fail-open (geen
  creds/bestand/leesfout → gewoon sturen); prefs één keer per proces gelezen
  (`read_notify_prefs`, token `GIST_TOKEN` óf `GH_TOKEN` — drie workflows exporteren de
  gist-token onder die naam). **Niet** muted: weekjournaal, álle Gardena-berichten,
  de tado-token-persist-alert en de `run_guarded`-crash-alerts (ops moet altijd
  doorkomen). Neveneffecten elders: de tweeling holdt zijn leren stil (als de
  huis-pauze, zonder marker — zie Project 13) en de maai-adviseur vuurt op het eerste
  advies-slot ná `cleared_at` één terugkeer-por los van de RENUDGE-klok
  (`return_nudge_due`). **Always** print/forward exceptions from
  WU/Telegram/Gist calls via `sanitize_error` — never raw `{e}` — because the credential sits in the
  request URL. Also home of **`run_guarded(main, name, ...)`**: the top-level crash guard every runner
  script uses (sanitized FATAL, Telegram alert, exit 1). The two quarter-hour loop scripts pass
  `fail_threshold=6` so a transient hiccup doesn't page — only ~1.5h of consecutive failures does
  (counter in `RUNNER_TEMP`, reset on success, alert only on the first crossing; silent under `DRY_RUN=1`).
  The one-shot runners that call an API (soil check, zandbak, weerbriefing, grasmaai) pass
  `fail_threshold=2`, paired with their workflow's one in-job retry after 10 min — a single API blip
  retries silently; only a persistent outage pages. (`verwarming` calls no API and keeps default 1.)
- **`gist_io.py`** — shared **read-only** Gist helpers (`read_file` raises, `read_json` is
  graceful, `read_files` haalt alle bestanden in één call). Volgt bij de ~1 MB-truncation
  van de Gist-API de `raw_url` i.p.v. stilletjes een halve JSON terug te geven.
  Gist *writes* deliberately stay per-project (see ground rule on Gist write logic; de
  enige uitzonderingen zijn expliciet: window_advisor's token-persist en het
  openingen-archief van de vent-action in `vent_io._gist_write_files`).
- **`artefact_io.py`** — de privé artefact-gist (`ARTEFACT_GIST_ID`) voor `data.json`,
  `mowing_data.json`, `mowing_state.json`, `window_data.json` en de drie vent-artefacten
  (privatisering aug 2026, uitgebreid door de privacy-sweep): secret gezet → lees/schrijf via de
  Gist-API en geen lokaal bestand meer; secret afwezig → het oude lokale pad
  (zelf-activerende migratie, tevens het test-/bootstrap-pad). Eén schrijver per
  bestand: data.json ← check_and_notify, mowing_data.json + mowing_state.json ←
  mowing_advisor, window_data.json ← window_advisor, de drie vent-artefacten ← vent_twin;
  lezers: mowing_advisor, gardena_control, weekjournaal, vent_io (`load_window_data`/
  `load_learned`, dus ook P10/P14) + de dashboards client-side.
- **`http_util.py`** — `get_json(url, params, timeout=, label=)`: the one GET→JSON transport with
  retry/backoff (5 attempts, 3+8+30+60s — a ~100s window that rides out short TLS-reset/timeout
  bursts) and sanitized error logs, used by all six Open-Meteo fetch sites.
  Transport only — parameter sets and parsing stay at the call sites; exceptions propagate after the
  last attempt so existing fallback paths keep working. WU fetches deliberately stay outside it
  (apiKey embedded in the URL string + bespoke partial-failure handling).
- **`shared_const.py`** — the single source for `LATITUDE`/`LONGITUDE` (Utrecht Oost) and
  `TZ` (Europe/Amsterdam), plus small stdlib date/time helpers that bundle the repeated
  boilerplate: `utc_now_iso()` (ISO UTC `generated_at` stamp), `local_today()`
  (`datetime.now(TZ).date()`), `parse_date()` (`YYYY-MM-DD` → `date`) en
  `past_local_time(hour, minute, now=None)` — de meldpoort voor de pijplijnen die vaker
  *draaien* dan ze *melden* (Projects 1 en 5, uurlijkse cadans). Bewust alleen de
  klokvraag: het dag-geheugen ("heb ik vandaag al gemeld?") blijft per project in zijn
  eigen state-bestand, en `now` is injecteerbaar zodat de tests de klok bezitten.
  Modules re-bind the constants to their existing local aliases.

---

## Shared secrets (GitHub Actions)
- `WU_STATION_ID`, `WU_API_KEY` — Weather Underground (soil project + window advisor)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — soil, sandbox, heating, mowing + window advisor (raam-advies + operational alerts, privé-chat) + vent twin (Project 13: anomalie-nudge + crash-alert, privé-chat)
- `TELEGRAM_CHAT_GROUP_ID` — weather briefing + night forecast + koelplan (Project 14) + het dagplan van de raam-adviseur (group chat)
- `WU_NEIGHBOUR_IDS` — komma-gescheiden buur-PWS-id's voor de coherentie-toets (Project 7, route A); locatiegegevens, dus nooit in de repo
- `GIST_ID`, `GIST_TOKEN` — soil project (irrigation log) + mowing advisor (mow log, same Gist) + vent twin (Project 13: opening log `house_openings.json` read-only from Python, plus het action-geschreven openingen-archief `house_openings_<YYYY-MM>.json` én — sinds de privacy-assessment aug 2026 — de twin2-maand-shards `twin2_history_<YYYY-MM>.json`, action-geschreven, read-only voor twin-eval/ml-dataset/tools) + de stille modus (`notify_prefs.json`, browser-geschreven, door álle melders read-only gelezen) + bewatering-automaat (Project 16: `gardena_config.json`, `garden_automation.json`, `gardena_state.json` + tweede schrijver van `irrigations.json`, same Gist); `GIST_TOKEN` also used by the window advisor
- `GARDENA_APP_KEY`, `GARDENA_APP_SECRET` — Husqvarna Developer Portal-applicatie (Project 16); key = OAuth client_id = X-Api-Key, secret = client_secret
- `ARTEFACT_GIST_ID` — de privé artefact-gist voor `data.json`/`mowing_data.json` (privatisering aug 2026, zie `artefact_io.py`), sinds de tweede ronde ook `vent_data.json`/`vent_forecast.json`/`vent_learned.json` (Project 13 — het dashboard zélf is nu token+artefact-gist-gated) en sinds de privacy-sweep óók `window_data.json` (Project 6, met `window.html`/`grafiek.html` gegated) en `mowing_state.json` (Project 5); auth via het bestaande `GIST_TOKEN`. Zolang het secret niet bestaat draait alles in de lokale-bestand-terugval
- `TADO_GIST_ID` — **separate secret Gist** for the window advisor: rotating tado refresh token (`tado_token.json`) + per-room advice state, meldgeheugen en dagbudget (`window_state.json`)
- `BRIEFING_BLOCKS` — optioneel, JSON met de tijdblokken van de weerbriefing (Project 2). Privacy-grens uit de privacy-sweep (aug 2026): een weekrooster van vertrek-/opvang-/thuiskomst-/sportvensters is een "wanneer is het huis leeg"-kalender en hoort niet in een publieke repo. Afwezig → generieke dagdelen.
- `TADO_ZONE_ALIASES` — optioneel, JSON `{gepubliceerde kamernaam: tado-zonenaam}` (bv. `{"Nursery": "<naam in de tado-app>"}`). Privacy-grens uit de pseudonimisering van aug 2026: de repo + Pages-artefacten zijn publiek, de tado-app niet — een persoonsnaam als zonenaam hoort hooguit in dit secret. Afwezig → zonenamen moeten letterlijk aan `ROOMS` voldoen.
- `GITHUB_TOKEN` — automatic, sandbox project

## Variables
- `DASHBOARD_URL`

---

## Ground rules for Claude

- **Privacy is Priority 1 — see the banner at the very top of this file.** Never write
  the household's real address, precise location, or travel/vacation plans/dates into
  anything that reaches this public repo (code, comments, commits, branch names, PR
  text, workflow logs, `docs/` artefacts, test fixtures). When a change touches
  location or scheduling logic, re-read that banner before writing a single line.
- **Afwezigheid mag nergens publiek af te lezen zijn (aug 2026)** — de uitbreiding van de
  banner naar *gedrag*: geen pauze-/afwezigheidsmarkers of handmatige-actie-tijdstempels
  in publieke artefacten, gecommitte state of Actions-logs; scheduled stdout print nooit
  berichtteksten, gemeten kamerwaarden of huisboekhouding (het `gardena_control`-patroon —
  alleen een handmatige `DRY_RUN`-dispatch mag berichtinhoud tonen); de dashboards
  dispatchen géén workflows (een run-event dateert de interactie publiek); en élk
  code-pad dat door de stille modus (`notify_prefs.json`, zie notify.py) geraakt wordt
  moet byte-identieke publieke sporen achterlaten — een muted bericht print exact de
  verzonden-regel en stempelt zijn state as-if-sent. Nieuwe melders volgen dit patroon.
  **Een hash van een gedateerd veld lost dit niet op** (privacy-sweep aug 2026): het veld
  *verandert* op de run waarin de handeling plaatsvond, dus de commit dateert 'm alsnog —
  zulke state hoort de privé-gist in, niet de publieke historie (zie `mowing_state.json`).
- **Never modify `data.json`/`mowing_data.json`/`window_data.json`** — regenerated elke run; ze leven in de privé artefact-gist (`artefact_io.py`), niet meer onder `docs/`
- **A `PHYSICS_REV` bump needs a re-seed, and a fysica-wijziging meet je alleen met béíde armen
  her-geseed** (`tools/vent_seed.py` + `tools/horizon_backtest.py`). De geleerde params
  absorberen een fysische fout; de correctie erbovenop toepassen telt 'm dubbel — dan meet je de
  parameter-reset i.p.v. de fysica. Zie AIRFLOW3_ASSESSMENT.md §2.
- **Never re-report the twin's nowcast RMSE as a forecast score** — `vent_learned.json`'s ~0.5 °C
  is een nowcast over een venster dat elk kwartier op verse metingen wordt gezet. De
  voorspelscore is `tools/horizon_backtest.py`, en die is ~0.70 °C op 12u.
- **`bath` is bewust buiten scope — laat 'm met rust.** De badkamer wordt gewoon meegesimuleerd
  (ze is een zone in het druknetwerk) en staat op de plattegrond, op haar eigen kamerkaart en in
  de meldmodal, maar er gaat géén modelleer- of afsteltijd naar. Ze is raamloos met 0.62 °C
  totale spreiding over het hele record, dus "het blijft zoals het is" is er nauwelijks te
  verslaan — en ze staat als enige kamer structureel achter op persistentie (0.363 vs 0.352 op
  12u). Dat is een bekend en geaccepteerd resultaat, geen openstaand punt: niet als regressie
  rapporteren, geen bath-specifieke termen/parameters introduceren, en een verandering die
  alleen bath verbetert is geen reden om iets te shippen. Een verandering die bath duidelijk
  verslechtert is wél nog steeds een signaal — dan is er waarschijnlijk iets huisbreeds mis.
  **Sinds aug 2026 is "buiten scope" ook letterlijk zo geconfigureerd** (bewonersbesluit): ze
  draagt `exclude_from_fit` + `hide_in_charts` in `house_model.json`, dus ze leert niet meer mee
  en staat in geen enkele grafiek. Dat zijn de twee generieke vlaggen — géén bath-specifieke
  code — en een nieuwe uitzondering hoort langs dezelfde weg te lopen of helemaal niet.
- **Never change FAO-56 formulas** without explicit instruction — they are validated against scientific literature
- **Never touch the Gist write logic** without explicit instruction — silent data loss risk
- **Never commit secrets** — all credentials live in GitHub Actions secrets
- **Do not tune soil parameters** (FC, WP, Zr) — those are domain decisions, not code changes
- **Preserve the data.json schema** — add fields additively, never rename or remove existing ones
- **Frontend cache-bust** — always keep the `?t=${Date.now()}` query on JSON fetches
  (writer pages via the `bust()` helper from shared.js; read-only pages inline)
- **Times — default to Europe/Amsterdam local time.** Crons use GitHub Actions' native
  `timezone:` field so DST is handled automatically — UTC crons drifted across DST and
  caused real timing bugs, hence this policy (a few legacy crons, e.g. soil 06:00 and
  briefing 01:00, are still pinned in UTC; new ones should be local). In-code day/schedule
  logic uses `shared_const.TZ` (`local_today()`, `datetime.now(TZ)`). Only machine-readable
  artifact stamps (`generated_at`) stay UTC/ISO; display in Amsterdam on the frontend
- Python 3.11+, no build step for frontend
- `ruff check .` and `python -m pytest` must stay green (ruff config in `pyproject.toml`, pytest import-bootstrap in `conftest.py`; CI runs both on every push)
- **De pytest-suite is `tests/` en alleen `tests/`** (`testpaths` in `pyproject.toml`). De
  `tools/test_*.py`/`test_*.js`-scripts (`test_invariants.py`, `test_golden.js`) zijn handmatige
  diagnose-runners die je zelf aanroept, geen pytest-modules — ze mogen `requirements-tools.txt`
  (numpy/torch) importeren, wat CI bewust niet installeert. Nieuwe échte tests horen in `tests/`;
  een importfout in een verzameld bestand is een **collection**-error en die zet de hele run op
  exit 2, dus dan draait er geen enkele test meer (bit ons in aug 2026).
- Every runner script wraps `main` in `notify.run_guarded` — keep that when adding a pipeline

---

## Security

This repo is **public**. Anyone can read all code, workflow files, and run logs. Keep this in mind for every change.

- **Privacy — Priority 1 (see the banner at the top of this file for the full rule).**
  Never let the household's real address/precise location or travel/vacation plans and
  dates reach code, comments, commit messages, branch names, PR text, workflow logs,
  `docs/` dashboard output, or test fixtures — this repo, its history, and its Actions
  logs are permanently public. Don't sharpen the existing area-level "Utrecht Oost"
  mention into anything more precise, and never wire a real trip/date into the
  vacation-mode (Project 2) or camping (Project 15) features. When in doubt, don't
  write it — ask first.
- **Never add `pull_request` or `pull_request_target` triggers** to any workflow — these allow forks to trigger runs and can expose secrets. (Trade-off: `tests.yml` runs on `push` only, so a fork's PR gets no CI until its branch is pushed to this repo — acceptable for a public repo.)
- **Never log secrets** — no `echo $SECRET`, no debug steps that dump env vars, no error handlers that print environment
- **GITHUB_TOKEN permissions must be minimal** — workflows that only read code use `permissions: contents: read`; only workflows that commit/push use `contents: write`
- **No community actions without a pinned commit SHA** — `uses: some-action@v2` is not safe; use `uses: some-action@<full-sha>` for any action outside the `actions/` namespace
- **No untrusted expression interpolation in `run:` steps** — never put `${{ github.event.pull_request.title }}` or similar directly into shell commands; pass via `env:` and read from the environment instead
- **Secrets stay in GitHub Actions secrets** — never hardcode credentials, never commit `.env` files
