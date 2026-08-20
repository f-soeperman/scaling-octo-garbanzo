#!/usr/bin/env python3
"""camping_forecast.py — Project 15: Kampeerkompas.

Doorlopend (jaarrond, 4×/dag) overzicht van waar en wanneer twaalf streken
geschikt zijn om te kamperen met tent, peuter en auto. Per streek wordt de
Open-Meteo-voorspelling (16 dagen) gescoord op de kampeercriteria:

- dag onder de 30 °C, nacht boven de 10 °C;
- een goede nacht heeft temperatuur ruim boven het dauwpunt (droge tent);
- dagregen telt zwaarder dan nachtregen;
- een officiële MeteoAlarm-waarschuwing van oranje of hoger is een rode vlag,
  net als extreme voorspelde waarden voorbij de waarschuwingshorizon — geel
  wordt bewust volledig genegeerd (zie WARN_MIN_LEVEL);
- vertrekken doe je het liefst na een droge nacht + droge ochtend.

De eenheid is de **kampeernacht**: de cel van dag D beoordeelt het dagdeel
(09–21u) plus de nacht die die avond begint (D 21:00 → D+1 09:00) — "is D een
goede dag én nacht om in de tent te staan". Vensters zijn reeksen van minstens
MIN_NIGHTS zulke nachten; de zekerheid komt uit het ECMWF-ensemble
(ledenfracties) afgetopt op de horizon.

Uitsluitend dashboard-voer: schrijft docs/camping_data.json en zwijgt verder
(geen Telegram-advies; alleen de standaard run_guarded-crash-alert).
DRY_RUN=1 rekent en print maar schrijft het artefact NIET — schrijven is het
enige neveneffect van dit script, dus een dry run die wél schrijft zou van een
echte run niet te onderscheiden zijn (de workflow-commitstap vindt dan niets).
"""

import json
import os
import time
from datetime import date, datetime, timedelta

import meteoalarm
from http_util import get_json
from notify import run_guarded, sanitize_error
from shared_const import LATITUDE, LONGITUDE, NL_DAYS, TZ, local_today, parse_date, utc_now_iso

# ── Configuratie ─────────────────────────────────────────────────────────────

OM_URL = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENSEMBLE_MODEL = "ecmwf_ifs025"  # ~51 leden, ~15 dagen
FORECAST_DAYS = 16
ENSEMBLE_DAYS = 15
DATA_PATH = os.getenv("CAMPING_DATA_PATH", "docs/camping_data.json")

# Alle twaalf streken liggen in CET/CEST → één timezone-param volstaat en de
# dag/nacht-snedes vallen overal op dezelfde klok (repo-beleid: Europe/Amsterdam).
OM_TIMEZONE = "Europe/Amsterdam"

# Representatieve kampeerdalen (bewust aanpasbaar; hoogte doet ertoe voor de
# nachten — dit zijn dal-/meerlocaties waar campings liggen, geen bergtoppen).
# area_patterns: substring-match tegen MeteoAlarm-areaDesc/geocodes. Geijkt op
# de echte feeds (eerste run, 13 aug 2026): NL waarschuwt per provincie
# ("Utrecht"), FR per departement ("Haut-Rhin"), AT per Bezirk ("Schwaz",
# "Villach Land", "Sankt Johann im Pongau") — de AT-lijsten dragen daarom álle
# Bezirke van de deelstaat, ook die zonder de deelstaatnaam erin.
# Bekende, geaccepteerde overlap (best-effort, geen exacte match): een
# departementnaam die zelf een woord-substring is van een ander departement
# ("Savoie" in "Haute-Savoie", "Eure" in "Eure-et-Loir") laat het kortere
# departement soms meetellen op een waarschuwing die alleen het langere raakt
# — nooit andersom. Over-inclusief, niet under-inclusief: een rode vlag die
# er niet hoort te zijn is minder erg dan eentje die ontbreekt.
REGIONS = [
    {"id": "utrecht", "label": "Utrecht", "country": "NL",
     "lat": LATITUDE, "lon": LONGITUDE,
     "area_patterns": ("utrecht",)},
    {"id": "salzburgerland", "label": "Salzburgerland", "country": "AT",
     "lat": 47.32, "lon": 12.80,  # Zell am See-dal
     "area_patterns": ("salzburg", "flachgau", "tennengau", "pongau", "pinzgau", "lungau",
                       "hallein", "zell am see", "tamsweg")},
    {"id": "tirol", "label": "Tirol", "country": "AT",
     "lat": 47.16, "lon": 11.86,  # Zillertal (Bezirk Schwaz)
     "area_patterns": ("tirol", "innsbruck", "unterland", "oberland", "imst", "kitzbühel",
                       "kitzbuhel", "kufstein", "landeck", "reutte", "schwaz", "lienz")},
    {"id": "karnten", "label": "Kärnten", "country": "AT",
     "lat": 46.61, "lon": 13.86,  # Villach/merengebied
     "area_patterns": ("kärnten", "karnten", "klagenfurt", "villach", "feldkirchen",
                       "hermagor", "spittal", "völkermarkt", "volkermarkt", "wolfsberg",
                       "sankt veit", "st. veit")},
    {"id": "steiermark", "label": "Steiermark", "country": "AT",
     "lat": 47.40, "lon": 13.69,  # Schladming/Ennstal
     "area_patterns": ("steiermark", "graz-umgebung", "graz", "deutschlandsberg",
                       "hartberg-fürstenfeld", "hartberg-furstenfeld", "leibnitz", "leoben",
                       "liezen", "murau", "murtal", "südoststeiermark", "sudoststeiermark",
                       "voitsberg", "weiz")},
    {"id": "normandie", "label": "Normandië", "country": "FR",
     "lat": 49.38, "lon": -1.75,  # Cotentin (Barneville-Carteret)
     "area_patterns": ("calvados", "manche", "orne", "eure", "seine-maritime")},
    {"id": "bretagne", "label": "Bretagne", "country": "FR",
     "lat": 48.25, "lon": -4.49,  # Crozon-schiereiland (Finistère)
     "area_patterns": ("finistère", "finistere", "côtes-d'armor", "cotes-d'armor",
                       "morbihan", "ille-et-vilaine")},
    {"id": "auvergne", "label": "Auvergne", "country": "FR",
     "lat": 45.57, "lon": 2.87,  # Lac Chambon/Monts Dore (Puy-de-Dôme)
     "area_patterns": ("puy-de-dôme", "puy-de-dome", "cantal", "haute-loire", "allier")},
    {"id": "elzas", "label": "Elzas", "country": "FR",
     "lat": 48.08, "lon": 7.36,  # Colmar/wijnroute
     "area_patterns": ("haut-rhin", "bas-rhin", "alsace")},
    {"id": "jura", "label": "Jura", "country": "FR",
     "lat": 46.57, "lon": 5.75,  # Clairvaux-les-Lacs
     "area_patterns": ("jura", "doubs")},
    {"id": "savoie", "label": "Savoie", "country": "FR",
     "lat": 45.55, "lon": 5.79,  # Lac d'Aiguebelette
     "area_patterns": ("savoie",)},
    {"id": "haute_savoie", "label": "Haute-Savoie", "country": "FR",
     "lat": 45.85, "lon": 6.17,  # Lac d'Annecy/Talloires
     "area_patterns": ("haute-savoie",)},
]

