# Project 13: Ventilatie-tweeling (Digital Twin)

> Reference doc, read on demand — read it before changing this project's files. The always-loaded rules (privacy, ground rules, security) live in [`CLAUDE.md`](../CLAUDE.md); where the two differ, `CLAUDE.md` wins.

**Goal:** A self-calibrating grey-box *digital twin* of the house — the inverse of Project 6: there the model tells you which windows to open; here **you report which windows / vents / doors are open** and the twin **predicts each room's temperature**, **shows the error** against the real tado temps, and **learns its own parameters online** so it improves the longer it runs. Rebuild of the retired Projects 8 + 12 (aug 2026): twin 1's gevalideerde fysica woordelijk geport, het leer-vangnet-complex bewust weggelaten (zie "Learning regime"). **Telegram: only the operational anomaly nudge ("klopt de raamstand nog?", privé-chat) + the shared `run_guarded` crash alert — no advice messages.** `DRY_RUN=1` prints instead of sending.

## Files
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
  onzekerheidsband-lezer (`load_uncertainty`/`band_for`, gebruikt door P10).
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
  in the non-secret `GIST_ID` Gist — bewust zónder workflow-dispatch; incl. de airco-dropdown en de
  huis-brede pauze-toggle), plattegrond met stroompijlen, kamerkaarten, temperatuurgrafiek
  (**24u terug + 12u vooruit**, met sinds aug 2026 een **p10/p90-band** om de vooruitblik per
  kamer uit `docs/js/uncertainty.json` — hulpdatasets met een "_"-label, gefilterd uit
  legenda/tooltip; ontbreekt het bestand → kale lijn), leercurve, speeltuin (gedeelde
  `speeltuin.js`, met een eigen **3u terug + 12u vooruit**-scenariografiek).
