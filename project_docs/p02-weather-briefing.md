# Project 2: Personal Weather Briefing

> Reference doc, read on demand — read it before changing this project's files. The always-loaded rules (privacy, ground rules, security) live in [`CLAUDE.md`](../CLAUDE.md); where the two differ, `CLAUDE.md` wins.

**Goal:** Daily personal weather briefing via Telegram, structured around fixed time blocks relevant to daily routine.

## Files
- `weather_briefing.py` — fetch Open-Meteo + build Telegram message
- `.github/workflows/weather-briefing.yml` — orchestrator target 05:00 lokaal + fallback cron 05:40 + guard-job

## Logic
- Fetches Open-Meteo hourly forecast for Utrecht
- Parses 24h window: temp, apparent_temp, precip, pop, uv_index
- Builds message per time block. **De blokken zijn een privacy-grens (privacy-sweep aug 2026)**
  en staan daarom NIET in de repo: een weekrooster van vertrek-, opvang-, kantoor-, thuiskomst-
  en sportvensters ís de "wanneer is het huis leeg"-kalender waar de privacy-sectie van `CLAUDE.md`
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

## UV cloud correction
Open-Meteo's `uv_index` field is only weakly cloud-corrected and reports clear-sky-like values on overcast/rainy days. We therefore fetch `uv_index_clear_sky` and apply the Josefsson & Landelius (2000) cloud modification factor `CMF = 1 - 0.75 * (cloud_fraction)^3.4` using the hourly `cloud_cover` from the same call. The corrected value is what `uv_windows()` thresholds against. If `uv_index_clear_sky` is missing for a given hour, fall back to the raw `uv_index`.