# Dag/nacht-vensters (lokale klokuren; halfopen [start, eind)). Op de twee
# DST-nachten is de 21→09-snede 23 of 25 uur lang — min/som-semantiek blijft
# gewoon geldig, dus geen special-casing.
DAY_START_H, DAY_END_H = 9, 21
NIGHT_START_H, NIGHT_END_H = 21, 9  # nacht van D = D 21:00 → D+1 09:00
MORNING_START_H, MORNING_END_H = 6, 12  # "droge ochtend" voor vertrek

# Harde gebruikerscriteria + de banden eromheen.
DAY_TMAX_HOT = 30.0     # daggrens (criterium)
DAY_TMAX_WARM = 27.0    # aanloopband naar de daggrens
NIGHT_TMIN_COLD = 10.0  # nachtgrens (criterium)
NIGHT_TMIN_COOL = 12.0  # aanloopband boven de nachtgrens
NIGHT_TMIN_HARD = 8.0   # duidelijk te koud, nog nét geen rode vlag

# Extreem → rode vlag, óók zonder officiële waarschuwing: MeteoAlarm kijkt maar
# ~2-4 dagen vooruit, dus voorbij die horizon zijn dit de rode vlaggen.
TMAX_RED = 33.0
TMIN_RED = 5.0          # peuter in een tent — hard nee
GUST_RED_KMH = 60.0
DAY_RAIN_RED_MM = 20.0
# Nachtregen had tot aug 2026 geen eigen extreem-plafond: "nachtregen_zwaar"
# (elke hoeveelheid ≥ NIGHT_RAIN_BAD_MM, dus ook 25mm) scoorde altijd exact 30
# punten — toevallig precies CAT_GOED, dus een stortbui 's nachts kon nooit
# boven "goed" uitkomen. Zelfde ~helft-verhouding als de rest van de
# dag/nacht-regenladder.
NIGHT_RAIN_RED_MM = 10.0

GUST_BREEZY_KMH, GUST_POOR_KMH = 35.0, 45.0
DAY_RAIN_DRY_MM, DAY_RAIN_SOME_MM, DAY_RAIN_BAD_MM = 1.0, 3.0, 8.0
NIGHT_RAIN_DRY_MM, NIGHT_RAIN_SOME_MM, NIGHT_RAIN_BAD_MM = 0.3, 1.0, 5.0
POP_DAY_UNSETTLED = 60  # % — droge som maar hoge kans → kleine straf
# Nachtelijk spiegelbeeld van POP_DAY_UNSETTLED — zelfde precedentie (een
# gemeten hoeveelheid wint altijd van de kans, zie score_day()), maar dan voor
# het nachtdeel, dat tot aug 2026 geen enkel kans-signaal had: een droge
# modeluitkomst met een zeer natte ensemble-kans bleef onopgemerkt.
POP_NIGHT_UNSETTLED = 60
DEW_MARGIN_GOOD, DEW_MARGIN_POOR = 2.0, 1.0  # min(T − Td) over de nacht

# Officiële waarschuwingen: alleen oranje en rood zijn een rode vlag. Geel wordt
# bewust volledig genegeerd — niet gescoord en niet getoond (bewonersbesluit
# aug 2026: een gele hittegolfwaarschuwing kleurde vrijwel de hele matrix rood).
# meteoalarm.py blijft generiek (parst ook geel); het filter leeft hier, bij het
# domeinbesluit.
WARN_MIN_LEVEL = "orange"

# Strafpunten per reden (0 = perfect; tests pinnen hierop). Nachtregen is
# bewust ~de helft van dagregen — overdag wil je buiten kunnen zijn, 's nachts
# lig je toch binnen (al pakt niemand graag een natte tent in).
PEN = {
    "hitte_naderend": 10, "hitte": 40,                          # Tmax 27–30 / ≥30
    # koude_nacht > CAT_GOED, bewust: een nacht onder de 10° schendt het harde
    # gebruikerscriterium en mag dus nooit in een kampeervenster vallen. Bij
    # elke wijziging van CAT_GOED moet deze waarde er strikt boven blijven.
    "koele_nacht": 8, "koude_nacht": 31, "te_koude_nacht": 40,  # Tmin 10–12 / 8–10 / 5–8
    "dauw_krap": 10, "dauw_nat": 12,                            # marge <2 / <1 °C
    "dagregen_licht": 8, "dagregen_matig": 20, "dagregen_zwaar": 40,
    "wisselvallig": 8,
    "nachtregen_licht": 5, "nachtregen_matig": 12, "nachtregen_zwaar": 30,
    "nachtregen_wisselvallig": 5,  # nachtelijk spiegelbeeld van "wisselvallig"
    "wind_fris": 10, "wind_hard": 25,
}
CAT_TOP, CAT_GOED, CAT_MATIG = 10, 30, 45  # score ≤ grens; erboven "slecht"
NIGHT_OK_CATS = ("top", "goed")  # venster-nachten; "matig" breekt het venster
MIN_NIGHTS = 3  # minimale kampeerduur (gebruikersbesluit — geldt overal)

# Super-regio's voor de flexibiliteitsvraag: "waar zitten we het beste als we
# binnen één landstreek af en toe willen verkassen, minstens MIN_NIGHTS
# nachten per plek?" utrecht is thuisbasis en doet bewust niet mee. Een test
# bewaakt dat de drie groepen samen exact de overige REGIONS-ids dekken,
# disjunct.
SUPER_REGIONS = [
    {"id": "oostenrijk", "label": "Oostenrijk",
     "region_ids": ("salzburgerland", "tirol", "karnten", "steiermark")},
    {"id": "nw_frankrijk", "label": "Noordwest-Frankrijk",
     "region_ids": ("normandie", "bretagne")},
    {"id": "oost_frankrijk", "label": "Oost-Frankrijk",
     "region_ids": ("auvergne", "elzas", "jura", "savoie", "haute_savoie")},
]
# Verkassen is niet gratis (tent afbreken en opbouwen met een peuter): één
# "licht ongemak"-equivalent, zodat de route niet voor 2 punten winst met de
# tent gaat slepen. Puur een stuurgetal voor de routekeuze — telt nooit mee in
# een getoonde dagscore. Domeinbeslissing.
MOVE_PENALTY = 8
# Rood op de route is een harde blokkade, geen afweging: groter dan élke som
# van gewone dagscores + verkassingen over de horizon (een test pint die
# ongelijkheid, zodat een PEN-hertuning hem niet stilzwijgend breekt). Routes
# rangschikken zo eerst op het aantal onvermijdelijke rode dagen en pas
# daarna op score. Bewust eindig: bij "overal rood" bestaat er tóch een route
# (die het dashboard dan eerlijk rood toont).
RED_DAY_PENALTY = 5000

