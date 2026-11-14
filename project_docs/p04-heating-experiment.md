# Project 4: Verwarmingsexperiment (Heating Experiment Notifier)

> Reference doc, read on demand — read it before changing this project's files. The always-loaded rules (privacy, ground rules, security) live in [`CLAUDE.md`](../CLAUDE.md); where the two differ, `CLAUDE.md` wins.

**Goal:** One Telegram message every Monday evening naming the **night-setpoint arm** for the coming week, so a paired-week A/B experiment runs itself. De vraag (bewonersbesluit okt 2026): **wat kost het om het huis 's nachts warm te houden, vergeleken met laten afkoelen?** — zodat die prijs tegen het comfort afgewogen kan worden.

## Files
- `heating_experiment_notify.py` — weekly arm picker + experiment log + Telegram
- `heating_experiment_state.json` — the arm log (committed by the action), like `sandbox_state.json`
- `.github/workflows/heating-temp-notify.yml` — orchestrator target maandag 21:00 + fallback cron ma 21:40 + guard-job; `contents: write` (commits the log); **filename deliberately kept** (orchestrator dispatch target, guard's `gh run list --workflow` key, run history)

## Geschiedenis — waarom het nachtsetpoint tóch gemeten wordt
- **Aug 2026** verving een wekelijks ochtend-opstookexperiment (`morning_recovery`: `early` = tado early start aan vs `hard` = harde start 06:00, nachtsetpoint vast 16 °C) de dagelijkse willekeurige setpoint-suggestie. De keuze rustte op een rekensom die van buiten de repo kwam en **nooit is nagemeten**: UA 163 W/K, "lager dan 16 °C bindt nooit", ~€32 per graad warmer per seizoen (150 nachten × 8 u, 92% ketelrendement, €1,45/m³) → "warm houden is per definitie duurder, niet het meten waard".
- **Okt 2026** bleek dat de eigenlijke vraag de *prijs* van warm houden is, niet de richting. De richting staat fysisch vrijwel vast; de prijs niet. De rekensom hierboven is daarmee een **hypothese die dit experiment toetst**, geen uitkomst. `morning_recovery` liep W41–W44 (5–31 okt 2026) zonder gasmeting; die weekregels blijven getagd in het logboek staan.
- Het ochtend-opstookeffect (condenserende ketel, enkele procenten) zit nu ín de `afkoelen`-arm en is niet meer apart meetbaar. Pas weer oppakken als `afkoelen` de winnaar blijkt — dan pas is "hoe warm je op" de volgende vraag.

## Design (do not casually change — dit is de experimentopzet)
- **Twee armen:** `afkoelen` (nachtsetpoint 16 °C — het huis kwam daar in de praktijk nooit onder, dus het koelt vrij af) en `warm` (nachtsetpoint 19 °C). Setpoints staan in `ARMS`.
- **Early start staat in béíde armen aan.** Het verschil meet dan precies "afkoelen + weer opwarmen" tegen "warm houden", inclusief een eventueel minder zuinige ochtendopwarming, en verder niets. Twee factoren tegelijk variëren (2×2) is bewust afgewezen: te weinig weken per cel in één winter.
- **Wekelijks alterneren, nooit in blokken.** Twee maandblokken verschillen per *seizoen* i.p.v. per instelling (januari is kouder dan november → de arm die daar valt lijkt slechter om de verkeerde reden). Wekelijks zien beide armen hetzelfde weerbereik.
- **Armkeuze is puur datum-afgeleid:** pariteit van `monday.toordinal() // 7`, zo gefaseerd dat de eerste week (`EXPERIMENT_START`, maandag 2 nov 2026) `afkoelen` is — de stand van daarvóór, dus zonder omschakeling. Bewust **niet** het ISO-weeknummer — een jaar met 53 weken geeft daar twee gelijke armen op de jaargrens. Gevolg: een gemiste maandag, een dubbele dispatch of de zomerstop kan de alternatie niet uit de pas laten lopen, en de state is puur logboek, geen besturing. Een dispatch in een week vóór `EXPERIMENT_START` doet niets (anders overschrijft hij een `morning_recovery`-weekregel).
- **Eerste dag na de omschakeling valt af.** Met τ ≈ 23 u settelt het huis ~65% in 24 u, ~92% in 48 u. Omschakeling maandagavond → dinsdag valt af, **woensdag t/m de volgende maandag** zijn de meetdagen (`analysis_window`, in het bericht + het logboek).
- **Meet gas, niet `callForHeat`.** Die vlag is NONE/LOW/MEDIUM/HIGH → 0/25/50/100, een klepstand-proxy, geen energie. Gasbron: **tado Energy IQ** (m³ per ruimte). De bewoner voert maandelijks meterstanden in; daartussen *verdeelt* tado het verbruik zelf over de dagen naar stookactiviteit — dat is een schatting, en juist op weekniveau het zwakke punt. Het weekbericht vraagt daarom om een meterstand op de wisselavond (dan is de week echt gemeten). Normaliseren op graaddagen en gepaarde weken vergelijken. **Die meetkant zit (nog) niet in dit project** (stap 2: Energy IQ uitlezen — de API is niet officieel; gasverbruik per week is gedragsdata, dus alleen naar de privé-gist, nooit naar logs/`docs/`/commits).
- **Stookseizoen-poort:** `SEASON_MONTHS` okt–apr; daarbuiten geen bericht en geen weekregel (er valt niets op te stoken). De alternatie schuift daar niet van, want die is datum-afgeleid. `force`-input (env `FORCE_SEND=1`) negeert de poort voor een testrun.
- `DRY_RUN=1` print zonder te sturen **en zonder de state te schrijven** — een testdispatch mag het experimentlogboek niet vervuilen (anders dan bij de raam-adviseur is er hier geen roterend token dat wél weg moet).

### heating_experiment_state.json (additief)
```json
{"experiment": "night_setpoint", "last_updated": "ISO",
 "weeks": [{"week": "2026-W44", "experiment": "morning_recovery", "arm": "early",
            "switched_at": "2026-10-26", "analyse_from": "2026-10-28", "analyse_through": "2026-11-02"},
           {"week": "2026-W45", "experiment": "night_setpoint", "arm": "afkoelen", "night_setpoint": 16.0,
            "switched_at": "2026-11-02", "analyse_from": "2026-11-04", "analyse_through": "2026-11-09"}]}
```
Upsert op `week` (herhaalde dispatch stapelt niet), gesorteerd op `switched_at`, afgekapt op `MAX_WEEKS` 200. Per-regel `experiment` (additief): regels zonder tag krijgen bij het laden het experiment uit de kop van het bestand, vóórdat `record_week` die kop omzet. `previous_arm()` leest de vorige week hieruit en telt alleen regels van het lopende experiment — bij een koude start of de eerste week na een experimentwissel meldt het bericht "eerste week" i.p.v. een verzonnen bewering.

## Relation to other projects
Fully independent — no weather data, no other project's artefacts. Shares `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (privé-chat) only.
