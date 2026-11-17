# Shared modules, secrets and variables

> Reference doc, read on demand — read it before changing a shared module or a workflow's secrets. The always-loaded rules (privacy, ground rules, security) live in [`CLAUDE.md`](../CLAUDE.md); where the two differ, `CLAUDE.md` wins.

## Pipeline overview

This repo contains fourteen independent automation pipelines (P1–P7, P9–P11, P13, P15–P17 — the numbering keeps historical gaps: Projects 8 and 12 were replaced by Project 13 in aug 2026, Project 14 (koelplan) is retired sep 2026), all running on GitHub Actions (most notify via Telegram; Project 7's Telegram is optional, Project 13 sends only an operational anomaly nudge — no advice messages, **Project 15 is dashboard-only** — geen Telegram-advies, alleen de crash-alert, and **Project 16 meldt uitsluitend privé** — start/stop/afwijkingen naar de privé-chat, nooit de groep, and **Project 17 (potje)** stuurt alleen plas-herinneringen naar de groep vanuit een eigen 5-minutenloop). They share Telegram/WU/Gist secrets and a few **deliberate read-only** data hand-offs (Project 5 reads Project 1's `data.json`; Project 13 reads Project 6's `window_data.json`; Projects 9/10 reuse Project 13's pure modules (`vent_physics`/`vent_io`, P10 also `vent_forecast`) read-only; Project 11 aggregates the published artefacts of 1/5/7/13; Project 16 reads Project 1's `data.json` and is the only *second writer* of the irrigations-Gist), but are otherwise separate. The daily jobs are fired at their local target time by the **Timing Orchestrator** (`.github/workflows/orchestrator.yml`, a self-driven 15-min klok-loop); each project keeps a ~30–60 min later fallback cron + a dedup guard-job. **Projects 1, 5 en 16 draaien uurlijks** (dedup-venster = het lopende klokuur i.p.v. de dag; 1 en 5 sinds aug 2026) zodat hun dashboards met de dag meebewegen; hun *berichten* schalen niet mee — die vallen op één moment per dag, beslist door het script zelf (zie "Meldmoment" bij Project 1).

## Shared modules

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
  `PHYSICS_REV`-bump: zie Project 13. (De seed-tool `tools/om_bias_backfill.py` is in nov 2026 verwijderd: hij herspeelde de git-historie van `docs/window_data.json`, die sinds de privatisering niet meer bestaat, en zou bij een run het levende leerboek overschrijven.)
- **`notify.py`** — shared Telegram sender (`send_telegram`, transient-failure retry, never raises) plus
  `sanitize_error(e)`: secret-safe exception rendering (scrubs `apiKey=`/token query params, Telegram
  bot tokens and Gist-IDs out of URLs in exception text). **Ook de thuisbasis van de
  stille modus (aug 2026):** `notify_prefs.json` in de `GIST_ID`-gist — geschreven door
  uitsluitend de browser (toggle "🔕 Meldingen" in de vent-meldmodal, token-gated):
  `{"quiet": bool, "since": ISO, "cleared_at": ISO}`. Adviesberichten geven per call site
  `muted_in_quiet=True` mee (weerbericht, zandbak, maai-, bodem-, raam-advies + dagplan +
  urgente sluitingen, zonwering, nachtvoorspelling, tweeling-nudges,
  verwarmingsexperiment, potje-herinneringen); bij actieve stilte wordt niet verstuurd maar is het gedrag voor
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
  `fail_threshold=2`, paired with their workflow's one in-job retry after 10 min (soil check + weerbriefing: 25 min, nov 2026 —
  Open-Meteo viel rond het hele uur ~17 min stil, een herkansing na 10 min landde nog in dat venster) — a single API blip
  retries silently; only a persistent outage pages. (`verwarming` calls no API and keeps default 1.)
  **Rate limit ≠ crash (nov 2026):** with `hand_off=True` an exception carrying `retry_elsewhere`
  (`http_util.RateLimited`, or a fetch whose attempts *all* timed out / lost the connection) exits `RATE_LIMITED_EXIT` (75) with a `::warning::`, no alert and the crash counter untouched, and
  drops the marker `$RUNNER_TEMP/open_meteo_rate_limited`. Open-Meteo's free tier limits per IP and
  GitHub runners share their outbound IPs: measured 15 nov 2026, one runner got 429 on every attempt
  and again after the 25-min in-job wait, while runs on other runners in the same hour succeeded;
  the window loop (one runner for ~5h) failed six quarters in a row. So waiting on the same runner is
  pointless — instead `daily-check.yml`/`weather-briefing.yml` skip their in-job retry on exit 75 and
  end red (the orchestrator re-dispatches on a fresh runner within ~15 min), and the window/vent
  loops `break` on the marker (the pending restart kick takes over on a fresh runner). Trade-off: a
  rate limit that follows every runner never pages; it shows as red/short runs and stale dashboards.
  The timeouts got the same treatment on 17 nov 2026: from 13 nov the soil check's :00 run timed out
  on all 5 attempts and often again after the 25-min wait on that runner, while the orchestrator's
  re-dispatch at :45 on a fresh runner answered in seconds (and a 429 at 14:00 on 16 nov carried
  "Daily API request limit exceeded", confirming the shared-IP limit). `hand_off` is opt-in: the
  orchestrator-dispatched one-shots (soil, briefing, maaien, zandbak, zonwering, nacht, kampeer) and
  the window/vent loops pass it; jobs without a re-dispatch (station-accuracy, weekjournaal) don't,
  so a failure there still alerts instead of silently skipping a monthly/weekly run.