- `docs/huis3d.html` + `docs/js/huis3d.js` — **het huis in 3D** (nov 2026): subpagina van
  vent.html (gelinkt in diens nav, bewust niet in de gedeelde navigatierij — het
  `model.html`-patroon). Draaibaar three.js-huis met deeltjesstromen die de netwerkdebieten
  van opening naar opening volgen; ramen/roosters/deuren klikbaar, verdiepingen uit elkaar
  te trekken, wanden glas↔massief, dak eraf. Zelfde token+artefact-gist-poort als vent.html,
  leest alleen `vent_data.json` en **schrijft niets** (elke wissel is een lokale wat-als).
  Geen tweede fysica-port: het laadt `speeltuin.js` voor `buildOpeningsJS`/`solveNetwork`
  (houd de `?v=` op beide pagina's gelijk — test bewaakt). De indeling in de broncode
  (`H3_DEFAULT_LAYOUT`) is **gestileerd en verzonnen** uit volumes/verdiepingen/gevelrichtingen
  — geen plattegrond op schaal, en dat moet zo blijven: een herkenbare plattegrond in een
  publieke repo is naast een woningadvertentie te leggen. **De echte indeling leeft als
  `huis3d_layout.json` in de privé artefact-gist** (bewoner-geschreven, de pagina leest 'm in
  dezelfde call als `vent_data.json`; bewust géén terugval op een pad onder `docs/`, en het
  bestand staat in `.gitignore`). Vorm (`h3Layout` valideert, ongeldig → de standaard):
  `zones.<id>` = `{x,z,y}`-paren in meters plus optionele `parts` (uitbouwen die aan de
  hoofddoos raken — een L-vormige kamer, of de begane-grond-overloop aan de trapkoker; een
  part mag een eigen `y` dragen; deeltjes lopen via de doorgang, niet dwars door de
  inspringende hoek), `extras` (ruimtes zónder luchtstroom: `solid` = dicht blok dat niet bij
  het huis hoort, anders een lege ruimte; elk met optioneel `label`) en `place.<element-id>`
  (`side` x0/x1/z0/z1/roof + `pos`) voor een opening die op de azimut-wand niet past; voor een
  binnendeur `axis` x/z + `pos` — welke van de gedeelde wanden, als twee ruimtes er meer dan
  één delen (zonder opgave de eerste), voor een dakraam `at` + `size` (een strook i.p.v. een vierkant) — en `stairs.<zone-id>` (looplijn vanaf de onderste trede:
  `start`, `heading`, `run`, `radius`, `turn`, `tail` + `landing`-vlakken; `closed` vult de
  hoeken buiten de buitenbocht en de ruimte onder de eerste trap — alleen beeld, de koker
  blijft voor de luchtstroom een doos) voor een draaiende
  trap met overlopen i.p.v. de rechte steektrappen. Een `solid`
  extra bóven een kamer laat het dak alleen op het onbedekte deel staan. Zet
  nooit waarden of labels uit dat bestand in code, tests, commits, `CLAUDE.md` of deze documentatie.
  **Beeldlaag (nov 2026):** de luchtstroom is een *lint* per deeltje (taps, naar de camera
  gedraaid, `h3Ribbons`); een **gloed**-nabewerking (`UnrealBloomPass`, zeven extra
  three-scripts met SRI) met labels/kompas op laag 1 er ná overheen getekend, anders gloeit
  de tekst mee; een **warmtewaas** (grof raster per kamer dat de stroom naar zijn eigen
  temperatuur trekt en langzaam terugzakt — puur beeld, de kamertemperaturen veranderen
  niet); en **camerabewegingen**: overzicht/bovenaanzicht, doorsnede per verdieping (de
  lagen erboven tillen weg — uit elkaar trekken en wegtillen lopen via dezelfde
  `h3.lvlOff`), naar een kamer vliegen en "volg de lucht" (de camera rijdt achter één
  deeltje aan). Additief mengen telt op: bij het bijstellen van helderheid altijd in de
  drukste stroom kijken (open raam + open deur), niet in een rustige kamer. Bovenop het
  netto debiet tekent de pagina twee uitwisselingen die alleen beeld zijn: eenzijdig door
  één open raam en tegenstroom door een open binnendeur. three.js r147 is de laatste reeks
  met een klassieke (niet-module) build + `examples/js/OrbitControls` — een nieuwere versie
  vraagt ES-modules, en een import-map is een inline script dat de CSP verbiedt.
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
  `--stratify-openings` (fout per raamstand-klasse op de oorsprong — de plek waar
  raamstand-scenario's op leunen) en `--summary-out` (kopcijfers appenden aan
  `docs/twin_eval.json`, het wekelijkse trendspoor).
- `tools/export_uncertainty.py` — empirische p10/p50/p90-band per (kamer, horizon-uur) uit een
  backtest-dump + het validatie-envelop voor de OOD-waarschuwing. **Niet per run** — het is een
  eigenschap van het model; wekelijks ververst door twin-eval.yml (stond daarvóór stil op een
  handmatige momentopname). Consumenten: de speeltuin, de band op de dashboard-
  temperatuurgrafiek (vent.js), de marge-regel in het nachtbericht.
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
  `data/twin2_history/` — kamer-temp/-vocht per kwartier is gedragsdata (zie de privacy-sectie in `CLAUDE.md`).
  Zelfde mechaniek als het openingen-archief: één schrijver (de kwartierloop), lokale dir als
  gitignorede terugval/overlay (`VENT_HISTORY_DIR` voor tests/tools), zelf-uitvoerende migratie
  (`vio.migrate_history_shards`: unie-merge → read-back-verificatie → lokale bestanden weg, de
  loop-commit publiceert de deletie). `vio.load_dataset` leest Gist ∪ lokale dir (lokaal wint
  per tijdstip — zo levert twin-eval's creds-loze ERA5-stap een in-job weer-overlay zonder
  tweede Gist-schrijver). De reeds gecommitte maanden mei–aug 2026 blijven in de publieke
  git-historie staan (zie [`privacy.md`](privacy.md): verwijderen kan alleen een history-squash).

## Per-run flow
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

## Vaste dagritmes op de vooruitblik (`routines`, aug 2026)
`house_model.json` draagt een additief `routines`-blok (element-id → `{state, from_h, to_h}`,
lokale klokuren, over-middernacht toegestaan) voor standen die níemand in de openingen-log
meldt maar die elke dag hetzelfde zijn — nu alleen het verduisteringsgordijn van de kinderkamer
(`nursery_window_shade` dicht 19–08, de fix die P10 al hardcodeerde: ~1 °C te warm om 07:00
zonder). `vio.apply_routines` dwingt ze af op de **forecast-tijdlijnen** (de 12u-vooruitblik
hier + beide fasen van de nachtvoorspelling); de laatst gemelde stand 12 uur
doortrekken was 's nachts elke nacht aantoonbaar fout. De **kalibratie op het verleden blijft
bewust op de gemelde log** rijden: de routine dáár ook toepassen verandert de fit-inputs en is
dus een te méten wijziging (re-seed + backtest, zie "Ground rules (Project 13)" onderaan), geen bijvangst.
Sinds de bewonersbevestiging (aug 2026) staat óók **`nursery_stair` dicht 19–08** in de config:
de deur is 's nachts vrijwel altijd dicht, met als zeldzame uitzondering een te warme kamer
(ruwweg >23°) bij koelere buitenlucht — precies de interventie die de stapel/all-open-
scenario's van P10 doorrekenen (scenario-overrides worden ná de routine gemerged en
winnen dus altijd). Bijbehorende regel: **een expliciete melding ín het lopende
routinevenster wint van de routine** (`apply_routines(..., log=log)`) — routines dekken wat
níemand meldt, maar op de avond dat de bewoner de deur wél openzet en dat meldt, mag de
routine het eigen rapport niet overschrijven (anders spreken dashboard en scenario-baseline
de gemelde stand tegen). Een melding van vóór het venster telt niet.