# Partitie van de PEN-redenen over dagdeel (09–21u) en nacht (21–09u), voor de
# aparte dag- en nachttegels op de regiokaarten. Een test bewaakt dat dit PEN
# exact en disjunct dekt. "waarschuwing" splitst niet hier maar op
# vensteroverlap (zie split_parts).
DAY_REASONS = frozenset({"hitte_naderend", "hitte", "dagregen_licht", "dagregen_matig",
                         "dagregen_zwaar", "wisselvallig", "wind_fris", "wind_hard"})
NIGHT_REASONS = frozenset({"koele_nacht", "koude_nacht", "te_koude_nacht",
                           "dauw_krap", "dauw_nat",
                           "nachtregen_licht", "nachtregen_matig", "nachtregen_zwaar",
                           "nachtregen_wisselvallig"})
DAY_FLAGS = frozenset({"hitte_extreem", "storm", "stortregen"})
NIGHT_FLAGS = frozenset({"koude_nacht_extreem", "stortregen_nacht"})

# Kleine, losse ongemakken stapelen bewust niet op elkaar (bewonersbesluit
# aug 2026: vier kleine dingen samen mochten niet zwaarder wegen dan het
# grootste ervan). MINOR_REASONS is de goedkoopste (eerste) trap van elke
# ladder — ≤10 punten, altijd "het begint hier"; alles daarboven (≥12) is
# een écht probleem en telt onverkort mee, ook naast andere problemen. Zie
# _score_reasons(). Bewust een expliciete lijst i.p.v. afgeleid van de
# waarde, zodat een latere herweging van PEN deze indeling niet stilzwijgend
# verschuift.
MINOR_REASONS = frozenset({"hitte_naderend", "koele_nacht", "dauw_krap",
                           "dagregen_licht", "wisselvallig", "nachtregen_licht", "wind_fris",
                           "nachtregen_wisselvallig"})

# Zekerheid: de zwakste ensemble-fractie bepaalt de tier, afgetopt op de
# horizon (ver weg is nooit "hoog", wat de leden ook zeggen).
CONF_HOOG, CONF_MIDDEL = 0.80, 0.55
CONF_HORIZON_CAP_MIDDEL, CONF_HORIZON_CAP_LAAG = 10, 13  # dag-index
CONF_FALLBACK = ((3, "hoog"), (8, "middel"))  # zonder ensemble: horizon-ladder
CONF_RANK = {"laag": 0, "middel": 1, "hoog": 2}
ENS_DRY_DAY_MM, ENS_DRY_NIGHT_MM = 1.0, 0.3

# "Wat je kunt verwachten" — autotekst per venster (en per regio als er geen
# venster is), gebouwd in Python zoals alle gebruikersgerichte tekst in de repo
# (cf. window_advisor.plan_window_text). De banden zijn domeinbeslissingen.
VERW_DAYS = 5  # regio-niveau zonder venster: de komende N dagen
VERW_DAG_BANDEN = ((28.0, "hete dagen"), (24.0, "warme zomerdagen"), (19.0, "milde dagen"))
VERW_DAG_FRIS = "frisse dagen"
VERW_NACHT_BANDEN = ((16.0, "zwoele nachten"), (12.0, "frisse nachten"))
VERW_NACHT_KOUD = "koude nachten"
SLAAPZAK = (  # gemiddelde nacht-Tmin ≥ grens → hint; eerste match wint
    (18.0, "een dun slaapzakje of alleen een dekentje is genoeg voor de peuter"),
    (14.0, "een gewone slaapzak volstaat voor de peuter"),
    (10.0, "doe de peuter een warme slaapzak (en zo nodig een mutsje) aan"),
)
SLAAPZAK_TE_KOUD = "eigenlijk te koud voor de peuter in de tent"
WEEKDAG_KORT = tuple(d[:2] for d in NL_DAYS)  # ma..zo, index = date.weekday()

HOURLY_VARS = ["temperature_2m", "dew_point_2m", "precipitation",
               "precipitation_probability", "wind_gusts_10m", "weather_code"]
DAILY_VARS = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum",
              "precipitation_probability_max", "wind_gusts_10m_max"]


# ── Fetch (dun; tests monkeypatchen get_json) ────────────────────────────────

def fetch_region_forecast(region: dict) -> dict:
    params = {
        "latitude": region["lat"], "longitude": region["lon"],
        "hourly": ",".join(HOURLY_VARS),
        "daily": ",".join(DAILY_VARS),
        "timezone": OM_TIMEZONE,
        "forecast_days": FORECAST_DAYS,
    }
    return get_json(OM_URL, params, timeout=20, label=f"open-meteo-{region['id']}")


def fetch_region_ensemble(region: dict) -> dict | None:
    """ECMWF-ensemble als niet-fatale verrijking: uitval → None (horizon-ladder)."""
    params = {
        "latitude": region["lat"], "longitude": region["lon"],
        "models": ENSEMBLE_MODEL,
        "hourly": "temperature_2m,precipitation",
        "timezone": OM_TIMEZONE,
        "forecast_days": ENSEMBLE_DAYS,
    }
    try:
        return get_json(ENSEMBLE_URL, params, timeout=30, label=f"ensemble-{region['id']}")
    except Exception as e:
        print(f"[ensemble] {region['id']}: niet beschikbaar ({sanitize_error(e)})")
        return None


# Bewuste pauze vóór een hele regio herkanst wordt (zie
# fetch_region_forecast_resilient hieronder) — geen tunable om aan te draaien,
# alleen lang genoeg om een korte netwerk-hobbel te laten voorbijgaan.
REGION_RETRY_DELAY_S = 30


def fetch_region_forecast_resilient(region: dict) -> dict:
    """`fetch_region_forecast` met één regio-brede herkansing erbovenop.

    Met twaalf regio's (was zeven, aug 2026) valt een korte, bredere
    netwerk-hobbel eerder samen met de volle uitputting van één regio's eigen
    5 pogingen (~100s, zie http_util.get_json) dan met zeven — gemeten
    14 aug 2026: Bretagne verloor alle 5 pogingen binnen dezelfde hobbel,
    terwijl buurregio's (Elzas, Savoie) 'm na 2-3 pogingen wél haalden. Eén
    volle herkansing na een korte pauze kost in het normale geval niets (de
    eerste ronde lukt vrijwel altijd) en redt precies dit scenario, zonder de
    "één kapotte regio → rest gaat door"-opzet in `main()` aan te tasten —
    die vangt nog altijd een regio op die ook de herkansing niet haalt."""
    try:
        return fetch_region_forecast(region)
    except Exception as e:
        print(f"[forecast] {region['id']}: volle poging mislukt ({sanitize_error(e)}), "
              f"regio-brede herkansing over {REGION_RETRY_DELAY_S}s")
        time.sleep(REGION_RETRY_DELAY_S)
        return fetch_region_forecast(region)


# ── Uurreeks en snedes ───────────────────────────────────────────────────────

def hourly_series(om_json: dict) -> list[dict]:
    """Open-Meteo hourly-kolommen → rijen; tijden komen naïef-lokaal terug en
    krijgen TZ weer aangehecht (zelfde valkuil als overal in de repo)."""
    h = om_json.get("hourly", {})
    times = h.get("time", [])
    n = len(times)

    def col(key):
        vals = h.get(key) or []
        return list(vals) + [None] * (n - len(vals))

    temps, dews = col("temperature_2m"), col("dew_point_2m")
    rains, pops, gusts = col("precipitation"), col("precipitation_probability"), col("wind_gusts_10m")
    rows = []
    for i, t in enumerate(times):
        if temps[i] is None:
            continue
        rows.append({
            "dt": datetime.fromisoformat(t).replace(tzinfo=TZ),
            "temp": temps[i], "dew": dews[i], "rain": rains[i],
            "pop": pops[i], "gust": gusts[i],
        })
    return rows