- **`gist_io.py`** — shared **read-only** Gist helpers (`read_file` raises, `read_json` is
  graceful, `read_files` haalt alle bestanden in één call). Volgt bij de ~1 MB-truncation
  van de Gist-API de `raw_url` i.p.v. stilletjes een halve JSON terug te geven.
  Gist-schrijf*semantiek* (wat/wanneer) stays per-project (see the `CLAUDE.md` ground rule on Gist write
  logic; de schrijvers zijn expliciet: window_advisor's token-persist + state,
  `artefact_io.write_json_str`, en het openingen-archief van de vent-action in
  `vent_io._gist_write_files`). Sinds sept 2026 lopen die alle drie voor het *transport*
  via `gist_io.write_files`: één PATCH-helper met een korte, begrensde **retry op 409
  Conflict** (`WRITE_RETRY_DELAYS`). De artefact-gist heeft vier schrijvers op eigen
  cadans (raam-adviseur + tweeling elk kwartier, bodem + maai elk uur) en binnen één run
  gaan PATCHes vlak na elkaar; twee die elkaar raken geven een 409 uit Gist's git-backend.
  Dat crashte een iteratie zonder retry (raam-adviseur 6× op rij, maai-adviseur 2×). De
  PATCH is idempotent, dus opnieuw proberen is veilig; een 409 dat blijft, faalt alsnog.
- **`artefact_io.py`** — de privé artefact-gist (`ARTEFACT_GIST_ID`) voor `data.json`,
  `mowing_data.json`, `mowing_state.json`, `window_data.json` en de drie vent-artefacten
  (privatisering aug 2026, uitgebreid door de privacy-sweep): secret gezet → lees/schrijf via de
  Gist-API en geen lokaal bestand meer; secret afwezig → het oude lokale pad
  (zelf-activerende migratie, tevens het test-/bootstrap-pad). Eén schrijver per
  bestand: data.json ← check_and_notify, mowing_data.json + mowing_state.json ←
  mowing_advisor, window_data.json ← window_advisor, de drie vent-artefacten ← vent_twin;
  lezers: mowing_advisor, gardena_control, weekjournaal, vent_io (`load_window_data`/
  `load_learned`, dus ook P10) + de dashboards client-side.
- **`http_util.py`** — `get_json(url, params, timeout=, label=)`: the one GET→JSON transport with
  retry/backoff (5 attempts, 3+8+30+60s — a ~100s window that rides out short TLS-reset/timeout
  bursts) and sanitized error logs, used by all six Open-Meteo fetch sites. HTTP 429 has its own path:
  Open-Meteo's `reason` is logged; a *minutely* limit waits `RATE_LIMIT_MINUTE_WAIT` (65 s) and retries,
  any other limit (hourly/daily/unknown) raises `RateLimited` (an `HTTPError` subclass) at once. When
  every attempt was a `Timeout`/`ConnectionError`, the last exception is re-raised unchanged but tagged
  `retry_elsewhere = True` — see
  `run_guarded` above for what the runners do with it.
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