## Physics (samenvatting — do not casually retune the structure)
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

## Deur-topologie begane grond (nov 2026 — bewonersopgave, rechtgezet)
Tot nov 2026 stond de **gang** in het model als centrale ruimte waar woonkamer en badkamer op
uitkwamen, met een vaste open doorgang naar de trap. Zo zit het huis niet in elkaar:
- de **gang (`hall`)** is het portaal direct achter de voordeur. Ze heeft precies één
  binnendeur, de tussendeur naar het trappenhuis (`hall_stair`), en die staat vrijwel altijd
  **dicht** (default `dicht`, wél meldbaar);
- het **trappenhuis (`stair`)** is op de begane grond één open ruimte met de overloop, en
  dáár komen woonkamer (`living_hall`), badkamer (`hall_bath`), kinderkamer en de gang op
  uit. Zijn volume en `ground_m2` zijn daarop bijgesteld (schets-schatting, geen meting).

Wat er bewust NIET veranderde, en waarom:
- **De id's `living_hall`/`hall_bath` blijven.** Het zijn dezelfde fysieke deuren; de
  openingen-log in de Gist is erop gesleuteld en hun volgorde is het kolomcontract van het
  surrogaat. Alleen `between` + label zijn rechtgezet.
- **Het huis werd er niet lekker of dichter van.** Het oude model droeg de voordeur als één
  rest-lek van 0,005 m² "achter een altijd-dichte tussendeur". Dat zijn nu twee openingen in
  serie: `front_door_leak` (0,007, in de gang) en de **kier van de dichte tussendeur**
  (`closed_leak_m2` 0,007 op `hall_stair`) — samen weer 0,005 effectief; een test pint dat.
  `closed_leak_m2` is de enige nieuwe term: een dichte deur mét die opgave blijft een lekpad
  in het druknetwerk (op-vlag `crack`), maar telt nergens als *open* deur — niet voor de
  stratificatie-gradiënt, niet voor de Brown–Solvason-counterflow. Zonder de opgave (alle
  andere deuren) is dicht nog steeds luchtdicht. Gevolg voor `tools/test_invariants.py`:
  "dicht huis → exact nul" wordt getoetst op een kopie zónder kieren; het kier-residu
  (~0,08 ACH in de gang, een paar watt) staat er apart onder, begrensd.
- **Geen `PHYSICS_REV`-bump.** Een bump zet álle geleerde params terug naar de priors, en in
  november is er niets om opnieuw op te leren: gestookte kamers vallen uit de kalibratie, en
  een re-seed heeft de privé shards nodig. De sensorkamer-params (ua_env, c_mass, zon) hangen
  nauwelijks aan de deur-topologie; de online fit stuurt het restant per kwartier bij. Wie
  dit in het stookvrije seizoen wil nameten: `tools/horizon_backtest.py` met beide armen
  her-geseed, zoals de grondregel voorschrijft.
- Het surrogaat is opnieuw gedistilleerd (uitvoerkolommen = de nieuwe deurparen) en door
  `tools/surrogate_backtest.py` geaccepteerd (|surrogaat − solver| 0,04 °C gem.), en de
  golden-vector is herslagen. Omdat de echte shards privé zijn en de publieke historie
  gesquasht is, gebeurde dat op **`tools/synth_history.py`**: een deterministische week
  zomerweer + kamertemps + openingen-log zonder één gemeten waarde. De golden-test is een
  port-contract (JS == Python), dus synthetische invoer is daar volwaardig; als *replay*-pool
  voor de distillatie is ze armer dan de echte log (zie `airflow_distill.py`).
  `tests/test_vent_forecast.py` bewaakt dat golden + surrogaat dezelfde deurparen dragen als
  `house_model.json` — de kolomvolgorde-poort van `surrogate_runtime` ziet een gewijzigde
  `between` namelijk níet.