def _slice(rows: list[dict], start_dt: datetime, end_dt: datetime) -> list[dict]:
    return [r for r in rows if start_dt <= r["dt"] < end_dt]


def _local_dt(d: date, hour: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, tzinfo=TZ)


def day_slice(rows, d):
    return _slice(rows, _local_dt(d, DAY_START_H), _local_dt(d, DAY_END_H))


def night_slice(rows, d):
    return _slice(rows, _local_dt(d, NIGHT_START_H), _local_dt(d + timedelta(days=1), NIGHT_END_H))


def morning_slice(rows, d):
    return _slice(rows, _local_dt(d, MORNING_START_H), _local_dt(d, MORNING_END_H))


def day_metrics(rows: list[dict], d: date) -> dict | None:
    sl = day_slice(rows, d)
    if not sl:
        return None
    pops = [r["pop"] for r in sl if r["pop"] is not None]
    gusts = [r["gust"] for r in sl if r["gust"] is not None]
    return {
        "tmax": max(r["temp"] for r in sl),
        "rain_mm": round(sum(r["rain"] or 0.0 for r in sl), 1),
        "pop_max": max(pops) if pops else None,
        "gust_max": max(gusts) if gusts else None,
    }


def night_metrics(rows: list[dict], d: date) -> dict | None:
    """Nacht van D (21:00 → D+1 09:00). `partial` = de reeks haalt de ochtend
    niet (laatste horizondag) — zo'n nacht telt niet mee voor een venster."""
    sl = night_slice(rows, d)
    if not sl:
        return None
    margins = [r["temp"] - r["dew"] for r in sl if r["dew"] is not None]
    pops = [r["pop"] for r in sl if r["pop"] is not None]
    last_needed = _local_dt(d + timedelta(days=1), NIGHT_END_H) - timedelta(hours=1)
    return {
        "tmin": min(r["temp"] for r in sl),
        "dew_margin": round(min(margins), 1) if margins else None,
        "rain_mm": round(sum(r["rain"] or 0.0 for r in sl), 1),
        "pop_max": max(pops) if pops else None,
        "partial": sl[-1]["dt"] < last_needed,
    }


# ── Score, vlaggen, categorie ────────────────────────────────────────────────

def _score_reasons(reasons: list[str]) -> int:
    """Som van de echte (niet-lichte) redenen + het zwaarste lichte probleem,
    als dat er is — lichte problemen (MINOR_REASONS) stapelen dus niet op
    elkaar, een matig/zwaar probleem telt altijd volledig mee."""
    zwaar = sum(PEN[r] for r in reasons if r not in MINOR_REASONS)
    licht = [PEN[r] for r in reasons if r in MINOR_REASONS]
    return zwaar + (max(licht) if licht else 0)


def score_day(day_m: dict, night_m: dict | None) -> tuple[int, list[str]]:
    """Strafpunten (0 = perfect) + de redenen (sleutels uit PEN). De celscore
    is het ZWAARSTE van het dagdeel en het nachtdeel (elk apart door
    _score_reasons gehaald), niet hun som. Optellen leek voor de hand liggend
    ("de hele kampeernacht telt mee"), maar geeft precies het omgekeerde
    probleem als de MINOR_REASONS-demping hierboven: twee helften die allebei
    op zichzelf keurig "goed" scoren (bv. 30 en 24 punten) konden samen (54)
    over de "matig"-grens heen kieperen naar "slecht" — het overzicht toonde
    dan een rode/oranje cel terwijl beide dag/nacht-tegels eronder groen
    stonden (gemeld door de gebruiker, 13 aug 2026, Salzburgerland 16 aug: dag
    30 + nacht 24 = 54 → "slecht", terwijl cat_day/cat_night allebei "goed"
    waren). Met "zwaarste helft" kan de gecombineerde cel per constructie
    nooit slechter zijn dan wat de tegels zelf al laten zien."""
    reasons: list[str] = []

    if day_m["tmax"] >= DAY_TMAX_HOT:
        reasons.append("hitte")
    elif day_m["tmax"] >= DAY_TMAX_WARM:
        reasons.append("hitte_naderend")

    if day_m["rain_mm"] >= DAY_RAIN_BAD_MM:
        reasons.append("dagregen_zwaar")
    elif day_m["rain_mm"] >= DAY_RAIN_SOME_MM:
        reasons.append("dagregen_matig")
    elif day_m["rain_mm"] >= DAY_RAIN_DRY_MM:
        reasons.append("dagregen_licht")
    elif day_m["pop_max"] is not None and day_m["pop_max"] >= POP_DAY_UNSETTLED:
        reasons.append("wisselvallig")

    if day_m["gust_max"] is not None:
        if day_m["gust_max"] >= GUST_POOR_KMH:
            reasons.append("wind_hard")
        elif day_m["gust_max"] >= GUST_BREEZY_KMH:
            reasons.append("wind_fris")

    if night_m is not None:
        if night_m["tmin"] < NIGHT_TMIN_HARD:
            reasons.append("te_koude_nacht")
        elif night_m["tmin"] < NIGHT_TMIN_COLD:
            reasons.append("koude_nacht")
        elif night_m["tmin"] < NIGHT_TMIN_COOL:
            reasons.append("koele_nacht")

        if night_m["dew_margin"] is not None:
            if night_m["dew_margin"] < DEW_MARGIN_POOR:
                reasons.append("dauw_nat")
            elif night_m["dew_margin"] < DEW_MARGIN_GOOD:
                reasons.append("dauw_krap")

        if night_m["rain_mm"] >= NIGHT_RAIN_BAD_MM:
            reasons.append("nachtregen_zwaar")
        elif night_m["rain_mm"] >= NIGHT_RAIN_SOME_MM:
            reasons.append("nachtregen_matig")
        elif night_m["rain_mm"] >= NIGHT_RAIN_DRY_MM:
            reasons.append("nachtregen_licht")
        elif night_m.get("pop_max") is not None and night_m["pop_max"] >= POP_NIGHT_UNSETTLED:
            reasons.append("nachtregen_wisselvallig")

    score = max(_score_reasons([r for r in reasons if r in DAY_REASONS]),
               _score_reasons([r for r in reasons if r in NIGHT_REASONS]))
    return score, reasons


def severe_warnings(warnings: list[dict]) -> list[dict]:
    """Alleen waarschuwingen van WARN_MIN_LEVEL of hoger (geel valt af)."""
    min_rank = meteoalarm.LEVEL_RANK[WARN_MIN_LEVEL]
    return [w for w in warnings if meteoalarm.LEVEL_RANK[w["level"]] >= min_rank]


