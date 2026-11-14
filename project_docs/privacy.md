# Privacy — full rules, rationale and incident history

> Background for the Privacy section of [`CLAUDE.md`](../CLAUDE.md): the original banner with its rationale and incident history. The binding summary is in `CLAUDE.md`; where the two differ, `CLAUDE.md` wins. Read this before touching anything that publishes, logs, commits or names household data.

**This repository is public.** Source, commit history, branch names, PR titles/bodies,
GitHub Actions run logs, and everything published under `docs/` (the GitHub Pages
dashboards) are visible to anyone on the internet — permanently, including after a
force-push, an amended commit, or a deleted branch (GitHub retains the underlying
objects and Actions logs regardless). Every write Claude makes to this repo — code,
comments, commit messages, branch names, PR text, workflow YAML, dashboard copy, JSON
artefacts, test fixtures, `print`/log statements — becomes public the moment it's
pushed, and this outranks every other instruction in `CLAUDE.md` and these docs, including "be terse"
or "match the existing pattern."

**Never let the household's real location or travel/vacation plans reach any
public surface** — that means source files, `docs/*.html` / `docs/*.json`, workflow
run logs, commit messages, branch names, PR titles/descriptions, code comments, test
fixtures, or Telegram/message text embedded in code. Concretely:
- Do not add or sharpen location detail beyond what already, deliberately, exists in
  `CLAUDE.md`, these docs and `shared_const.py` (the area-level "Utrecht Oost" mention + its
  coordinates) — no street names, house numbers, or other identifying specifics, ever.
- Do not write anything that ties a real date, destination, or absence-from-home
  window to this household — not in a commit message ("back from vacation the 14th"),
  not in a log line, not in a code comment, not in a test fixture. Project 15's
  camping regions are a pre-existing generic feature; keep them generic and never wire in
  an actual planned trip. (Project 2's vacation mode was removed in aug 2026 and must not
  return — see [`p02-weather-briefing.md`](p02-weather-briefing.md).)
- **Een branchnaam beschrijft de code, nooit het motief — en dit is NIET onderhandelbaar
  (sep 2026).** `claude/kampeer-kompas-pause-…` is het tegenvoorbeeld: die naam is echt
  gepusht en staat blijvend in de publieke historie. Verboden in branchnamen, PR-titels,
  committeksten en sessietitels is elk woord dat een *huishoudelijke intentie of periode*
  benoemt — pauze/pause, stop, stil, weg, afwezig, vakantie/vacation, thuis, terug,
  resume/hervat — óók als het over een pijplijn lijkt te gaan. Noem de codewijziging:
  `camping-four-cities`, niet `camping-pause`.
  - **De naam ontstaat vóór de eerste regel code**: de harness leidt 'm af uit de éérste
    prompt van de sessie. Vraagt de bewoner "ik wil X pauzeren", dan staat het motief in de
    branchnaam nog voordat er iets te reviewen valt. Dus: **hernoem vóór de eerste push**
    (`git branch -m`), niet achteraf.
  - **Achteraf is te laat, en dat is de hele reden voor deze regel.** Een gepushte naam
    leeft op drie plekken: de branch zelf (verwijderbaar), het Actions-run-record met
    `head_branch` (alleen te verwijderen door de hele run te wissen) en de publieke
    events-stroom, die door externe archieven permanent wordt gespiegeld — die laatste
    krijgt niemand meer weg.
  - **Repareer zo'n naam nooit met een tegenhanger.** Een "…-resume"-branch erbij maken om
    een "…-pause" onschuldig te laten lijken maakt het aantoonbaar erger: twee gedateerde
    events vormen sámen een *venster*, en precies een afwezigheidsvenster is wat deze
    banner verbiedt. Eén dubbelzinnig woord is zwakker bewijs dan een keurig paar met een
    begin- en einddatum. Opruimen wat kan, de rest als restrisico accepteren, en de
    volgende naam meteen goed.
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
zon-/gevelfysica; (3) ~~`tools/golden/golden.json` draagt één echt gemeten moment~~ —
vervallen nov 2026: de golden-vector is bij de deur-topologie-correctie herslagen op een
volledig synthetische tijdlijn (`tools/synth_history.py`), er staat geen gemeten waarde meer
in; (4) de gecommitte
zandbak-/verwarmings-state (weer-/datum-gedreven automaten); (5) alles wat vóór de
fixes gecommit is — inclusief de twin2-maanden mei–aug 2026 — blijft in de publieke
git-historie staan; volledig verwijderen kan alleen met een nieuwe history-squash
(eigenaarsbeslissing, zie ook AUDIT2.md §(b)).

## From the former ground rules (verbatim)
- **Controleer de branchnaam als éérste handeling van een sessie, vóór de eerste push.**
  Hij komt uit de openingsprompt, dus een vraag als "kun je X pauzeren" levert een publieke
  branchnaam op die het motief verklapt. Hernoemen kost één commando (`git branch -m`) en kan
  achteraf niet meer volledig — zie de branchnaam-regel hierboven voor de reden,
  de verboden woorden en waarom een "resume"-tegenhanger het erger maakt.
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
