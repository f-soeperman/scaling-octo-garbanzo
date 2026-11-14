# Project 17: Potje (zindelijkheidstraining)

> Reference doc, read on demand — read it before changing this project's files. The always-loaded rules (privacy, ground rules, security) live in [`CLAUDE.md`](../CLAUDE.md); where the two differ, `CLAUDE.md` wins.

**Goal:** Plas- en poepmomenten van de peuter met één tik registreren (tabel plassen/poepen × wc/potje/ongelukje/geprobeerd), een analysedashboard eronder, en een Telegram-herinnering in de **groep** zodra het tijd is om te laten proberen.

## Files
- `docs/potje.html` + `docs/js/potje.js` — registratie + analyse, **alleen met gekoppeld account** (GIST_ID + token; zonder koppeling alleen een privé-melding). Schrijft `potty_log.json` met een verse read vlak vóór de PATCH (twee telefoons tegelijk). Bewust géén workflow-dispatch bij opslaan (zie de privacyregel bij Project 1's modal).
- `potty_reminder.py` — de herinneringsrunner (zuivere beslisfuncties + `run`), `run_guarded` met `fail_threshold=6`.
- `.github/workflows/potty-reminder.yml` — self-driven loop, 60 iteraties op de 5-minutengrens (~5u), cron-kicks `2,22,42` als vangnet, concurrency `potty-reminder`, `contents: read` + `actions: write`, checkout gepind op de branch-tip. Commit niets. **Dispatcht aan het eind zelf zijn opvolger** (okt 2026, alleen op main en niet bij een dry-run): GitHub liet overdag cron-kicks tot ~2,5u vallen, en in zo'n gat ging geen herinnering uit. De opvolger wacht in de concurrency-groep en neemt direct over.

## Gist-bestanden (in de `GIST_ID`-Gist) — één schrijver per bestand
- `potty_log.json` — schrijver: de browser. `{"events": [{"id", "t": ISO met offset, "kind": "plas|poep", "where": "wc|potje|ongeluk|geprobeerd"}]}`.
- `potty_state.json` — schrijver: de action. `{"reminders": [{"t", "anchor": event-id, "kind": "plas|poging|herhaal", "msg_id"?, "text"?, "acked"?}]}` (afgekapt op `MAX_REMINDER_LOG`; `text` alleen zolang het bericht van vandaag nog niet is afgevinkt); het dashboard leest 'm voor "helpt de herinnering?".

## Herinneringsregels (bewonersbesluiten okt 2026 — do not casually retune)
- Anker = de laatste **plas**-registratie van vandaag (lokale datum). Echt plasje (wc/potje/ongelukje) → herinnering na `INTERVAL_PEE_MIN` **120** (2u; was 90, daarna kort 105 in okt 2026); "geprobeerd" → na `INTERVAL_TRY_MIN` **30**; daarna precies **één** herhaling `INTERVAL_REPEAT_MIN` 30 min na een onbeantwoorde herinnering. Poep telt niet mee.
- Alleen in `[DAY_START_H 07:00, DAY_END_H 19:00)`. Alleen registraties van vándaag tellen, dus de eerste herinnering van de ochtend komt pas na de eerste registratie. Een moment dat in de nacht viel gaat om 07:00 uit als het niet meer dan `STALE_MIN` 60 te laat is; anders vervalt het stil (ook na loop-uitval).
- State wordt vóór het bericht geschreven: een kapotte Gist-schrijf mag niet elke 5 minuten hetzelfde bericht opleveren.
- **Afvinken i.p.v. een extra bericht (okt 2026):** komt er ná een herinnering een plasregistratie binnen (elke uitkomst, óók "geprobeerd"; poep niet), dan bewerkt de loop dat groepsbericht (`notify.edit_telegram` → `editMessageText`, geeft geen nieuwe notificatie): "✅" ervoor + "Geregistreerd om HH:MM (waar)". Een herhaling en de herinnering ervóór vinken samen af. Alleen berichten van vandaag; een edit die op netwerk/429/5xx strandt probeert de volgende iteratie opnieuw, een niet-meer-bewerkbaar bericht telt als klaar. De `message_id` komt uit `notify.send_telegram_message` en wordt ná het versturen in een tweede state-schrijf vastgelegd (mislukt die, dan krijgt alleen dat bericht geen vinkje); in de stille modus is er geen id en dus niets af te vinken. Het afvinkpad raist en print nooit.
- `docs/js/potje.js` spiegelt de constanten voor de tegel "volgende herinnering"; `tests/test_potty_reminder.py` bewaakt dat ze gelijk blijven.

## Analyse (client-side, periode 7/14/30 dagen)
Elke analyse beantwoordt een beslissing: gaat het vooruit / kunnen we afbouwen, wanneer extra opletten, klopt het interval, en ligt een ongelukje aan het interval of aan het opvolgen. Bewonersbesluiten okt 2026 (`docs/js/potje.js`, constanten bovenin):
- **Een dag telt pas mee met ≥ `MIN_PEES_PER_DAY` (3) echte plasjes** — oppasdagen worden niet bijgehouden en gaven anders een "droge dag" met één plasje of een schijnbaar urenlange droge pauze. Geldt voor álles behalve "vandaag" (tijdlijn, droog vandaag, plassen per dag): droog-/zelf-%-tegels en hun vergelijking, droge reeks (een niet-tellende dag breekt hem niet), trend, tijdstip, ritme, ongelukjes-split.
- **Zelf aangegeven** — een extra vlag `self: true` op een registratie (knop 🙋 onder de tabel, bij elke uitkomst; de herinneringsloop negeert het veld). Tegel, gestippelde tweede lijn in de trendgrafiek, ring om de stip op de tijdlijn.
- **Trend + afbouwsignaal** — droog-% en zelf-% per tellende dag + gemiddelde over de laatste 3 tellende dagen. Afbouwsignaal over de laatste `TAPER_DAYS` (7) tellende dagen: ≥90 % droog én ≥50 % zelf → voorstel interval +15 min; anders staat er wat ontbreekt. Het interval zelf blijft `INTERVAL_PEE_MIN` in `potty_reminder.py` (handmatig aanpassen).
- **Tijdstip** — per blok van 2 uur het *aandeel* ongelukjes (niet het aantal); blokken met < 3 plasjes vaag en niet in de conclusie.
- **Ritme** — Kaplan-Meier "kans dat hij na X min nog droog is": een ongelukje is de gebeurtenis, een gelukt plasje is gecensureerd (hij werd erop gezet, dus het zegt niet hoe lang hij het volhoudt). Curve stopt waar < 3 tussenpozen in beeld zijn; advies = interval waarbij hij in `TARGET_DRY` (90 %) droog blijft, afgerond op 15 min.
- **Ongelukjes vóór/ná de herinnering** — vóór = interval te lang, ná = herinnering niet (op tijd) opgevolgd, plus eerste-van-de-dag apart.
- Verder: reactie op herinneringen (binnen 30 min) en een poep-overzicht. Categoriekleuren zijn met de dataviz-validator geijkt op `#f3ecd9`.

## Privacy
Een plas-/poeplogboek met tijdstempels is gedragsdata (dagritme, en een dag zonder registraties leest als afwezigheid). Daarom: logboek + herinneringslog alleen in de privé Gist, nooit in git of `docs/`; de loop draait constant, ook 's nachts; de stdout is **vormvast** (`potje: controle klaar`, de `[telegram] ✓ verzonden`-regel wordt onderdrukt, het gardena-patroon), en een schrijffout ná een sendbeslissing gaat als privé-alert weg i.p.v. als FATAL in het publieke log. `DRY_RUN=1` schrijft niets en stuurt een eventuele herinnering met `[dry-run]` naar de privé-chat. Berichten noemen geen naam. Muted in de stille modus.

## Relation to other projects
Volledig onafhankelijk. Hergebruikt `GIST_ID`/`GIST_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_GROUP_ID` (herinnering) en `TELEGRAM_CHAT_ID` (alerts). Geen nieuwe secrets.