def red_flags(day_m: dict, night_m: dict | None, day_warnings: list[dict]) -> list[str]:
    """Harde stops: officiële waarschuwing (oranje of hoger — geel is
    stroomopwaarts al weggefilterd door severe_warnings) óf extreme voorspelde
    waarden, die de dagen voorbij MeteoAlarms ~2-4-daagse waarschuwingshorizon
    dekken."""
    flags: list[str] = []
    if day_warnings:
        flags.append("waarschuwing")
    if day_m["tmax"] >= TMAX_RED:
        flags.append("hitte_extreem")
    if night_m is not None and night_m["tmin"] <= TMIN_RED:
        flags.append("koude_nacht_extreem")
    if day_m["gust_max"] is not None and day_m["gust_max"] >= GUST_RED_KMH:
        flags.append("storm")
    if day_m["rain_mm"] >= DAY_RAIN_RED_MM:
        flags.append("stortregen")
    if night_m is not None and night_m["rain_mm"] >= NIGHT_RAIN_RED_MM:
        flags.append("stortregen_nacht")
    return flags


def main_reason(reasons: list[str]) -> str | None:
    """De zwaarste reden van de zwaarste helft — het ene woord dat de celkleur
    verklaart (de celscore is de max van de twee helften, dus de dominante
    helft ís de kleur). Gelijkspel tussen de helften → de dag, daar handelt
    een kampeerder het eerst op. Voedt het reden-icoon achter de
    "waarom?"-toggle op de matrix en de "vooral: …"-regel in de tooltip."""
    if not reasons:
        return None
    dag = [r for r in reasons if r in DAY_REASONS]
    nacht = [r for r in reasons if r in NIGHT_REASONS]
    helft = dag if _score_reasons(dag) >= _score_reasons(nacht) else nacht
    if not helft:
        return None
    return max(helft, key=lambda r: PEN[r])


def split_parts(reasons: list[str], flags: list[str], *,
                warn_day: bool, warn_night: bool) -> dict:
    """Combi-score en -vlaggen → dag- en nachtdeel voor de dag/nacht-tegels.
    "waarschuwing" volgt de vensteroverlap (warn_day/warn_night), de overige
    redenen en vlaggen de vaste partitie."""
    return {
        "score_day": _score_reasons([r for r in reasons if r in DAY_REASONS]),
        "score_night": _score_reasons([r for r in reasons if r in NIGHT_REASONS]),
        "flags_day": (["waarschuwing"] if warn_day else []) + [f for f in flags if f in DAY_FLAGS],
        "flags_night": (["waarschuwing"] if warn_night else []) + [f for f in flags if f in NIGHT_FLAGS],
    }


def category(score: int, flags: list[str]) -> str:
    if flags:
        return "rood"
    if score <= CAT_TOP:
        return "top"
    if score <= CAT_GOED:
        return "goed"
    if score <= CAT_MATIG:
        return "matig"
    return "slecht"


# ── Vensters en vertrek ──────────────────────────────────────────────────────

def detect_windows(days: list[dict]) -> list[dict]:
    """Maximale reeksen aaneengesloten goede kampeernachten (cat ∈ NIGHT_OK_CATS,
    volledige nacht), lengte ≥ MIN_NIGHTS."""
    windows: list[dict] = []
    run: list[dict] = []

    def flush():
        if len(run) >= MIN_NIGHTS:
            last = run[-1]
            windows.append({
                "start": run[0]["date"],
                "end_night": last["date"],
                "vertrek": (date.fromisoformat(last["date"]) + timedelta(days=1)).isoformat(),
                "nights": len(run),
                "tmin_min": min(x["tmin_night"] for x in run if x["tmin_night"] is not None),
                "tmax_max": max(x["tmax"] for x in run),
                "rain_total_mm": round(sum((x["rain_day_mm"] or 0) + (x["rain_night_mm"] or 0)
                                           for x in run), 1),
                "conf": min((x["conf"] for x in run), key=lambda c: CONF_RANK[c]),
            })
        run.clear()

    for day in days:
        if day["cat"] in NIGHT_OK_CATS and not day["night_partial"]:
            run.append(day)
        else:
            flush()
    flush()
    return windows


def _dry_departure_from(days_by_date: dict[str, dict], rows: list[dict], night_date: date) -> bool:
    """Droog vertrek na de nacht van `night_date`: droge nacht én droge
    vertrekochtend (06–12u de dag erna). Een ochtend voorbij de horizon heeft
    geen rijen — dan telt alleen de nacht (de horizon topt de zekerheid al af)."""
    day = days_by_date.get(night_date.isoformat())
    if day is None or day["rain_night_mm"] is None or day["rain_night_mm"] > NIGHT_RAIN_DRY_MM:
        return False
    morning = morning_slice(rows, night_date + timedelta(days=1))
    return sum(r["rain"] or 0.0 for r in morning) <= NIGHT_RAIN_DRY_MM


def departure_advice(window: dict, days_by_date: dict[str, dict], rows: list[dict]) -> dict:
    """droog_vertrek voor de venster-vertrekochtend; anders de laatste eerdere
    droge ochtend die nog ≥ MIN_NIGHTS nachten overlaat (beste_vertrek)."""
    start = date.fromisoformat(window["start"])
    end_night = date.fromisoformat(window["end_night"])
    if _dry_departure_from(days_by_date, rows, end_night):
        return {"droog_vertrek": True, "beste_vertrek": None}
    d = end_night - timedelta(days=1)
    while (d - start).days + 1 >= MIN_NIGHTS:
        if _dry_departure_from(days_by_date, rows, d):
            return {"droog_vertrek": False,
                    "beste_vertrek": (d + timedelta(days=1)).isoformat()}
        d -= timedelta(days=1)
    return {"droog_vertrek": False, "beste_vertrek": None}


# ── Verwachtingstekst ────────────────────────────────────────────────────────

def _gem(vals: list) -> float | None:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _band(value: float, banden: tuple, anders: str) -> str:
    for grens, label in banden:
        if value >= grens:
            return label
    return anders