# Shared secrets (GitHub Actions)
- `WU_STATION_ID`, `WU_API_KEY` — Weather Underground (soil project + window advisor)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — soil, sandbox, heating, mowing + window advisor (raam-advies + dagplan + operational alerts, privé-chat) + vent twin (Project 13: anomalie-nudge + crash-alert, privé-chat)
- `TELEGRAM_CHAT_GROUP_ID` — weather briefing + night forecast + de potje-herinneringen (Project 17) (group chat)
- `WU_NEIGHBOUR_IDS` — komma-gescheiden buur-PWS-id's voor de coherentie-toets (Project 7, route A); locatiegegevens, dus nooit in de repo
- `GIST_ID`, `GIST_TOKEN` — soil project (irrigation log) + mowing advisor (mow log, same Gist) + vent twin (Project 13: opening log `house_openings.json` read-only from Python, plus het action-geschreven openingen-archief `house_openings_<YYYY-MM>.json` én — sinds de privacy-assessment aug 2026 — de twin2-maand-shards `twin2_history_<YYYY-MM>.json`, action-geschreven, read-only voor twin-eval/ml-dataset/tools) + de stille modus (`notify_prefs.json`, browser-geschreven, door álle melders read-only gelezen) + bewatering-automaat (Project 16: `gardena_config.json`, `garden_automation.json`, `gardena_state.json`, de sensor-shards `gardena_history_<YYYY-MM>.json` + tweede schrijver van `irrigations.json`, same Gist) + zindelijkheidstraining (Project 17: `potty_log.json` browser-geschreven, `potty_state.json` action-geschreven); `GIST_TOKEN` also used by the window advisor
- `GARDENA_APP_KEY`, `GARDENA_APP_SECRET` — Husqvarna Developer Portal-applicatie (Project 16); key = OAuth client_id = X-Api-Key, secret = client_secret
- `ARTEFACT_GIST_ID` — de privé artefact-gist voor `data.json`/`mowing_data.json` (privatisering aug 2026, zie `artefact_io.py`), sinds de tweede ronde ook `vent_data.json`/`vent_forecast.json`/`vent_learned.json` (Project 13 — het dashboard zélf is nu token+artefact-gist-gated) en sinds de privacy-sweep óók `window_data.json` (Project 6, met `window.html`/`grafiek.html` gegated) en `mowing_state.json` (Project 5), plus het on-demand rapport `gardena_sensor_eval.txt/.json` (Project 16, geschreven door `gardena-sensor-eval.yml`); auth via het bestaande `GIST_TOKEN`. Zolang het secret niet bestaat draait alles in de lokale-bestand-terugval
- `TADO_GIST_ID` — **separate secret Gist** for the window advisor: rotating tado refresh token (`tado_token.json`) + per-room advice state, meldgeheugen en dagbudget (`window_state.json`)
- `BRIEFING_BLOCKS` — optioneel, JSON met de tijdblokken van de weerbriefing (Project 2). Privacy-grens uit de privacy-sweep (aug 2026): een weekrooster van vertrek-/opvang-/thuiskomst-/sportvensters is een "wanneer is het huis leeg"-kalender en hoort niet in een publieke repo. Afwezig → generieke dagdelen.
- `TADO_ZONE_ALIASES` — optioneel, JSON `{gepubliceerde kamernaam: tado-zonenaam}` (bv. `{"Nursery": "<naam in de tado-app>"}`). Privacy-grens uit de pseudonimisering van aug 2026: de repo + Pages-artefacten zijn publiek, de tado-app niet — een persoonsnaam als zonenaam hoort hooguit in dit secret. Afwezig → zonenamen moeten letterlijk aan `ROOMS` voldoen.
- `GITHUB_TOKEN` — automatic, sandbox project

# Variables
- `DASHBOARD_URL`

## Doorlichting nov 2026 — wat er in de gedeelde laag veranderde
- **`gist_io`**: een GET herkanst kort op transiënte fouten (`READ_RETRY_DELAYS`, zonder logregel — de vormvaste loops mogen er niet door verschuiven). `read_json(..., strict=True)` en `artefact_io.read_json(..., strict=True)` laten een **léésfout** raisen in plaats van `default` terug te geven; een ontbrekend bestand blijft `default`. Gebruik `strict` voor elke read die de basis is van wat de run daarna schrijft (maandtotalen, kamerhistorie + om_bias-leerboek, geleerde tweeling-params, meldgeheugen, logboeken): "kon niet lezen" mag daar nooit als "leeg" doorgaan. `read_files(names=...)` beperkt het resultaat (en de raw-URL-volgers) tot de gevraagde bestanden.
- **`artefact_io.read_many`**: meerdere artefacten in één Gist-call.
- **`artefact_io` migratie + maand-shards (security-scan nov 2026):** `read_json_migrating`
  (gist-modus strict; valt alleen bij een ontbrékend gist-bestand terug op de nog gecommitte
  kopie) + `write_state` (paar pogingen, daarna `retire_local`) voor `soil_state.json` en
  `shade_state.json`; `load_shard`/`save_shards`/`load_all_shards`/`migrate_shards` voor
  `station_history_<YYYY-MM>.json` en `night_forecast_log_<YYYY-MM>.json`. De migratie
  verifieert met een read-back vóór ze lokale bestanden verwijdert; de workflow commit die
  verwijdering, daarna is de commit-stap een no-op.
- **`om_bias.night_weight`**: de inloop bij het nachtbegin werkte niet (gewicht sprong op 22:00 van 0 naar 0,5 — precies de sprong die `TRANSITION_H` moest voorkomen); nu symmetrisch met de uitloop. Raakt de driver van de tweeling op hooguit twee kwartierstappen per dag; geen `PHYSICS_REV`-bump.
- **`notify.sanitize_error`** poetst ook de raw-URL (`gist.githubusercontent.com/<gebruiker>/<id>/…`) die `gist_io` volgt voor een afgekapt bestand.
- **Publieke stdout**: de bodemcheck, de maai-adviseur en de tweeling loggen nu vormvast (geen prioriteit, slot-/verzendregel, byte-telling, sample-/kameraantal of RMSE); de raam-adviseur en de tweeling printen geen ruwe stationswaarden meer. Elk van die regels dateerde een handeling of verklapte huisboekhouding. Nieuwe melders volgen dit patroon; debuggen kan met een `DRY_RUN`-dispatch.