- De 2D-plattegrond (`plan_xy`) is meeverhuisd: trappenhuis in het midden, woonkamer links,
  kinderkamer/badkamer rechts, gang eronder.

## Vooruitblik (12u) — `vent_forecast.py`
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
0.62 °C totale spreiding) — bewust buiten scope, zie "Ground rules (Project 13)" onderaan. Het herankeren zelf is de grootste enkele winst: 1.12 → 0.70.
**Elke accuraatheid hier gaat uit van een perfecte weersvoorspelling** (de backtest speelt
hindcast-weer af); die fout is nog ongemeten, maar sinds aug 2026 **wordt de dataset om 'm te
meten verzameld**: het forecast-log (`data/forecast_log`, elke 3 klokuren een snapshot van de
échte Open-Meteo-voorspelling) + `horizon_backtest --weather forecast`, wekelijks gedraaid
door twin-eval.yml. Na ~4–6 weken accumulatie levert dat het eerste live-foutgetal.
**Stand nov 2026 (`docs/twin_eval.json`, 10 weken):** op de échte gelogde forecasts scoort de
tweeling 0.56–0.77 °C tegen persistentie 0.58–0.77 en wint in 5 van de 10 weken — op de 12u-
horizon is hij dus nog niet aantoonbaar beter dan "het blijft zoals het is". De hindcast-reeks
zelf loopt sinds aug 0.81–1.08 (niet 0.70; de herfst is lastiger dan de zomerset). Bekend
voorbehoud bij de backtest: hij ziet raammeldingen van ná de oorsprong en slaat de routines en
de om_bias-correctie uit productie over, dus hij is optimistischer dan de live-situatie.

## Bewijsstatus eenzijdige ventilatie (§6.2-verplichting — afgerond aug 2026)
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

## Learning regime
- Online damped Gauss-Newton + ridge naar de priors + Huber + recency (`vent_fit.calibrate`), één stap per kwartierrun.
- **Bewust afwezig:** checkpoint/auto-fallback, `backfill_rmse_history`/log-vingerafdrukken, batch-verankering en tarrering — elk groot incident in Projects 8/12 kwam uit dát vangnet-complex, niet uit de fysica. De seeding-tool + de rev-poort vervangen ze.
- **Anomalie-poort deadlock-proof** (`anomaly_step`): een log↔werkelijkheid-mismatch houdt het leren maximaal `ANOMALY_MAX_HOLD_H` (24u) vast, daarna hervat het leren met een `ANOMALY_REARM_H`-cooloff (de zelfvoedende hold die P12 bevroor kan niet terug); revisie-migratie → cooloff i.p.v. hold. Bij hold-start gaat een nudge naar de privé-chat (herhaald op cooldown), plus een "leren hervat"-variant bij escape; de handmatige huis-brede pauze nudget bewust níet (zelfgekozen).
- Leercurve-punten dragen additief `skill`, `rmse_naive` en `wx` (weer-samenvatting), zodat een RMSE-verschuiving toewijsbaar blijft.
- **Structurele kamer-uitsluiting (`exclude_from_fit`, aug 2026).** Naast de drie *tijdvenster*-filters (AC/verwarming/pauze) kan `house_model.json` een kamer permanent buiten de kalibratie zetten: `rooms.<id>.exclude_from_fit: true` → `vent_fit.filter_excluded_rooms` haalt haar vóór alle andere filters uit `actual`, dus uit de fit, de RMSE, `rmse_naive`/skill, de leercurve én de anomaliepoort. Nu: **`bath`** — douche + handbediende mechanische afzuiging zijn drijvers die de fysica niet kent en die géén melding kan repareren (de heat-vlag-filter ving er maar een deel van; douchen ≠ stoken), terwijl haar samples wél de gedeelde globalen meebepaalden. Ze wordt onverkort meegesimuleerd, getoond op haar kamerkaart en meegenomen in het druknetwerk; alleen haar params bevriezen op de priors/seed. `coupled_sensorless_zones` slaat zo'n kamer over — anders zou ze via de sensorloos-gekoppelde achterdeur alsnog meeleren. `tools/vent_seed.py` past hetzelfde filter toe, anders keurt zijn acceptatiepoort een RMSE over een andere kamerverzameling dan de runner rapporteert. `tools/horizon_backtest.py` doet dat bewust **niet**: die scoort *voorspellen*, en een niet-gefitte kamer blijft een geldige voorspeldoelstelling (het is juist de vergelijking die de bath-grondregel hieronder staaft).
  - **Gemeten bij invoering:** de leercurve stapt hierdoor ~+0,08 °C **omhoog**, niet omlaag — over acht 72u-vensters (1–5 aug 2026, offline replay) was bath met RMSE 0,28–0,71 °C juist de bést-gevolgde kamer van het huis (living/bedroom zaten op 1,4–1,5), en er stond geen enkel `held`-punt in de leercurve. De uitsluiting is dus een keuze over *wat er in het objectief hoort*, niet een reparatie van een slecht getal; punten van vóór en ná de omschakeling zijn niet vergelijkbaar.