def _opsomming(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " en " + labels[-1]


def _daglabel(iso: str) -> str:
    d = parse_date(iso)
    return f"{WEEKDAG_KORT[d.weekday()]} {d.day}/{d.month}"


def verwachting_text(days: list[dict]) -> str | None:
    """Twee zinnen "wat je kunt verwachten" over een reeks dagdicts: karakter
    van dagen/nachten + slaapzakhint voor de peuter, en het regen-/dauwbeeld."""
    if not days:
        return None
    dag_gem = _gem([x["tmax"] for x in days])
    nacht_gem = _gem([x["tmin_night"] for x in days])
    if dag_gem is None:
        return None

    dag_deel = f"{_band(dag_gem, VERW_DAG_BANDEN, VERW_DAG_FRIS)} rond {round(dag_gem)}°"
    zin1 = dag_deel[0].upper() + dag_deel[1:]
    if nacht_gem is not None:
        nacht_deel = f"{_band(nacht_gem, VERW_NACHT_BANDEN, VERW_NACHT_KOUD)} rond {round(nacht_gem)}°"
        hint = SLAAPZAK_TE_KOUD
        for grens, h in SLAAPZAK:
            if nacht_gem >= grens:
                hint = h
                break
        zin1 = f"{zin1}, {nacht_deel} — {hint}."
    else:
        zin1 += "."

    regen_dagen = [x for x in days if (x["rain_day_mm"] or 0) >= DAY_RAIN_DRY_MM]
    regen_nachten = [x for x in days if (x["rain_night_mm"] or 0) >= NIGHT_RAIN_DRY_MM]
    if not regen_dagen and not regen_nachten:
        zin2 = "Het blijft droog"
    elif len(regen_dagen) > len(days) / 2:
        zin2 = "Geregeld regen overdag"
        if regen_nachten:
            zin2 += " en ook 's nachts valt er wat"
    elif regen_dagen and regen_nachten:
        zin2 = (f"Regen overdag op {_opsomming([_daglabel(x['date']) for x in regen_dagen])}"
                f" en 's nachts op {_opsomming([_daglabel(x['date']) for x in regen_nachten])}")
    elif regen_dagen:
        zin2 = f"Regen overdag op {_opsomming([_daglabel(x['date']) for x in regen_dagen])}"
    else:
        zin2 = f"Overdag droog, 's nachts wat regen ({_opsomming([_daglabel(x['date']) for x in regen_nachten])})"

    marges = [x["dew_margin_night"] for x in days if x["dew_margin_night"] is not None]
    if marges:
        if min(marges) < DEW_MARGIN_POOR:
            zin2 += ", en de tent wordt 's nachts nat van de dauw"
        elif min(marges) < DEW_MARGIN_GOOD:
            zin2 += ", en reken op dauw op de tent bij het inpakken"
    return f"{zin1} {zin2}."


# ── Ensemble → zekerheid ─────────────────────────────────────────────────────

def member_series(ens_json: dict | None) -> dict | None:
    """Ensemble-hourly → {'times': [dt], var: [ledenreeksen]}. Ledenkolommen
    heten `temperature_2m_memberNN` (het kale `temperature_2m` is lid 0/controle);
    op prefix gescand zodat het ledental mag verschuiven."""
    if not ens_json:
        return None
    h = ens_json.get("hourly", {})
    times = h.get("time", [])
    if not times:
        return None
    out = {"times": [datetime.fromisoformat(t).replace(tzinfo=TZ) for t in times]}
    for var in ("temperature_2m", "precipitation"):
        members = [h[k] for k in sorted(h) if k == var or k.startswith(var + "_member")]
        if not members:
            return None
        out[var] = members
    return out


def day_probs(members: dict | None, d: date) -> dict | None:
    """Ledenfracties voor de criteria van dag D; None voorbij de ensemble-horizon."""
    if members is None:
        return None
    times = members["times"]
    day_idx = [i for i, t in enumerate(times)
               if _local_dt(d, DAY_START_H) <= t < _local_dt(d, DAY_END_H)]
    night_end = _local_dt(d + timedelta(days=1), NIGHT_END_H)
    night_idx = [i for i, t in enumerate(times)
                 if _local_dt(d, NIGHT_START_H) <= t < night_end]
    if not day_idx or not night_idx or times[night_idx[-1]] < night_end - timedelta(hours=1):
        return None

    temps, rains = members["temperature_2m"], members["precipitation"]
    n = tmin_ok = tmax_ok = dry_day = dry_night = 0
    for m in range(len(temps)):
        t_day = [temps[m][i] for i in day_idx if i < len(temps[m]) and temps[m][i] is not None]
        t_night = [temps[m][i] for i in night_idx if i < len(temps[m]) and temps[m][i] is not None]
        if not t_day or not t_night:
            continue
        n += 1
        tmax_ok += max(t_day) < DAY_TMAX_HOT
        tmin_ok += min(t_night) > NIGHT_TMIN_COLD
        r = rains[m] if m < len(rains) else []
        rain_day = sum(r[i] or 0.0 for i in day_idx if i < len(r))
        rain_night = sum(r[i] or 0.0 for i in night_idx if i < len(r))
        dry_day += rain_day <= ENS_DRY_DAY_MM
        dry_night += rain_night <= ENS_DRY_NIGHT_MM
    if n == 0:
        return None
    return {"tmin_ok": round(tmin_ok / n, 2), "tmax_ok": round(tmax_ok / n, 2),
            "dry_day": round(dry_day / n, 2), "dry_night": round(dry_night / n, 2)}


def confidence(day_index: int, probs: dict | None) -> str:
    """Zwakste ensemble-éénstemmigheid → tier, afgetopt op de horizon; zonder
    ensemble de pure horizon-ladder uit CONF_FALLBACK.

    Éénstemmigheid is de afstand tot 50/50 (`max(v, 1-v)`), niet de rauwe
    fractie: een criterium waar 0% van de leden aan voldoet is net zo
    éénstemmig als eentje waar 100% aan voldoet — beide zijn de ensemble het
    roerend eens, alleen over een ongunstige uitkomst. De rauwe fractie
    gebruiken zou zo'n dag als "laag" (onzeker) merken terwijl het model juist
    zeker is van slecht weer."""
    if probs is not None:
        agreement = min(max(v, 1.0 - v) for v in probs.values())
        tier = "hoog" if agreement >= CONF_HOOG else "middel" if agreement >= CONF_MIDDEL else "laag"
    else:
        tier = "laag"
        for limit, t in CONF_FALLBACK:
            if day_index < limit:
                tier = t
                break
    if day_index >= CONF_HORIZON_CAP_LAAG:
        return "laag"
    if day_index >= CONF_HORIZON_CAP_MIDDEL and tier == "hoog":
        return "middel"
    return tier


# ── Regio-opbouw ─────────────────────────────────────────────────────────────

def _day_warning_summary(warnings: list[dict]) -> dict | None:
    if not warnings:
        return None
    worst = max(warnings, key=lambda w: meteoalarm.LEVEL_RANK[w["level"]])
    return {
        "level": worst["level"],
        "events": sorted({w["event"] for w in warnings}),
        "until": max(w["expires"] for w in warnings).isoformat(),
    }


def build_region(region: dict, om_json: dict, ens_json: dict | None,
                 country_warnings: list[dict] | None, today: date) -> dict:
    """Eén regio-blok voor het artefact. country_warnings=None betekent
    "feed onbereikbaar" (≠ lege lijst "geen waarschuwingen")."""
    rows = hourly_series(om_json)
    members = member_series(ens_json)
    # Geel valt hier al af (severe_warnings) — celvlaggen, dagsamenvatting en
    # warnings_active zien uitsluitend oranje+.
    matched = (severe_warnings([w for w in country_warnings
                                if meteoalarm.match_region(w, region["area_patterns"])])
               if country_warnings is not None else None)

    days: list[dict] = []
    for i in range(FORECAST_DAYS):
        d = today + timedelta(days=i)
        day_m = day_metrics(rows, d)
        if day_m is None:
            continue
        night_m = night_metrics(rows, d)
        # Waarschuwing raakt de cel als hij dag- óf nachtvenster overlapt (09u D → 09u D+1).
        cell_start = _local_dt(d, DAY_START_H)
        cell_end = _local_dt(d + timedelta(days=1), NIGHT_END_H)
        day_warnings = ([w for w in matched if meteoalarm.active_in(w, cell_start, cell_end)]
                        if matched is not None else [])
        score, reasons = score_day(day_m, night_m)
        flags = red_flags(day_m, night_m, day_warnings)
        warn_day = any(meteoalarm.active_in(w, cell_start, _local_dt(d, DAY_END_H))
                       for w in day_warnings)
        warn_night = any(meteoalarm.active_in(w, _local_dt(d, NIGHT_START_H), cell_end)
                         for w in day_warnings)
        parts = split_parts(reasons, flags, warn_day=warn_day, warn_night=warn_night)
        probs = day_probs(members, d)
        days.append({
            "date": d.isoformat(),
            "tmax": round(day_m["tmax"], 1),
            "tmin_night": round(night_m["tmin"], 1) if night_m else None,
            "dew_margin_night": night_m["dew_margin"] if night_m else None,
            "rain_day_mm": day_m["rain_mm"],
            "rain_night_mm": night_m["rain_mm"] if night_m else None,
            "pop_day_max": day_m["pop_max"],
            "pop_night_max": night_m["pop_max"] if night_m else None,
            "gust_max_kmh": day_m["gust_max"],
            "score": score, "cat": category(score, flags),
            "red_flags": flags, "reasons": reasons,
            "cat_day": category(parts["score_day"], parts["flags_day"]),
            "cat_night": (category(parts["score_night"], parts["flags_night"])
                          if night_m is not None else None),
            "red_flags_day": parts["flags_day"],
            "red_flags_night": parts["flags_night"],
            "main_reason": main_reason(reasons),
            "warning": _day_warning_summary(day_warnings),
            "probs": probs,
            "conf": confidence(i, probs),
            "night_partial": night_m is None or night_m["partial"],
        })

    days_by_date = {x["date"]: x for x in days}
    windows = detect_windows(days)
    for w in windows:
        w.update(departure_advice(w, days_by_date, rows))
        w["verwachting"] = verwachting_text(
            [x for x in days if w["start"] <= x["date"] <= w["end_night"]])

    now = datetime.now(TZ)
    active = ([{"level": w["level"], "event": w["event"], "area": w["area"],
                "onset": w["onset"].isoformat(), "expires": w["expires"].isoformat()}
               for w in matched if w["expires"] > now]
              if matched is not None else [])

    return {
        "id": region["id"], "label": region["label"], "country": region["country"],
        "lat": region["lat"], "lon": region["lon"],
        "elevation_m": om_json.get("elevation"),
        "status": "ok",
        "ensemble": "ok" if members is not None else "unavailable",
        "verwachting": verwachting_text(days[:VERW_DAYS]),  # fallback zonder venster
        "days": days, "windows": windows, "warnings_active": active,
    }


# ── Super-regio's: flexibele route ───────────────────────────────────────────

def _flex_day_cost(day: dict | None) -> float:
    """Routekosten van één kampeernacht in een subregio. None = de subregio
    heeft die datum niet (kortere horizon) → daar kún je dan niet staan."""
    if day is None:
        return float("inf")
    if day["cat"] == "rood":
        return day["score"] + RED_DAY_PENALTY
    return float(day["score"])


def flex_route(sub_days: list[dict[str, dict]], dates: list[str]) -> list[tuple[int, bool]] | None:
    """De goedkoopste route door één super-regio: per datum in welke subregio
    je staat, met minimaal MIN_NIGHTS nachten per plek.

    Klein dynamisch programma over (subregio, nachten-op-deze-plek, gecapt op
    MIN_NIGHTS): blijven, of — alleen als je er al MIN_NIGHTS nachten staat —
    verkassen (+ MOVE_PENALTY). De waarde per toestand is (strafpunten,
    verkassingen), lexicografisch: gelijke kosten kiezen de minste
    verkassingen, en bij écht gelijkspel wint de eerste subregio (strikte
    <-vergelijking + gesorteerde iteratie — 4×/dag draaien mag de route niet
    laten wiebelen op dict-volgorde). In de horizonstaart mag de route nog
    gewoon verkassen (eindverblijf < MIN_NIGHTS): verbieden zou de route juist
    daar vastpinnen waar de zekerheid toch al "laag" is, en een late
    verkassing gebeurt alleen als hij > MOVE_PENALTY oplevert.

    Geeft per datum (subregio-index, verkasdag): dag 0 is nacht 1 op de
    startplek, een verkasdag telt als nacht 1 op de nieuwe plek. None alleen
    als er geen begaanbare route bestaat (geen subregio met data)."""
    inf = float("inf")
    states: dict[tuple[int, int], tuple[float, int]] = {}
    for r, per_datum in enumerate(sub_days):
        cost = _flex_day_cost(per_datum.get(dates[0]))
        if cost < inf:
            states[(r, 1)] = (cost, 0)
    if not states:
        return None

    parents: list[dict] = [dict.fromkeys(states)]  # dag 0 heeft geen ouder
    for datum in dates[1:]:
        nxt: dict[tuple[int, int], tuple[float, int]] = {}
        par: dict[tuple[int, int], tuple[int, int, bool]] = {}
        for r, n in sorted(states):
            cost, moves = states[(r, n)]
            stay = _flex_day_cost(sub_days[r].get(datum))
            if stay < inf:
                key, val = (r, min(n + 1, MIN_NIGHTS)), (cost + stay, moves)
                if key not in nxt or val < nxt[key]:
                    nxt[key], par[key] = val, (r, n, False)
            if n < MIN_NIGHTS:
                continue
            for r2 in range(len(sub_days)):
                if r2 == r:
                    continue
                move = _flex_day_cost(sub_days[r2].get(datum))
                if move < inf:
                    key, val = (r2, 1), (cost + move + MOVE_PENALTY, moves + 1)
                    if key not in nxt or val < nxt[key]:
                        nxt[key], par[key] = val, (r, n, True)
        if not nxt:
            # Kan alleen bij een gat midden in élke subregio-reeks — defensief
            # afbreken is dan eerlijker dan een halve route verzinnen.
            return None
        states = nxt
        parents.append(par)

    route: list[tuple[int, bool]] = []
    key = min(sorted(states), key=lambda k: states[k])
    for par in reversed(parents):
        parent = par[key]
        route.append((key[0], parent[2] if parent else False))
        if parent:
            key = (parent[0], parent[1])
    route.reverse()
    return route


def build_super_region(sup: dict, blocks_by_id: dict[str, dict]) -> dict:
    """Eén super-regioblok: de optimale flexroute + kopcijfers. Alleen
    subregio's met status "ok" en dagen doen mee; geen enkele beschikbaar →
    hetzelfde stub-patroon als een kapotte regio (status "unavailable",
    zonder days — consumenten poorten op status)."""
    subs = [blocks_by_id[rid] for rid in sup["region_ids"]
            if blocks_by_id.get(rid, {}).get("status") == "ok"
            and blocks_by_id[rid].get("days")]
    sub_days = [{x["date"]: x for x in b["days"]} for b in subs]
    dates = sorted(set().union(*map(set, sub_days))) if sub_days else []
    route = flex_route(sub_days, dates) if dates else None
    if route is None:
        return {"id": sup["id"], "label": sup["label"],
                "region_ids": list(sup["region_ids"]), "status": "unavailable"}

    days: list[dict] = []
    segments: list[dict] = []
    for datum, (r, moved) in zip(dates, route, strict=True):
        day = sub_days[r][datum]
        # De echte waarden van de gekozen subregio — MOVE_PENALTY en
        # RED_DAY_PENALTY sturen alleen de routekeuze, nooit wat er staat.
        days.append({
            "date": datum, "region": subs[r]["id"], "region_label": subs[r]["label"],
            "move": moved,
            "cat": day["cat"], "score": day["score"], "conf": day["conf"],
            "night_partial": day["night_partial"],
            "tmax": day["tmax"], "tmin_night": day["tmin_night"],
            "dew_margin_night": day["dew_margin_night"],
            "rain_day_mm": day["rain_day_mm"], "rain_night_mm": day["rain_night_mm"],
            "red_flags": day["red_flags"], "main_reason": day["main_reason"],
        })
        if moved or not segments:
            segments.append({"region": subs[r]["id"], "region_label": subs[r]["label"],
                             "start": datum, "end_night": datum})
        else:
            segments[-1]["end_night"] = datum

    # Kopcijfers tellen — net als de vensters — alleen volledige nachten: de
    # horizon-afgekapte laatste nacht hoort niet in "X van N nachten goed".
    full = [x for x in days if not x["night_partial"]]
    return {
        "id": sup["id"], "label": sup["label"],
        "region_ids": list(sup["region_ids"]), "status": "ok",
        "days": days, "segments": segments, "moves": len(segments) - 1,
        "nights_ok": sum(1 for x in full if x["cat"] in NIGHT_OK_CATS),
        "nights_total": len(full),
        "red_days": sum(1 for x in days if x["cat"] == "rood"),
        "windows": detect_windows(days),
    }


def build_super_regions(region_blocks: list[dict]) -> list[dict]:
    by_id = {b["id"]: b for b in region_blocks}
    return [build_super_region(sup, by_id) for sup in SUPER_REGIONS]


def build_payload(region_blocks: list[dict], warnings_status: dict, now: datetime,
                  super_blocks: list[dict] | None = None) -> dict:
    return {
        "generated_at": utc_now_iso(),
        "as_of_local": now.isoformat(timespec="minutes"),
        "source": "open-meteo + ecmwf-ensemble + meteoalarm",
        "horizon_days": FORECAST_DAYS,
        "params": {
            "MIN_NIGHTS": MIN_NIGHTS, "MOVE_PENALTY": MOVE_PENALTY,
            "DAY_TMAX_HOT": DAY_TMAX_HOT, "NIGHT_TMIN_COLD": NIGHT_TMIN_COLD,
            "TMAX_RED": TMAX_RED, "TMIN_RED": TMIN_RED,
            "GUST_RED_KMH": GUST_RED_KMH, "DAY_RAIN_RED_MM": DAY_RAIN_RED_MM,
            "NIGHT_RAIN_RED_MM": NIGHT_RAIN_RED_MM,
            "DEW_MARGIN_GOOD": DEW_MARGIN_GOOD, "DEW_MARGIN_POOR": DEW_MARGIN_POOR,
            "DAY_RAIN_DRY_MM": DAY_RAIN_DRY_MM, "DAY_RAIN_BAD_MM": DAY_RAIN_BAD_MM,
            "NIGHT_RAIN_DRY_MM": NIGHT_RAIN_DRY_MM,
            "CAT_TOP": CAT_TOP, "CAT_GOED": CAT_GOED, "CAT_MATIG": CAT_MATIG,
            "CONF_HOOG": CONF_HOOG, "CONF_MIDDEL": CONF_MIDDEL,
            "ensemble_model": ENSEMBLE_MODEL, "WARN_MIN_LEVEL": WARN_MIN_LEVEL,
        },
        "warnings_status": warnings_status,
        "regions": region_blocks,
        "super_regions": super_blocks or [],
    }


# ── Artefact ─────────────────────────────────────────────────────────────────

def write_artifact(payload: dict) -> None:
    os.makedirs(os.path.dirname(DATA_PATH) or ".", exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[data] {DATA_PATH} geschreven ({os.path.getsize(DATA_PATH)} bytes)")


# ── Main ─────────────────────────────────────────────────────────────────────

def _region_summary(block: dict) -> str:
    if block["status"] != "ok":
        return f"{block['label']}: onbereikbaar"
    if block["windows"]:
        w = block["windows"][0]
        vertrek = "droog vertrek" if w["droog_vertrek"] else (
            f"beste vertrek {w['beste_vertrek']}" if w["beste_vertrek"] else "geen droog vertrek")
        return (f"{block['label']}: venster {w['start']} t/m {w['end_night']} "
                f"({w['nights']} nachten, {w['conf']}, {vertrek})")
    return f"{block['label']}: geen venster van ≥ {MIN_NIGHTS} nachten"


def _super_summary(block: dict) -> str:
    if block["status"] != "ok":
        return f"Flex {block['label']}: onbereikbaar"
    verkassen = f"{block['moves']}× verkassen" if block["moves"] else "zonder verkassen"
    return (f"Flex {block['label']}: {block['nights_ok']}/{block['nights_total']} "
            f"nachten goed, {verkassen}")


def main() -> None:
    now = datetime.now(TZ)
    today = local_today()

    warnings_by_country: dict[str, list | None] = {}
    warnings_status: dict[str, str] = {}
    for country in sorted({r["country"] for r in REGIONS}):
        try:
            warnings_by_country[country] = meteoalarm.fetch_country_warnings(country)
            warnings_status[country] = "ok"
        except Exception as e:
            print(f"[meteoalarm] {country}: feed onbereikbaar ({sanitize_error(e)})")
            warnings_by_country[country] = None
            warnings_status[country] = "failed"

    blocks: list[dict] = []
    ok = 0
    for region in REGIONS:
        try:
            om = fetch_region_forecast_resilient(region)
        except Exception as e:
            print(f"[forecast] {region['id']}: onbereikbaar ({sanitize_error(e)})")
            blocks.append({"id": region["id"], "label": region["label"],
                           "country": region["country"], "status": "unavailable"})
            continue
        ens = fetch_region_ensemble(region)
        blocks.append(build_region(region, om, ens, warnings_by_country[region["country"]], today))
        ok += 1

    if ok == 0:
        raise RuntimeError("alle regio's onbereikbaar — geen artefact te schrijven")

    # Vóór de DRY_RUN-kortsluiting, zodat een dry run de flexroutes wél oefent.
    super_blocks = build_super_regions(blocks)

    for block in blocks:
        print(_region_summary(block))
    for block in super_blocks:
        print(_super_summary(block))

    if os.environ.get("DRY_RUN") == "1":
        print("DRY_RUN=1, artefact niet geschreven.")
        return
    write_artifact(build_payload(blocks, warnings_status, now, super_blocks=super_blocks))


if __name__ == "__main__":
    # fail_threshold=2: de workflow herkanst één keer in dezelfde job (sleep 600),
    # dus pas de tweede opeenvolgende crash is een echte storing waard.
    run_guarded(main, "kampeerkompas", fail_threshold=2)