## Wat de grafieken tonen (`hide_in_charts`, aug 2026)
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

## Wat er in de shards komt (`exclude_from_shards`, privacy-sweep aug 2026)
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

## Artefact schema (lean, additive only — never break existing fields)
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

## Relation to other projects
Leest `window_data.json` (Project 6, privé artefact-gist) + de openingen-Gist **read-only**; schrijft uitsluitend
eigen artefacten + de twin2-shards (privé Gist sinds de privacy-assessment aug 2026). **P9/P10 importeren `vent_physics`/`vent_io` read-only** met een
ctx-prologue van 3 regels (`vent_io.make_context` → `RunContext`); P11 leest `docs/vent_learned.json`.
Geen tado-auth, geen nieuwe secrets (WU-, privé-chat-Telegram- en Gist-secrets hergebruikt).
`house_model.json`: de twin-2-only velden `subzones` en per-element `exposure` zijn inert;
`front_azimuth_deg` is verwijderd (aug 2026 — dead sinds het pensioen van Project 12, geen enkele consument meer).

## Ground rules (Project 13)
- **A `PHYSICS_REV` bump needs a re-seed, and a fysica-wijziging meet je alleen met béíde armen
  her-geseed** (`tools/vent_seed.py` + `tools/horizon_backtest.py`). De geleerde params
  absorberen een fysische fout; de correctie erbovenop toepassen telt 'm dubbel — dan meet je de
  parameter-reset i.p.v. de fysica. Zie AIRFLOW3_ASSESSMENT.md §2.
- **Never re-report the twin's nowcast RMSE as a forecast score** — `vent_learned.json`'s ~0.5 °C
  is een nowcast over een venster dat elk kwartier op verse metingen wordt gezet. De
  voorspelscore is `tools/horizon_backtest.py` (wekelijks in `docs/twin_eval.json`; zie
  "Gemeten" voor de live stand — de oude 0.70 °C was een zomer-hindcast).
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

### Doorlichting nov 2026
- **Stdout is nu echt vormvast.** De regel "N samples over K kamers", de RMSE-regel, de aparte regel voor een venster zonder samples en de byte-telling van `vent_data.json` hingen allemaal af van `actual` ná de pauze-/airco-/verwarmingsfilters: het sample-aantal zakte per kwartier zodra een pauze inging, het kameraantal was "alle min de airco-/gestookte kamers". Eén regel `[leren] kalibratiestap afgerond.` voor elke uitkomst; `tests/test_vent_twin.py` draait `main()` met en zonder pauze/airco en vergelijkt de logs.
- **`load_learned` is strict**: een léésfout op de artefact-gist breekt de iteratie af i.p.v. de params naar de priors te zetten en leercurve + anomalie-state te wissen (en de nachtvoorspelling op priors te laten rekenen).
- **`vent-notify.yml`** staget alleen nog `data/forecast_log`.
- **Open — te méten, niet aangenomen:** `calibrate` geeft `measured=` (de γ-waarneming) wél door aan de eerste residuen maar niet aan de Jacobiaan-kolommen, de proefstap en de eind-RMSE; de fit mengt daardoor twee modelvarianten. Rechtzetten verandert het fit-traject en hoort dus met een re-seed + `tools/horizon_backtest.py` (beide armen), niet als bijvangst.
- **Open — tools:** `tools/vent_diagnostics.py` leest nog de lokale `docs/vent_*.json` (nu gist-only) en gescrubde velden; `tools/horizon_backtest.py` past `om_learned` en de routines niet toe en scoort dus niet exact de productie-vooruitblik; `tools/export_uncertainty.py` zet `heating_season_observed` hard op False terwijl het record inmiddels november bereikt; `tools/airflow_distill.py` bemonstert de stand `"half"`, die geen openingsstand is (fractie 0).
