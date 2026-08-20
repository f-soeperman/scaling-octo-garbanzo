#!/usr/bin/env python3
"""
vent_io.py — data-loodgieterij van de ventilatie-tweeling (Project 13).

Loaders (huisgeometrie, window_data, geleerde staat incl. de PHYSICS_REV-poort),
openingen-log-reconstructie (incl. de speciale `ac_room`/`paused`-sleutels),
Open-Meteo-fetch + WU-buiten-nu-verfijning, de driver-tijdlijn (build_timeline,
met de geleerde om_bias-correctie als enige plek waar de buitentemperatuur de
fysica binnenkomt), en de maand-shards (data/twin2_history — de trainingsset
voor offline evaluatie en het seeden, geërfd van tweeling 2).

Geen muteerbare module-globals: make_context() bouwt de RunContext die alle
fysica-aanroepen expliciet meekrijgen (vent_physics).

Env: GIST_ID/GIST_TOKEN (openingen-log, read-only), WU_STATION_ID/WU_API_KEY
(buiten-nu-verfijning), VENT_DATA_PATH/VENT_LEARNED_PATH/VENT_HISTORY_DIR/
HOUSE_MODEL_PATH/WINDOW_DATA_PATH (test-overrides).
"""

import glob
import json
import os
import subprocess
from datetime import date, datetime, timedelta, timezone

import requests

import artefact_io
import shared_const
import om_bias
import gist_io
from gist_io import read_json as gist_read_json
from http_util import get_json
from wu_bias import correct_temp
from window_advisor import convert_rh, fetch_wu_current_temp

import vent_physics as vp
from vent_physics import (
    RunContext,
    SOLAR_SUBSTEPS, WU_SOLAR_SCALE_DECAY_H,
    WU_SOLAR_SCALE_MIN, WU_SOLAR_SCALE_MAX, WU_SOLAR_MIN_WM2,
    PRIORS, PER_ROOM_PARAMS, GLOBAL_PARAMS,
    clamp_model_bounds, facade_irradiance, per_window_solar, sun_position,
)

HOUSE_FILE     = os.getenv("HOUSE_MODEL_PATH", "house_model.json")
WINDOW_DATA    = os.getenv("WINDOW_DATA_PATH", "docs/window_data.json")
DASHBOARD_FILE = os.getenv("VENT_DATA_PATH", "docs/vent_data.json")
LEARNED_FILE   = os.getenv("VENT_LEARNED_PATH", "docs/vent_learned.json")
# Browser-payload van de 12u-vooruitblik (weer-only drivers + thermische params + het
# geankerde zaad) — de speeltuin rekent daarmee raamstand-scenario's lokaal door. Apart van
# vent_data.json: dát is een slank dashboard-schema en dit is een andere consument.
FORECAST_FILE  = os.getenv("VENT_FORECAST_PATH", "docs/vent_forecast.json")
OPENINGS_FILE  = "house_openings.json"

# Fysica-revisie van de tweeling. Bij een mismatch met de opgeslagen learned-staat reset
# merged_params ALLE params naar hun priors (de oude waren compensaties voor de oude
# fysica) en slaat de runner de anomalie-poort die ene run over; daarna her-seeden met
# tools/vent_seed.py zodat de reset niet live vanaf priors hoeft te leren. Rev 6 = de
# lijn van airflow_model rev 5 (eenzijdige ventilatie + DNI-conventie + binnengordijn-
# factor), voortgezet als startpunt van de herbouw (Project 13).
# Rev 7 (aug 2026): de kruipruimte-verankering (`GROUND_AIR_COUPLING` 0.5 → 1.0) + de
# per-kamer parametervloer (`param_bounds`, living.c_mass ≥ 0.595). De geleerde params
# absorbeerden de te koude kruipruimte — een staande put van ~250 W onder living — dus ze
# moeten terug naar hun priors i.p.v. die compensatie de nieuwe fysica in te dragen. Zie
# tools/horizon_backtest.py voor de meting en AIRFLOW3_ASSESSMENT.md voor de motivering;
# her-seed na deploy met tools/vent_seed.py.
PHYSICS_REV = 7

TZ = shared_const.TZ

# Speciale sleutel in een openingen-log-snapshot: in wélke kamer de (ene, mobiele) airco staat
# — een room-id, of "" / "geen" = geen airco. Voorwaarts geaccumuleerd zoals elke andere stand.
# Bewust géén element-id: build_openings kent 'm niet → raakt het luchtstroomnetwerk nooit. Het
# model heeft géén actieve-koel-term, dus de AC-kamer wordt alleen uit de KALIBRATIE gelaten
# (zie main); ze blijft wél voorspeld + getoond.
AC_STATE_KEY = "ac_room"

# Speciale sleutel in een openingen-log-snapshot: is het huis nu gepauzeerd (huis-breed, geen
# room-id)? True zolang iemand anders — niet de betrouwbare melder — thuis kan zijn; niemand
# meldt dan de raam/rooster/deur-standen betrouwbaar. Voorwaarts geaccumuleerd zoals ac_room.
# Anders dan AC_STATE_KEY raakt dit ALLE kamers tegelijk (het is geen kamer-uitsluiting maar een
# leer-gate — zie main), en anders dan de AC-guard is géén apart guard-venster nodig: een nog-
# actieve pauze is per definitie open-eindig tot nu (zie paused_intervals) en sluit recente
# samples dus vanzelf uit.
PAUSE_STATE_KEY = "paused"

# Kalibratievenster + integratie.
CALIB_WINDOW_H = 48.0    # uur historie waarover we de fout minimaliseren (~2 dag-nacht-cycli;

                         # window_data houdt ~48u tado-historie → traag-veranderende termen
                         # ua_party/q_int/c_mass worden identificeerbaar i.p.v. naar hun grens
                         # te driften op een half-daags venster)
WARMUP_H       = 24.0    # uur sim-only aanloop vóór het residu-venster: de trage massaknoop

                         # equilibreert zodat zijn beginwaarde geen vrije laagfrequente bias is.
                         # Drivers reiken ver genoeg terug via Open-Meteo past_days; residuen
                         # tellen alleen waar tado-samples bestaan (≤CALIB_WINDOW_H terug)
CALIB_COVERAGE_WARN_H = 24.0   # effectieve grond-waarheid-spanwijdte (na AC-/verwarmings-/

def openings_at(log: list[dict], when: datetime) -> dict:
    """Actieve gerapporteerde toestand per element op tijdstip `when`, voorwaarts
    geaccumuleerd: elk element houdt zijn laatst-gezette waarde tot het opnieuw gemeld
    wordt. Zo kun je kleine, losse wijzigingen melden (één raam) zonder de rest te
    herhalen, en weerspiegelt de toestand wat écht open/dicht staat. Lege dict als er
    niets vóór `when` is gelogd."""
    entries = []
    for entry in log:
        try:
            t = datetime.fromisoformat(entry["t"])
        except (ValueError, TypeError, KeyError):
            continue
        if t <= when:
            entries.append((t, entry.get("states", {}) or {}))
    entries.sort(key=lambda e: e[0])
    state: dict = {}
    for _, st in entries:
        state.update(st)
    return state

def _norm_ac_room(value) -> str | None:
    """Normaliseer de gerapporteerde AC-kamer naar een room-id, of None (geen airco)."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("", "geen", "none", "off", "uit", "-"):
        return None
    return s

def ac_changes(log: list[dict]) -> list[tuple]:
    """Chronologische (tijdstip, room-id|None) AC-toewijzingen uit de openingen-log: elk
    snapshot dat de `ac_room`-sleutel zet. Voorwaarts uit te lezen met `ac_room_at`."""
    out = []
    for entry in log:
        st = entry.get("states", {}) or {}
        if AC_STATE_KEY not in st:
            continue
        try:
            t = datetime.fromisoformat(entry["t"])
        except (ValueError, TypeError, KeyError):
            continue
        out.append((t, _norm_ac_room(st[AC_STATE_KEY])))
    out.sort(key=lambda c: c[0])
    return out

def ac_room_at(changes: list[tuple], when: datetime) -> str | None:
    """Welke kamer de airco had op tijdstip `when` (voorwaarts geaccumuleerd), of None."""
    room = None
    for t, r in changes:
        if t <= when:
            room = r
        else:
            break
    return room

def _norm_paused(value) -> bool:
    """Normaliseer de gerapporteerde pauze-stand naar een bool."""
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    return s in ("true", "1", "paused", "gepauzeerd", "aan", "ja")

def pause_changes(log: list[dict]) -> list[tuple]:
    """Chronologische (tijdstip, paused-bool) wijzigingen uit de openingen-log: elk snapshot
    dat de `paused`-sleutel zet. Voorwaarts uit te lezen met `paused_at`."""
    out = []
    for entry in log:
        st = entry.get("states", {}) or {}
        if PAUSE_STATE_KEY not in st:
            continue
        try:
            t = datetime.fromisoformat(entry["t"])
        except (ValueError, TypeError, KeyError):
            continue
        out.append((t, _norm_paused(st[PAUSE_STATE_KEY])))
    out.sort(key=lambda c: c[0])
    return out

def paused_at(changes: list[tuple], when: datetime) -> bool:
    """Was het huis gepauzeerd op tijdstip `when` (voorwaarts geaccumuleerd)? Vóór de eerste
    melding: niet gepauzeerd (False)."""
    val = False
    for t, v in changes:
        if t <= when:
            val = v
        else:
            break
    return val

def paused_intervals(changes: list[tuple], now: datetime) -> list[tuple]:
    """Zet de boolean-wisselingen om in (start, eind)-tupels waarin het huis gepauzeerd was. Een
    nog-actieve pauze (geen latere 'uit'-melding) loopt open-eindig door tot `now` — dat sluit
    recente samples vanzelf uit, zónder apart guard-venster zoals bij de airco (die guard bestaat
    juist omdát een 'staat nu hier'-melding niet met een interval-eind samenvalt; hier IS
    'nu, nog actief' letterlijk het interval-eind)."""
    intervals = []
    start = None
    for t, v in changes:
        if v and start is None:
            start = t
        elif not v and start is not None:
            intervals.append((start, t))
            start = None
    if start is not None:
        intervals.append((start, now))
    return intervals

def collect_heating_on(house: dict, wd: dict, since: datetime) -> dict[str, set]:
    """Per sensorkamer de tijdstippen (datetime) sinds `since` waarop tado meldde dat er
    gestookt werd (`heat`-vlag in de window_data.json-history). Leeg → geen stook-samples.
    Leest dezelfde history als `collect_actual`, zodat de tijdstippen exact matchen."""
    out: dict[str, set] = {}
    for rid, room in house.get("rooms", {}).items():
        wd_key = room.get("from_window_data")
        if not wd_key or wd_key not in wd.get("rooms", {}):
            continue
        on = set()
        for s in wd["rooms"][wd_key].get("history", []):
            try:
                ts = datetime.fromisoformat(s["t"])
            except (ValueError, TypeError, KeyError):
                continue
            if ts >= since and s.get("temp") is not None and s.get("heat"):
                on.add(ts)
        if on:
            out[rid] = on
    return out

def heating_now(house: dict, wd: dict) -> dict[str, bool]:
    """Per sensorkamer of tado nú meldt dat er gestookt wordt (`heating`-vlag op de kamer in
    window_data.json) — voor de dashboard-chip + de 'niet-gekalibreerd'-melding."""
    out: dict[str, bool] = {}
    for rid, room in house.get("rooms", {}).items():
        wd_key = room.get("from_window_data")
        if wd_key and wd_key in wd.get("rooms", {}):
            out[rid] = bool(wd["rooms"][wd_key].get("heating"))
    return out

def collect_actual(house: dict, wd: dict, since: datetime) -> dict:
    """Per sensorkamer de werkelijke tado-temp-samples (t, °C) vanaf `since`, uit de
    history in window_data.json (+ de huidige meting)."""
    actual = {}
    for rid, room in house.get("rooms", {}).items():
        wd_key = room.get("from_window_data")
        if not wd_key or wd_key not in wd.get("rooms", {}):
            continue
        rd = wd["rooms"][wd_key]
        samples = []
        for s in rd.get("history", []):
            try:
                ts = datetime.fromisoformat(s["t"])
            except (ValueError, TypeError, KeyError):
                continue
            if ts >= since and s.get("temp") is not None:
                samples.append((ts, s["temp"]))
        samples.sort()
        if samples:
            actual[rid] = samples
    return actual

_MODEL_VERSION = None

def model_version() -> str:
    """Korte code-versie (git short-SHA) van de draaiende runner, zodat elk RMSE-punt aan een
    codeversie te koppelen is — "heeft iteratie N de fout echt verbeterd?" wordt dan een
    correlatie op de data zelf, geen git-archeologie. Prefereert `GITHUB_SHA` (gezet in de
    Action), valt terug op `git rev-parse`, dan 'unknown'. Gecachet per proces."""
    global _MODEL_VERSION
    if _MODEL_VERSION is not None:
        return _MODEL_VERSION
    sha = os.getenv("GITHUB_SHA")
    if sha:
        _MODEL_VERSION = sha[:7]
        return _MODEL_VERSION
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        _MODEL_VERSION = out.stdout.strip() if (out.returncode == 0 and out.stdout.strip()) else "unknown"
    except (OSError, subprocess.SubprocessError):
        _MODEL_VERSION = "unknown"
    return _MODEL_VERSION

def load_house() -> dict:
    with open(HOUSE_FILE, encoding="utf-8") as f:
        return json.load(f)

def load_window_data() -> dict:
    """Het raamadviseur-artefact (tado-kamertemps + -vocht, de grondwaarheid).

    Sinds de privacy-sweep (aug 2026) uit de privé artefact-gist i.p.v. de
    checkout — het droeg per kamer 48u temperatuur/vocht per kwartier, inclusief
    de badkamer (douche-/aanwezigheidsspoor). Zonder ARTEFACT_GIST_ID het oude
    lokale pad, dus tests en bootstrap blijven werken. Ontbreekt/onleesbaar →
    lege dict (elke consument degradeert daar al netjes op)."""
    wd = artefact_io.read_json("window_data.json", WINDOW_DATA, default=None)
    if not isinstance(wd, dict):
        print("[window_data] ontbreekt/onleesbaar — kamers leeg.")
        return {}
    return wd

def om_learned_from(wd: dict) -> dict | None:
    """De geleerde Open-Meteo-modelbias uit het raamadviseur-artefact (`om_bias`, zie
    `om_bias.py`) — de enige plek waar hij geleerd én gepersisteerd wordt, zodat beide
    tweelingen, de batch-fit en de nachtvoorspelling dezelfde correctie gebruiken.

    Nog niets geleerd (verse deploy, te weinig geverifieerde punten) → None, en dan
    gedraagt `build_timeline` zich exact als vóór deze correctie."""
    ob = (wd or {}).get("om_bias") or {}
    if not ob.get("night") and not ob.get("day"):
        return None
    return ob

def load_learned() -> dict:
    """De geleerde staat (params/RMSE/anomaly) — sinds de privatisering (aug 2026)
    uit de artefact-gist (ARTEFACT_GIST_ID, dezelfde als data.json/mowing_data.json),
    met LEARNED_FILE als lokaal/test-pad zolang het secret niet bestaat. Dit is de
    read-back die de online kalibratie van run naar run laat doorlopen — zonder
    gist-uitlezing zou elke run vanaf de priors herstarten."""
    d = artefact_io.read_json("vent_learned.json", LEARNED_FILE, default={})
    return d if isinstance(d, dict) else {}

def default_params(house: dict) -> dict:
    p = {k: PRIORS[k] for k in GLOBAL_PARAMS}
    for rid in house.get("rooms", {}):
        p[rid] = {k: PRIORS[k] for k in PER_ROOM_PARAMS}
    return p

def physics_rev_migration_needed(learned: dict) -> bool:
    """Is er geleerde staat van een oudere fysica-revisie? (Een lege/nieuwe staat hoeft
    niets te migreren — de defaults zijn al de priors.)"""
    return bool(learned.get("params")) and learned.get("physics_rev") != PHYSICS_REV

def merged_params(house: dict, learned: dict) -> dict:
    """Geleerde params aangevuld met priors voor nieuwe kamers/keys (additief, robuust).
    Gedeeld door main() en night_forecast.py zodat de merge-logica niet dubbel bestaat."""
    params = learned.get("params") or default_params(house)
    # Fossiel uit de tijd dat `cd` leerbaar was: de code rekent met de vaste CD-constante en
    # niets leest params["cd"] — strip 'm hier zodat hij niet eeuwig in de artefacten meerijdt.
    params.pop("cd", None)
    base = default_params(house)
    # Fysica-revisie-migratie (zie PHYSICS_REV): geleerde staat van een oudere revisie → álles
    # terug naar de priors. Hier (en niet alleen in main) zodat óók night_forecast.py nooit
    # oude-fysica-params op de nieuwe fysica loslaat.
    if physics_rev_migration_needed(learned):
        params = base
    for g in GLOBAL_PARAMS:
        params.setdefault(g, base[g])
    for rid in house.get("rooms", {}):
        params.setdefault(rid, base[rid])
        for k in PER_ROOM_PARAMS:
            params[rid].setdefault(k, PRIORS[k])
            # Klem op de per-kamer versmalde band uit house_model.json (`param_bounds`).
            # Dit is de poort waar een huismodel-vloer daadwerkelijk landt: de fit klemt
            # zelf al, maar geleerde staat van vóór de vloer (of een seed uit
            # tools/vent_seed.py) komt hier binnen en moet meteen worden opgetild —
            # anders draait de eerste run nog op de oude, te lage waarde.
            params[rid][k] = clamp_model_bounds(house, rid, k, params[rid][k])
    return params

def load_openings_log() -> list[dict]:
    gist_id = os.getenv("GIST_ID")
    token = os.getenv("GIST_TOKEN")
    if not gist_id or not token:
        print("[openings] geen GIST_ID/GIST_TOKEN — lege log.")
        return []
    data = gist_read_json(gist_id, OPENINGS_FILE, token=token,
                          default={}, label="openings")
    return data.get("log", []) if isinstance(data, dict) else []

def fetch_weather(lat: float, lon: float) -> dict:
    """Open-Meteo: verleden (voor het leren) + forecast, met wind incl. richting en de
    zoncomponenten voor de instraling door het glas. Coördinaten expliciet
    (house_location) — geen module-globals."""
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": ("temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,"
                   "wind_direction_10m,wind_gusts_10m,shortwave_radiation,"
                   "direct_radiation,diffuse_radiation"),
        "current": ("temperature_2m,relative_humidity_2m,wind_speed_10m,"
                    "wind_direction_10m,wind_gusts_10m,shortwave_radiation,direct_radiation"),
        "wind_speed_unit": "ms",
        "timezone": "Europe/Amsterdam",
        # Genoeg verleden voor het residu-venster (CALIB_WINDOW_H) plus de sim-only WARMUP_H
        # aanloop van de massaknoop, met marge.
        "past_days": 4, "forecast_days": 2,
    }
    data = get_json("https://api.open-meteo.com/v1/forecast", params,
                    timeout=25, label="open-meteo")
    h = data.get("hourly", {})
    times = [datetime.fromisoformat(t).replace(tzinfo=TZ) for t in h.get("time", [])]
    rows = []
    for i, t in enumerate(times):
        rows.append({
            "dt": t,
            "T_out": _get(h, "temperature_2m", i),
            "rh": _get(h, "relative_humidity_2m", i),
            "precip": _get(h, "precipitation", i) or 0.0,
            "wind_speed": _get(h, "wind_speed_10m", i) or 0.0,
            "wind_dir": _get(h, "wind_direction_10m", i) or 0.0,
            "gust": _get(h, "wind_gusts_10m", i) or 0.0,
            "shortwave": _get(h, "shortwave_radiation", i) or 0.0,
            "direct": _get(h, "direct_radiation", i) or 0.0,
            "diffuse": _get(h, "diffuse_radiation", i) or 0.0,
        })
    cur = data.get("current", {}) or {}
    return {"hourly": rows, "current": cur}

def _get(h: dict, key: str, i: int):
    arr = h.get(key) or []
    return arr[i] if i < len(arr) else None

def wu_solar_scale_factor(k: float | None, age_h: float,
                          decay_h: float = WU_SOLAR_SCALE_DECAY_H) -> float:
    """Per-stap herschaalfactor voor de instraling: blend tussen de WU/OM-zon-ratio `k` (geldig op
    nu) en 1.0 (pure OM) naar sample-leeftijd. `age_h` = uren vóór nu; **negatief = vooruit**.
    `k`=None → 1.0 (WU ontbrak; no-op).

    De uitdoving is SYMMETRISCH (`abs(age_h)`): `k` is een momentopname van de verhouding tussen
    wat de eigen pyranometer meet en wat het grid modelleert, en die verhouding veroudert
    vooruit net zo hard als achteruit. Zolang de vooruitblik 2 uur was, was dit cosmetisch (hij
    voedde alleen de trendpijl); met een 12-uurs voorspelling zou de bewolkingsverhouding van dít
    moment anders de hele nacht en de ochtend erna blijven gelden. Voor het verleden verandert er
    niets."""
    if k is None:
        return 1.0
    w = 1.0 if decay_h <= 0 else 1.0 - abs(age_h) / decay_h
    w = min(1.0, max(0.0, w))
    return 1.0 + (k - 1.0) * w

def build_timeline(house: dict, weather: dict, log: list[dict], now: datetime,
                   window_h: float, ctx: RunContext, *,
                   wu_solar_scale: float | None = None,
                   beam_iam: bool = False, end_h: float = 2.0,
                   om_learned: dict | None = None) -> list[dict]:
    """Bouw een 15-minuten-raster van drivers over het kalibratievenster t/m nu,
    plus een vooruitblik van `end_h` uur (default de korte 2u voor de afgeleide-
    temp-projectie; night_forecast.py rekt hem op tot morgenochtend). Per stap:
    T_out, per-kamer instraling (door het glas), wind, en de gerapporteerde
    openingen-toestand op dat moment.

    `om_learned` = de geleerde Open-Meteo-modelbias (zie `om_bias.py`). Open-Meteo leest
    op onze locatie structureel te warm, 's nachts het sterkst (+1,4 °C tussen 22–07u),
    en dít is het enige punt waar de buitentemperatuur de fysica binnenkomt — voor béíde
    tweelingen, hun batch-fit én de nachtvoorspelling. Zonder correctie absorbeert de
    kalibratie die modelfout in de kamer-params (twin 2's tarrering maakte 'm zichtbaar:
    een systematische warm-bias per kamer die 's nachts het grootst is), waarna élke
    voorspelling ermee besmet is. None → geen correctie, exact het oude gedrag.

    De **vochtigheid schuift mee**: bij een temperatuurcorrectie blijft de absolute
    dampinhoud behouden, dus de RH bij de gecorrigeerde temperatuur is hoger
    (`convert_rh`, dezelfde Magnus-redenering als `vent_rh` in de raamadviseur). Alleen
    de temperatuur corrigeren zou de tweeling stiekem uitdrogen — en twin 2 laat de
    RH-residuen meewegen in zijn fit."""
    rows = [r for r in weather["hourly"] if r["T_out"] is not None]
    if not rows:
        return []
    start = now - _timedelta_h(window_h)
    grid = []
    t = start
    end = now + _timedelta_h(end_h)
    lat, lon = ctx.lat, ctx.lon
    while t <= end:
        T_out = _interp_hourly(rows, t, "T_out")
        wx = {k: _interp_hourly(rows, t, k) for k in
              ("wind_speed", "wind_dir", "gust", "precip", "direct", "diffuse", "rh")}
        if om_learned and T_out is not None:
            # Modelbias eraf; de RH volgt bij behoud van dampinhoud (zie docstring).
            T_corr = T_out + om_bias.correction_for(t, om_learned)
            wx["rh"] = convert_rh(wx["rh"], T_out, T_corr)
            T_out = T_corr
        st = openings_at(log, t)            # gerapporteerde toestand op dit moment (incl. zonwering)
        # Representatieve zonpositie op het stap-midden (voor de rij/dashboard; `irr` hieronder
        # is een tijdsgemiddelde over de stap, geen momentopname).
        sun_az, sun_el = sun_position(lat, lon, (t + _timedelta_h(0.125)).astimezone(timezone.utc))
        # Tijdsgemiddelde instraling over [t, t+0.25h] via de midden-regel op SOLAR_SUBSTEPS
        # subintervallen: dempt de geometrie-aliasing van de snel-draaiende lage avondzon.
        irr = {rid: 0.0 for rid in house.get("rooms", {})}
        # Horizontale dak-instraling (W/m², onbeschaduwd, opake conductie — de absorptie zit in
        # ROOF_SOLAR_GAIN, niet in een glas-transmissie) voor de bovenste-verdieping-kamers.
        roof_rooms = [rid for rid, r in house.get("rooms", {}).items() if r.get("roof_m2", 0.0) > 0.0]
        irr_roof = {rid: 0.0 for rid in roof_rooms}
        # WU/OM-herschaling (stap 1): sterkst rond nu, uitdovend naar 1.0 verder terug. None → 1.0.
        sc = wu_solar_scale_factor(wu_solar_scale, (now - t).total_seconds() / 3600.0)
        for j in range(SOLAR_SUBSTEPS):
            ts = t + _timedelta_h(0.25 * (j + 0.5) / SOLAR_SUBSTEPS)
            s_az, s_el = sun_position(lat, lon, ts.astimezone(timezone.utc))
            s_direct = _interp_hourly(rows, ts, "direct")
            s_diffuse = _interp_hourly(rows, ts, "diffuse")
            if sc != 1.0:
                s_direct = (s_direct or 0.0) * sc
                s_diffuse = (s_diffuse or 0.0) * sc
            pw = per_window_solar(house, st, s_az, s_el, s_direct, s_diffuse, beam_iam)
            tot_room = {rid: 0.0 for rid in irr}
            for wid, w in house.get("windows", {}).items():
                rid = w.get("room")
                if rid in tot_room:
                    tot_room[rid] += pw[wid]
            for rid in irr:
                irr[rid] += tot_room[rid] / SOLAR_SUBSTEPS
            if roof_rooms:
                # Plat dak (tilt 0) → azimut-onafhankelijk; één waarde voor alle dak-kamers.
                roof_i = facade_irradiance(0.0, s_az, s_el, s_direct, s_diffuse, 0.0)
                for rid in roof_rooms:
                    irr_roof[rid] += roof_i / SOLAR_SUBSTEPS
        grid.append({"t": t, "T_out": T_out, "irr": irr, "irr_roof": irr_roof, "states": st,
                     "weather": wx, "dt": 900.0, "sun_az": sun_az, "sun_el": sun_el})
        t = t + _timedelta_h(0.25)
    return grid

# Empirische onzekerheidsband (docs/js/uncertainty.json, wekelijks ververst door
# twin-eval.yml): p10/p90 van (voorspeld − gemeten) per (kamer, horizon-uur). Twee
# consumenten citeren er één regel uit (de nachtvoorspelling en het koelplan), dus de
# loader + celkeuze wonen hier — een puntschatting suggereert een precisie die het
# model niet heeft. Ontbreekt het bestand → None, en de berichten zwijgen erover.
UNCERTAINTY_PATH = os.getenv("UNCERTAINTY_PATH", "docs/js/uncertainty.json")

def load_uncertainty(path: str | None = None) -> dict | None:
    try:
        with open(path or UNCERTAINTY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

def band_for(pred: float | None, hours_ahead: float, unc: dict | None,
             room: str) -> tuple[float, float] | None:
    """Band rond een voorspelling `pred` op `hours_ahead` vooruit: [pred − p90, pred − p10]
    uit de dichtstbijzijnde trusted uur-cel van `unc` (uncertainty.json-vorm). None als er
    geen band te geven is — dan zwijgt de consument erover (fail open)."""
    cells = ((unc or {}).get("bands") or {}).get(room) or {}
    trusted = {}
    for h, c in cells.items():
        try:
            if c.get("trusted") and c.get("p10") is not None and c.get("p90") is not None:
                trusted[int(h)] = c
        except (TypeError, ValueError, AttributeError):
            continue
    if not trusted or pred is None:
        return None
    h = min(trusted, key=lambda x: abs(x - hours_ahead))
    c = trusted[h]
    return (pred - c["p90"], pred - c["p10"])

def _routine_window_start(t: datetime, fh: int, th: int) -> datetime:
    """Start van het lopende routinevenster waar stap `t` in valt: de meest recente
    `from_h`-grens op of vóór `t` (bij een overnacht-venster kan dat gisteren zijn)."""
    start = t.replace(hour=fh, minute=0, second=0, microsecond=0)
    if fh > th and t.hour < th:      # over middernacht, ochtendkant → venster begon gisteren
        start -= timedelta(days=1)
    return start

def _last_report_at(log: list[dict], eid: str, before: datetime) -> datetime | None:
    """Tijdstip van de laatste log-melding die `eid` noemt, op of vóór `before`."""
    best = None
    for entry in log or []:
        if eid not in (entry.get("states") or {}):
            continue
        try:
            ts = datetime.fromisoformat(entry["t"])
        except (KeyError, TypeError, ValueError):
            continue
        if ts <= before and (best is None or ts > best):
            best = ts
    return best

def apply_routines(timeline: list[dict], house: dict, from_t: datetime | None = None,
                   log: list[dict] | None = None) -> list[dict]:
    """Dwing de vaste dagelijkse routines uit `house_model.json` (`routines`:
    element-id → {state, from_h, to_h}, lokale klokuren, from > to = over middernacht)
    af op elke timeline-stap (of alleen stappen ≥ `from_t`).

    Generalisatie van night_forecast's gordijnroutine (juli 2026): sommige standen —
    het verduisteringsgordijn dat elke avond om 19:00 dichtgaat — zijn een vast
    dagritme dat niemand in de openingen-log meldt. De 12u-vooruitblik van de tweeling
    nam tot aug 2026 de laatst gemelde stand voor de hele horizon aan (gordijn open,
    de hele nacht), terwijl de nachtvoorspelling de routine hardcodeerde; nu lezen
    beide dezelfde config. De kalibratie op het verleden blijft bewust op de gemelde
    log rijden — een routine dáár ook toepassen verandert de fit-inputs en is dus een
    te méten wijziging (re-seed + backtest), geen bijvangst.

    **Een expliciete melding ín het lopende routinevenster wint van de routine**
    (`log` meegeven): routines dekken wat níemand meldt, maar op de zeldzame avond dat
    de bewoner de deur wél openzet en dat meldt, mag de routine het eigen rapport niet
    overschrijven — anders spreken dashboard en koelplan-baseline de gemelde stand
    tegen (dezelfde klasse inconsistentie als de chip-vs-statustekst-bugs van P6).
    Een melding van vóór het venster (bv. gistermiddag) telt niet — dan geldt gewoon
    het dagritme. `log=None` → routine wint altijd (oude gedrag).

    Kopie; het origineel wordt niet gemuteerd. Sleutels die met "_" beginnen zijn
    commentaar (het house_model-patroon). Geen routines → de timeline zelf."""
    routines = {k: v for k, v in (house.get("routines") or {}).items()
                if not k.startswith("_") and isinstance(v, dict)}
    if not routines:
        return timeline
    out = []
    for step in timeline:
        if from_t is not None and step["t"] < from_t:
            out.append(step)
            continue
        t = step["t"]
        h = t.hour
        override = {}
        for eid, r in routines.items():
            fh, th = r.get("from_h"), r.get("to_h")
            if fh is None or th is None:
                continue
            active = (h >= fh or h < th) if fh > th else (fh <= h < th)
            if not active:
                continue
            if log is not None:
                reported = _last_report_at(log, eid, t)
                if reported is not None and reported >= _routine_window_start(t, fh, th):
                    continue          # expliciete melding in dít venster → log wint
            override[eid] = r.get("state", "dicht")
        out.append({**step, "states": {**step["states"], **override}} if override else step)
    return out

def _timedelta_h(h: float):
    return timedelta(hours=h)

def _interp_hourly(rows: list[dict], t: datetime, key: str) -> float:
    """Lineaire interpolatie van een uurlijkse driver-reeks op tijdstip t."""
    if t <= rows[0]["dt"]:
        return rows[0].get(key) or 0.0
    if t >= rows[-1]["dt"]:
        return rows[-1].get(key) or 0.0
    for r0, r1 in zip(rows, rows[1:]):
        if r0["dt"] <= t <= r1["dt"]:
            v0, v1 = r0.get(key) or 0.0, r1.get(key) or 0.0
            # span <= 0 → v0 (zelfde guard als window_advisor._interp_out_corr)
            span = (r1["dt"] - r0["dt"]).total_seconds()
            if span <= 0:
                return v0
            f = (t - r0["dt"]).total_seconds() / span
            return v0 + f * (v1 - v0)
    return rows[-1].get(key) or 0.0


# ── RunContext-opbouw ────────────────────────────────────────────────────────────────

def house_location(house: dict) -> tuple[float, float]:
    """Locatie uit het huismodel, met de gedeelde Utrecht-Oost-constante als fallback."""
    loc = house.get("location", {}) or {}
    return (float(loc.get("lat", shared_const.LATITUDE)),
            float(loc.get("lon", shared_const.LONGITUDE)))


def make_context(house: dict, weather: dict, now: datetime) -> RunContext:
    """Bouw de run-context: locatie uit het huismodel plus de twee trage ankers uit de
    weer-historie. Buur-anker met het zomerplafond erop (simulate legt daar per tijdstap
    de nachtcap overheen via neighbor_at); bodem-anker ~30-daags gedempt."""
    hourly = (weather or {}).get("hourly", [])
    lat, lon = house_location(house)
    return RunContext(
        lat=lat, lon=lon,
        neighbor_temp=min(vp.NEIGHBOR_SUMMER_CAP,
                          vp.neighbor_temp_estimate(hourly, now)),
        ground_temp=vp.ground_temp_estimate(hourly, now))


# ── WU-buiten-nu-verfijning ──────────────────────────────────────────────────────────

def refine_outside_now(weather: dict) -> tuple[float | None, float | None]:
    """Verfijn de buiten-nu-uitlezing met het eigen WU-station (zoals soil/window): de
    station-temp + RH zijn lokaler dan het Open-Meteo-grid. De temp krijgt de wu_bias-
    stralingscorrectie (driver = eigen pyranometer, Open-Meteo-zon als fallback).
    Bewust NIET van WU overgenomen: wind (het station meet die onbetrouwbaar) en de
    zon-instraling voor de glasfysica (die heeft de direct/diffuus-split nodig die WU
    niet levert; WU-zon dient enkel als bias-driver + glas-drive-herschaling). Alleen
    de "nu"-uitlezing wordt verfijnd — de historische timeline die de kalibratie voedt
    blijft Open-Meteo (WU levert geen uur-historie; de ground truth zijn de tado-temps).

    Muteert `weather` in place (current + wu_solar_scale) en geeft
    (wu_solar_scale, out_rh_temp) terug — de rauwe temp bij de gebruikte RH (één
    consistent Magnus-sensorpaar voor convert_rh)."""
    cur = weather.get("current", {}) or {}
    out_rh_temp = cur.get("temperature_2m")   # rauwe temp bij de gebruikte RH (één sensorpaar)
    wu_temp, wu_solar, wu_humid = fetch_wu_current_temp()
    wu_solar_scale = None   # WU/OM glas-drive-herschaling; None → pure Open-Meteo
    if wu_temp is not None:
        solar_now = wu_solar if wu_solar is not None else cur.get("shortwave_radiation")
        src = "wu" if wu_solar is not None else "om"
        cur["temperature_2m"] = round(correct_temp(wu_temp, solar_now), 1)
        cur["outside_source"] = "wu"
        out_rh_temp = wu_temp                 # rauwe WU-temp hoort bij de WU-RH (Magnus-paar)
        if wu_humid is not None:
            cur["relative_humidity_2m"] = wu_humid
        print(f"[buiten] WU: {wu_temp}°C → gecorrigeerd {cur['temperature_2m']}°C "
              f"(zon {solar_now} W/m², bron {src}); RH {wu_humid}%")
        # WU-gemeten-zon herschaling van de glas-drive rond nu: k = WU_global/OM_global.
        om_solar_now = cur.get("shortwave_radiation")
        if (wu_solar is not None and om_solar_now and om_solar_now >= WU_SOLAR_MIN_WM2
                and wu_solar >= WU_SOLAR_MIN_WM2):
            wu_solar_scale = min(WU_SOLAR_SCALE_MAX,
                                 max(WU_SOLAR_SCALE_MIN, wu_solar / om_solar_now))
            print(f"[zon] WU/OM glas-drive-herschaling k={wu_solar_scale:.2f} "
                  f"(WU {wu_solar}, OM {om_solar_now} W/m²)")
    else:
        cur["outside_source"] = "open-meteo"
        print("[buiten] WU niet beschikbaar → Open-Meteo buiten-nu.")
    weather["current"] = cur
    weather["wu_solar_scale"] = wu_solar_scale
    return wu_solar_scale, out_rh_temp


# ── Maand-shards (trainingsset; geërfd van tweeling 2) ──────────────────────────────
#
# Sinds de privacy-assessment (aug 2026) leven de shards als
# `twin2_history_<YYYY-MM>.json` in de privé GIST_ID-gist i.p.v. als gecommitte
# bestanden: kamer-temp/-vocht per kwartier is gedragsdata (een meerdaagse
# amplitude-inzakking over alle kamers leest als afwezigheid) en hoort niet in
# publieke git — zie de PRIVACY-banner in CLAUDE.md. Zelfde gist en dezelfde
# maand-shard-mechaniek als het openingen-archief hieronder. De lokale dir blijft
# bestaan als terugval (bootstrap/tests, env-override `VENT_HISTORY_DIR`) én als
# overlay: `load_dataset` leest Gist ∪ lokale dir, lokaal wint per tijdstip —
# zo kan twin-eval's ERA5-verversing zonder Gist-creds (bewust: één Gist-schrijver,
# de kwartierloop) een in-job weer-overlay leveren zonder de Gist te raken.

_HISTORY_DIR_DEFAULT = "data/twin2_history"
HISTORY_DIR          = os.getenv("VENT_HISTORY_DIR", _HISTORY_DIR_DEFAULT)
HISTORY_GIST_PREFIX  = "twin2_history_"

def _history_name(month: str) -> str:
    return f"{HISTORY_GIST_PREFIX}{month}.json"

def _history_gist_active() -> bool:
    """Gist-modus alleen op het onaangepaste default-pad mét creds. Een expliciete
    dir-override (VENT_HISTORY_DIR, of een gemonkeypatchte HISTORY_DIR — alle
    shard-tests doen dat) wint altijd, zodat ambient dev-creds een gesandboxte
    test of offline tool nooit stilletjes naar de echte Gist laten schrijven."""
    if HISTORY_DIR != _HISTORY_DIR_DEFAULT:
        return False
    gist_id, token = _gist_creds()
    return bool(gist_id and token)

def _shard_path(month: str) -> str:
    return os.path.join(HISTORY_DIR, f"{month}.json")

def _load_shard(month: str) -> dict:
    empty = {"schema": 1, "month": month, "rooms": {}, "weather": []}
    if _history_gist_active():
        gist_id, token = _gist_creds()
        # Bewust read_file (raist bij netwerkfouten) en niet read_json: een
        # graceful default als basis voor een read-modify-write zou de Gist-maand
        # bij een hikje overschrijven met alleen de verse samples — stil
        # dataverlies. De raise landt in het shard-vangnet van de runner, die
        # deze run dan overslaat. Kapotte JSON → verse basis (pariteit met het
        # lokale JSONDecodeError-pad).
        content = gist_io.read_file(gist_id, _history_name(month), token=token)
        if content is not None:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass
        return empty
    try:
        with open(_shard_path(month), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Bewust geen "openings"-default meer: de openingen-snapshots leven sinds de
        # privacy-scrub in het privé Gist-archief, niet in de gecommitte shards.
        return empty

def _write_shard(shard: dict) -> None:
    body = json.dumps(shard, ensure_ascii=False, separators=(",", ":"))
    if _history_gist_active():
        _gist_write_files({_history_name(shard["month"]): body})
        return
    os.makedirs(HISTORY_DIR, exist_ok=True)
    with open(_shard_path(shard["month"]), "w", encoding="utf-8") as f:
        f.write(body)

def shard_excluded_rooms(house: dict | None) -> set[str]:
    """De window_data-kamernamen die niet in de gecommitte shards horen —
    de kamers met `exclude_from_shards` in het huismodel (privacy-sweep aug 2026).

    Generieke vlag, geen kamer-specifieke code: zelfde patroon als
    `exclude_from_fit`/`hide_in_charts`. Vertaalt de huismodel-id naar de
    gepubliceerde naam via `from_window_data`, want de shards zijn op die
    namen gesleuteld. Geen huismodel → niets uitgesloten (fail open)."""
    return {wd_name for cfg in ((house or {}).get("rooms") or {}).values()
            if cfg.get("exclude_from_shards")
            and (wd_name := cfg.get("from_window_data"))}


def append_history_shard(wd: dict, log: list[dict], now: datetime,
                         house: dict | None = None) -> int:
    """Append verse tado-samples aan de maand-shard(s). Idempotent: alleen samples
    nieuwer dan het laatst opgeslagen per kamer worden toegevoegd — een tweede
    aanroep is een no-op. Geeft #toegevoegde samples.

    De openingen-snapshots gaan sinds de privacy-scrub (aug 2026) bewust NIET meer
    in de gecommitte shards: elke rij was een minuut-gestempeld bewijs van een
    menselijke handeling, blijvend in de publieke git-historie. Het blijvende
    archief (bescherming tegen de browser-trim van de live log) leeft nu in de
    privé Gist — zie `append_openings_archive`/`load_openings_archive`.

    Om dezelfde reden slaat de privacy-sweep (aug 2026) de kamers met
    `exclude_from_shards` over: badkamervocht per kwartier tekent het
    douche-/aanwezigheidsritme. `house` weglaten → niets uitgesloten."""
    added = 0
    skip = shard_excluded_rooms(house)
    by_month: dict[str, dict] = {}

    def shard_for(ts: datetime) -> dict:
        month = ts.strftime("%Y-%m")
        if month not in by_month:
            by_month[month] = _load_shard(month)
        return by_month[month]

    for name, rd in (wd.get("rooms", {}) or {}).items():
        if name in skip:
            continue
        for s in rd.get("history", []):
            try:
                ts = datetime.fromisoformat(s["t"])
            except (ValueError, TypeError, KeyError):
                continue
            if s.get("temp") is None:
                continue
            shard = shard_for(ts)
            slot = shard["rooms"].setdefault(name, {"ts": [], "temp": [], "hum": [], "heat": []})
            epoch = int(ts.timestamp())
            if slot["ts"] and epoch <= slot["ts"][-1]:
                continue
            slot["ts"].append(epoch)
            slot["temp"].append(int(round(s["temp"] * 10)))
            slot["hum"].append(int(round(s["hum"])) if s.get("hum") is not None else None)
            slot["heat"].append(1 if s.get("heat") else 0)
            added += 1
    for shard in by_month.values():
        _write_shard(shard)
    return added


def _iter_history_shards():
    """Alle maand-shards als dicts: eerst de Gist (indien actief), dan de lokale
    dir. `load_dataset` merge't per tijdstip last-writer-wins, dus een lokale rij
    wint van de Gist-kopie — precies wat twin-eval's in-job ERA5-overlay nodig
    heeft (die stap draait bewust zónder Gist-creds; zie de sectie-kop). Een
    Gist-leesfout is hier graceful: de consumenten zijn evaluatietools, "minder
    data" is daar een melding waard maar geen crash."""
    if _history_gist_active():
        gist_id, token = _gist_creds()
        try:
            files = gist_io.read_files(gist_id, token=token)
        except Exception as e:
            from notify import sanitize_error
            print(f"[shards] Gist lezen mislukt: {sanitize_error(e)}")
            files = {}
        for name in sorted(files):
            if not (name.startswith(HISTORY_GIST_PREFIX) and name.endswith(".json")):
                continue
            try:
                yield json.loads(files[name])
            except json.JSONDecodeError:
                continue
    for path in sorted(glob.glob(os.path.join(HISTORY_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                yield json.load(f)
        except (OSError, json.JSONDecodeError):
            continue


def migrate_history_shards() -> int:
    """Eenmalige, zelf-uitvoerende migratie (privacy-assessment aug 2026): staan
    er nog lokale (gecommitte) twin2-maand-shards terwijl de Gist-modus actief
    is, verhuis ze dan unie-gemerged naar de privé Gist en verwijder de lokale
    bestanden — pas ná een read-back die bevestigt dat élk kamersample en élke
    weer-rij in de Gist-kopie staat. De runner-workflow commit de verwijdering
    daarna gewoon mee (de add-loop dekt de dir al). Idempotent: elke faalroute
    laat de lokale bestanden staan en herkanst de volgende run; de unie maakt de
    volgorde t.o.v. append_history_shard onverschillig. Geeft #gemigreerde
    maandbestanden; 0 = niets te doen of migratie (nog) niet mogelijk."""
    if not _history_gist_active():
        return 0
    paths = sorted(glob.glob(os.path.join(HISTORY_DIR, "*.json")))
    if not paths:
        return 0
    gist_id, token = _gist_creds()
    local: dict[str, dict] = {}
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                shard = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        local[shard.get("month") or os.path.basename(path)[:-len(".json")]] = shard
    if not local:
        return 0

    def _merge(local_shard: dict, gist_shard: dict) -> dict:
        # Unie per sleutel; de Gist-kopie (nieuwere appends) wint bij overlap.
        out = {**local_shard, **gist_shard}
        rooms: dict[str, dict] = {}
        for name in set(local_shard.get("rooms") or {}) | set(gist_shard.get("rooms") or {}):
            slot: dict[int, tuple] = {}
            for src in (local_shard, gist_shard):        # gist als laatste → wint
                cols = (src.get("rooms") or {}).get(name) or {}
                ts = cols.get("ts") or []
                for i, e in enumerate(ts):
                    slot[e] = tuple((cols.get(k) or [None] * len(ts))[i]
                                    for k in ("temp", "hum", "heat"))
            order = sorted(slot)
            rooms[name] = {"ts": order,
                           "temp": [slot[e][0] for e in order],
                           "hum":  [slot[e][1] for e in order],
                           "heat": [slot[e][2] for e in order]}
        out["rooms"] = rooms
        weather = {r["dt"]: r for src in (local_shard, gist_shard)
                   for r in (src.get("weather") or []) if r.get("dt")}
        out["weather"] = [weather[k] for k in sorted(weather)]
        return out

    def _read_gist_shard(month: str) -> dict | None:
        content = gist_io.read_file(gist_id, _history_name(month), token=token)
        if content is None:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    try:
        to_write = {}
        for month, shard in local.items():
            gist_shard = _read_gist_shard(month)
            merged = _merge(shard, gist_shard) if gist_shard else shard
            to_write[_history_name(month)] = json.dumps(
                merged, ensure_ascii=False, separators=(",", ":"))
        _gist_write_files(to_write)
        # Read-back-verificatie vóór het verwijderen (verse GET).
        for month, shard in local.items():
            after = _read_gist_shard(month) or {}
            for name, cols in (shard.get("rooms") or {}).items():
                have = set(((after.get("rooms") or {}).get(name) or {}).get("ts") or [])
                if not set(cols.get("ts") or []) <= have:
                    print("[shards] read-back mist samples — lokale bestanden blijven staan.")
                    return 0
            have_w = {r.get("dt") for r in after.get("weather") or []}
            if not {r.get("dt") for r in shard.get("weather") or [] if r.get("dt")} <= have_w:
                print("[shards] read-back mist weer-uren — lokale bestanden blijven staan.")
                return 0
    except Exception as e:
        from notify import sanitize_error
        print(f"[shards] migratie mislukt: {sanitize_error(e)} — lokale bestanden blijven staan.")
        return 0
    for path in paths:
        os.remove(path)
    print(f"[shards] {len(paths)} maand-bestand(en) naar de privé Gist gemigreerd.")
    return len(paths)


# ── Openingen-archief (privé Gist, maand-geshard) ────────────────────────────────────
#
# De live log (`house_openings.json`) wordt door de browser getrimd tot ~500 snapshots;
# het blijvende archief stond tot aug 2026 als `openings[]` in de gecommitte
# twin2-shards — publiek, voor altijd, met het tijdstip van elke handmatige melding.
# Het archief leeft nu als `house_openings_<YYYY-MM>.json` in dezelfde privé Gist
# (schrijver: uitsluitend de vent-action — de browser schrijft alleen de live log,
# dus één schrijver per bestand blijft gelden). Maand-shards i.p.v. één groeiend
# bestand: de Gist-API kapt content boven ~1 MB af en een enkel bestand zou die
# grens binnen maanden bereiken (gemeten ~77–134 kB/maand); gist_io volgt bij
# truncation de raw_url, maar klein blijven is de echte bescherming.
#
# Env-override `VENT_OPENINGS_ARCHIVE_DIR`: lees/schrijf lokale bestanden met
# dezelfde namen (tests + offline tools zonder secrets).

OPENINGS_ARCHIVE_PREFIX = "house_openings_"


def _archive_dir() -> str | None:
    return os.getenv("VENT_OPENINGS_ARCHIVE_DIR")


def _archive_name(month: str) -> str:
    return f"{OPENINGS_ARCHIVE_PREFIX}{month}.json"


def _gist_creds() -> tuple[str | None, str | None]:
    return os.getenv("GIST_ID"), (os.getenv("GIST_TOKEN") or os.getenv("GH_TOKEN"))


def _gist_write_files(files: dict[str, str]) -> None:
    """Multi-file PATCH naar de GIST_ID-gist (archief-bestanden only). Raist bij
    fouten — de aanroepers zitten in een vangnet-try van de runner."""
    gist_id, token = _gist_creds()
    r = requests.patch(f"https://api.github.com/gists/{gist_id}",
                       headers={"Accept": "application/vnd.github+json",
                                "Authorization": f"Bearer {token}"},
                       json={"files": {n: {"content": c} for n, c in files.items()}},
                       timeout=30)
    r.raise_for_status()


def _norm_entries(raw) -> dict[str, dict]:
    """{t: entry} uit een archief-/logvorm; onbruikbare rijen vallen stil af."""
    out = {}
    for e in (raw or []):
        t = e.get("t") if isinstance(e, dict) else None
        if t:
            out[t] = {"t": t, "states": e.get("states", {}) or {}}
    return out


def _read_archive_files() -> dict[str, dict[str, dict]]:
    """{maand: {t: entry}} van alle bestaande archief-bestanden (dir of Gist).
    Zonder creds (en zonder dir-override) → lege dict + één vaste melding."""
    adir = _archive_dir()
    out: dict[str, dict[str, dict]] = {}
    if adir:
        for path in sorted(glob.glob(os.path.join(adir, f"{OPENINGS_ARCHIVE_PREFIX}*.json"))):
            month = os.path.basename(path)[len(OPENINGS_ARCHIVE_PREFIX):-len(".json")]
            try:
                with open(path, encoding="utf-8") as f:
                    out[month] = _norm_entries(json.load(f).get("log"))
            except (OSError, json.JSONDecodeError):
                continue
        return out
    gist_id, token = _gist_creds()
    if not gist_id or not token:
        print("[archief] geen Gist-creds — openingen-archief niet beschikbaar.")
        return {}
    try:
        files = gist_io.read_files(gist_id, token=token)
    except Exception as e:
        from notify import sanitize_error
        print(f"[archief] lezen mislukt: {sanitize_error(e)}")
        return {}
    for name, content in files.items():
        if not (name.startswith(OPENINGS_ARCHIVE_PREFIX) and name.endswith(".json")):
            continue
        month = name[len(OPENINGS_ARCHIVE_PREFIX):-len(".json")]
        try:
            out[month] = _norm_entries(json.loads(content).get("log"))
        except (json.JSONDecodeError, AttributeError):
            continue
    return out


def _write_archive_months(months: dict[str, dict[str, dict]]) -> None:
    files = {}
    for month, entries in months.items():
        body = {"schema": 1, "month": month,
                "log": [entries[t] for t in sorted(entries)]}
        files[_archive_name(month)] = json.dumps(body, ensure_ascii=False,
                                                 separators=(",", ":"))
    if not files:
        return
    adir = _archive_dir()
    if adir:
        os.makedirs(adir, exist_ok=True)
        for name, content in files.items():
            with open(os.path.join(adir, name), "w", encoding="utf-8") as f:
                f.write(content)
        return
    _gist_write_files(files)


def append_openings_archive(log: list[dict]) -> int:
    """Archiveer nieuwe live-log-entries blijvend (maand-geshard, idempotent op `t`).
    Geeft #nieuw gearchiveerde entries; 0 bij niets nieuws of ontbrekende creds."""
    new_by_month: dict[str, dict[str, dict]] = {}
    for t, entry in _norm_entries(log).items():
        try:
            month = datetime.fromisoformat(t).strftime("%Y-%m")
        except ValueError:
            continue
        new_by_month.setdefault(month, {})[t] = entry
    if not new_by_month:
        return 0
    existing = _read_archive_files()
    if not existing and not _archive_dir():
        gist_id, token = _gist_creds()
        if not gist_id or not token:
            return 0
    changed: dict[str, dict[str, dict]] = {}
    added = 0
    for month, entries in new_by_month.items():
        cur = dict(existing.get(month, {}))
        fresh = {t: e for t, e in entries.items() if t not in cur}
        if fresh:
            cur.update(fresh)
            changed[month] = cur
            added += len(fresh)
    if changed:
        _write_archive_months(changed)
    return added


def migrate_shard_openings() -> int:
    """Eenmalige, zelf-uitvoerende migratie: staan er nog `openings[]` in de lokale
    twin2-shards, archiveer ze dan naar de privé Gist en strip ze uit de shard-
    bestanden — pas ná een read-back die bevestigt dat élke t in het archief staat
    (de shards waren de enige plek die de browser-trim overleefde; er mag geen
    entry verloren gaan). De runner commit de gestripte shards daarna gewoon mee.
    Geeft #gestripte entries; 0 = niets te doen of migratie (nog) niet mogelijk."""
    shard_paths = sorted(glob.glob(os.path.join(HISTORY_DIR, "*.json")))
    pending: dict[str, dict[str, dict]] = {}
    for path in shard_paths:
        try:
            with open(path, encoding="utf-8") as f:
                shard = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        entries = _norm_entries(shard.get("openings"))
        if entries:
            pending.setdefault(shard.get("month") or os.path.basename(path)[:-5], {}) \
                   .update(entries)
    if not pending:
        return 0
    existing = _read_archive_files()
    gist_id, token = _gist_creds()
    if not existing and not _archive_dir() and (not gist_id or not token):
        return 0                       # geen archief bereikbaar → shards ongemoeid laten
    to_write = {}
    for month, entries in pending.items():
        cur = dict(existing.get(month, {}))
        cur.update({t: e for t, e in entries.items() if t not in cur})
        to_write[month] = cur
    _write_archive_months(to_write)
    # Read-back-verificatie vóór het strippen: elke te migreren t moet er nu staan.
    after = _read_archive_files()
    for month, entries in pending.items():
        if not set(entries) <= set(after.get(month, {})):
            print("[archief] read-back mist entries — shards blijven ongemoeid.")
            return 0
    stripped = 0
    for path in shard_paths:
        try:
            with open(path, encoding="utf-8") as f:
                shard = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if shard.get("openings"):
            stripped += len(shard["openings"])
        if "openings" in shard:
            del shard["openings"]
            _write_shard(shard)
    return stripped


def load_openings_archive(include_live: bool = True) -> list[dict]:
    """Het volledige openingen-archief als chronologische log (t-gededupliceerd),
    optioneel gemerged met de actuele live log — de vorm die `load_dataset` en de
    offline tools verwachten."""
    merged: dict[str, dict] = {}
    for entries in _read_archive_files().values():
        merged.update(entries)
    if include_live:
        merged.update(_norm_entries(load_openings_log()))
    return [merged[t] for t in sorted(merged)]

def load_dataset(house: dict) -> dict:
    """Merge alle maand-shards tot één trainingsset: per kamer-id de (t, temp)- en
    (t, RH)-samples (gededupliceerd op tijdstip), de stook-tijdstippen, de weer-rijen
    (fetch_weather-vorm) en de samengevoegde openingen-log."""
    name_to_rid = {r.get("from_window_data"): rid
                   for rid, r in house.get("rooms", {}).items() if r.get("from_window_data")}
    samples: dict[str, dict[int, tuple]] = {}
    weather_rows: dict[str, dict] = {}
    log_by_t: dict[str, dict] = {}
    for shard in _iter_history_shards():
        for name, cols in (shard.get("rooms") or {}).items():
            rid = name_to_rid.get(name)
            if not rid:
                continue
            slot = samples.setdefault(rid, {})
            ts_arr = cols.get("ts") or []
            for i, epoch in enumerate(ts_arr):
                temp = (cols.get("temp") or [None] * len(ts_arr))[i]
                hum = (cols.get("hum") or [None] * len(ts_arr))[i]
                heat = (cols.get("heat") or [0] * len(ts_arr))[i]
                if temp is None:
                    continue
                slot[epoch] = (temp / 10.0, hum, bool(heat))
        for row in shard.get("weather") or []:
            if row.get("dt"):
                weather_rows[row["dt"]] = row
        for entry in shard.get("openings") or []:
            # Legacy: shards van vóór de archief-migratie (of lokale fixtures) dragen
            # de openingen nog zelf; de migratie strip't ze na verificatie.
            if entry.get("t"):
                log_by_t[entry["t"]] = entry
    actual, actual_rh, heat_on = {}, {}, {}
    for rid, slot in samples.items():
        t_list = sorted(slot)
        actual[rid] = [(datetime.fromtimestamp(e, TZ), slot[e][0]) for e in t_list]
        rh_list = [(datetime.fromtimestamp(e, TZ), float(slot[e][1]))
                   for e in t_list if slot[e][1] is not None]
        if rh_list:
            actual_rh[rid] = rh_list
        hs = {datetime.fromtimestamp(e, TZ) for e in t_list if slot[e][2]}
        if hs:
            heat_on[rid] = hs
    rows = []
    for iso in sorted(weather_rows):
        r = dict(weather_rows[iso])
        r["dt"] = datetime.fromisoformat(iso)
        rows.append(r)
    # Openingen: legacy shard-rijen (hierboven) ∪ het privé archief ∪ de live log.
    # Zonder Gist-creds én zonder dir-override blijft alleen de legacy-inhoud over —
    # de tools melden dat zelf via de vaste archief-regel.
    for entry in load_openings_archive():
        log_by_t[entry["t"]] = entry
    log = [log_by_t[t] for t in sorted(log_by_t)]
    return {"actual": actual, "actual_rh": actual_rh, "heat_on": heat_on,
            "weather_rows": rows, "log": log}

def fetch_weather_archive(lat: float, lon: float, start: date, end: date) -> list[dict]:
    """Historische uur-drivers in exact de fetch_weather-rijvorm: Open-Meteo-archief
    (ERA5, ~2–5 dagen achterstand) + de forecast-API met past_days voor de verse
    staart. Dezelfde variabelen als am.fetch_weather zodat am.build_timeline ze
    ongewijzigd consumeert."""
    hourly_vars = ("temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,"
                   "wind_direction_10m,wind_gusts_10m,shortwave_radiation,"
                   "direct_radiation,diffuse_radiation")

    def _rows(data: dict) -> list[dict]:
        h = data.get("hourly", {})
        times = [datetime.fromisoformat(t).replace(tzinfo=TZ) for t in h.get("time", [])]
        out = []
        for i, t in enumerate(times):
            out.append({"dt": t,
                        "T_out": _get(h, "temperature_2m", i),
                        "rh": _get(h, "relative_humidity_2m", i),
                        "precip": _get(h, "precipitation", i) or 0.0,
                        "wind_speed": _get(h, "wind_speed_10m", i) or 0.0,
                        "wind_dir": _get(h, "wind_direction_10m", i) or 0.0,
                        "gust": _get(h, "wind_gusts_10m", i) or 0.0,
                        "shortwave": _get(h, "shortwave_radiation", i) or 0.0,
                        "direct": _get(h, "direct_radiation", i) or 0.0,
                        "diffuse": _get(h, "diffuse_radiation", i) or 0.0})
        return out

    base = {"latitude": lat, "longitude": lon, "hourly": hourly_vars,
            "wind_speed_unit": "ms", "timezone": "Europe/Amsterdam"}
    rows = _rows(get_json("https://archive-api.open-meteo.com/v1/archive",
                          {**base, "start_date": start.isoformat(), "end_date": end.isoformat()},
                          timeout=45, label="open-meteo-archief"))
    rows = [r for r in rows if r["T_out"] is not None]
    last = rows[-1]["dt"].date() if rows else (start - timedelta(days=1))
    if last < end:
        # ERA5-staart ontbreekt → vul bij uit de forecast-API (past_days ≤ 92).
        need_days = min(92, (date.today() - last).days + 1)
        fresh = _rows(get_json("https://api.open-meteo.com/v1/forecast",
                               {**base, "past_days": need_days, "forecast_days": 1},
                               timeout=30, label="open-meteo-staart"))
        cutoff = rows[-1]["dt"] if rows else None
        rows += [r for r in fresh if r["T_out"] is not None
                 and (cutoff is None or r["dt"] > cutoff)]
    return rows

def refresh_shard_weather(rows: list[dict], overwrite: bool = True) -> int:
    """Merge weer-rijen in hun maand-shards, gesleuteld op `dt`. Geeft #nieuwe uur-rijen.

    **Mergen, niet vervangen** — dit was een echte gat-bron: de oude versie zette
    `shard["weather"]` gelijk aan précies de aangeleverde rijen, dus een fetch met een
    smaller bereik (of een half-mislukte staart-fallback) wíste de rest van die maand.
    Gecombineerd met "alleen de wekelijkse batch schrijft weer" leverde dat een shard op
    waarvan het weer op 2026-07-16 stopte terwijl de kamerdata tot 07-28 liep — de hele
    hete twee weken viel buiten elke fit (gediagnosticeerd juli 2026). Mergen maakt het
    shard-weer monotoon groeiend en immuun voor een smaller venster of een door de
    `-X theirs`-merge van de kwartierloop geklobberde batch-commit.

    `overwrite=True` (batch/backfill): het ERA5-archief wint van een eerder ingevulde
    forecast-staart. `overwrite=False` (kwartierrun): alléén gaten vullen, zodat een
    archief-rij nooit terug-degradeert naar een forecast-waarde."""
    by_month: dict[str, list[dict]] = {}
    for r in rows:
        by_month.setdefault(r["dt"].strftime("%Y-%m"), []).append(r)
    added = 0
    for month, mrows in by_month.items():
        shard = _load_shard(month)
        merged = {r["dt"]: r for r in shard.get("weather") or [] if r.get("dt")}
        for r in mrows:
            iso = r["dt"].isoformat()
            if iso in merged and not overwrite:
                continue
            added += iso not in merged
            merged[iso] = {**r, "dt": iso}
        shard["weather"] = [merged[k] for k in sorted(merged)]
        _write_shard(shard)
    return added

def append_shard_weather(weather: dict, now: datetime) -> int:
    """Vul het shard-weer bij uit de drivers die de kwartierrun tóch al ophaalt
    (`am.fetch_weather` levert `past_days=4` aan verleden). Geeft #nieuwe uur-rijen.

    Alléén verstreken uren: de forecast-staart is gemodelleerde toekomst en hoort niet
    als grondwaarheid in de trainingsset. Alléén gaten vullen (`overwrite=False`), dus
    waar de batch het ERA5-archief al heeft neergezet blijft dat leidend.

    Waarom de kwartierrun dit óók doet terwijl het weer "van de batch" is: met één
    wekelijkse schrijver is elk gemist of geklobberd batch-venster een blijvend gat in
    de trainingsset. Met een rollende 4-daagse overlap elke 15 minuten kan zo'n gat niet
    meer ontstaan, en het kost bytes per run — hetzelfde argument als voor de
    kamer-samples in `append_history_shard`."""
    rows = [r for r in (weather.get("hourly") or [])
            if r.get("dt") is not None and r["dt"] <= now and r.get("T_out") is not None]
    return refresh_shard_weather(rows, overwrite=False) if rows else 0

# ---------------------------------------------------------------------------
# Forecast-log (data/forecast_log): de weersvoorspelling zélf als meetobject.
#
# Elke accuraatheid van de tweeling is tot nu toe gemeten onder een perfecte-
# forecast-aanname (tools/horizon_backtest.py speelt hindcast-weer af) — de
# assessments noemen dat "de grootste openstaande onzekerheid". Dit log legt
# vast wat Open-Meteo op uitgiftemoment U voor doel-uur T vóórspelde, zodat de
# backtest na een paar weken accumulatie ook op échte forecasts kan draaien
# (`--weather forecast`) en het gat meetbaar wordt. Rauwe modelwaarden — de
# om_bias-correctie blijft een aparte, reproduceerbare laag in build_timeline.
# ---------------------------------------------------------------------------

FORECAST_LOG_DIR = os.getenv("VENT_FORECAST_LOG_DIR", "data/forecast_log")
FORECAST_ISSUE_EVERY_H = 3.0   # max één snapshot per 3 klokuren (spiegelt de backtest-stride)

# Kolom → (fetch_weather-veld, schaalfactor). Compact int-kolomformaat, zelfde
# afweging als temp×10 in de twin2-shards: dit wordt elke run gecommit.
_FC_COLS = (("T", "T_out", 10), ("rh", "rh", 1), ("pr", "precip", 100),
            ("ws", "wind_speed", 10), ("wd", "wind_dir", 1), ("gu", "gust", 10),
            ("sw", "shortwave", 1), ("dr", "direct", 1), ("df", "diffuse", 1))

def _forecast_shard_path(month: str) -> str:
    return os.path.join(FORECAST_LOG_DIR, f"{month}.json")

def _load_forecast_shard(month: str) -> dict:
    try:
        with open(_forecast_shard_path(month), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"schema": 1, "month": month, "snapshots": []}

def append_forecast_shard(weather: dict, now: datetime) -> int:
    """Log de zojuist opgehaalde Open-Meteo-forecast (het lopende uur + alle toekomstige
    uren) als compact kolom-snapshot in de maand-shard van het uitgiftemoment. Hooguit
    één snapshot per `FORECAST_ISSUE_EVERY_H` klokuren — de kwartierruns daartussen zijn
    een no-op, zodat het log meegroeit met de backtest-stride i.p.v. met de runcadans.
    Geeft #gelogde uur-rijen (0 bij skip)."""
    rows = [r for r in (weather.get("hourly") or [])
            if r.get("dt") is not None and r.get("T_out") is not None
            and r["dt"] >= now - _timedelta_h(2.0)]
    if not rows:
        return 0
    month = now.strftime("%Y-%m")
    shard = _load_forecast_shard(month)
    snaps = shard.setdefault("snapshots", [])
    if snaps:
        try:
            last = datetime.fromisoformat(snaps[-1].get("issued"))
        except (TypeError, ValueError):
            last = None
        if last is not None and (now - last) < _timedelta_h(FORECAST_ISSUE_EVERY_H):
            return 0
    snap = {"issued": now.isoformat(),
            "t": [int(r["dt"].timestamp()) for r in rows]}
    for col, field, scale in _FC_COLS:
        snap[col] = [int(round(r[field] * scale)) if r.get(field) is not None else None
                     for r in rows]
    snaps.append(snap)
    os.makedirs(FORECAST_LOG_DIR, exist_ok=True)
    with open(_forecast_shard_path(month), "w", encoding="utf-8") as f:
        json.dump(shard, f, ensure_ascii=False, separators=(",", ":"))
    return len(rows)

def _decode_forecast_snapshot(snap: dict) -> list[dict]:
    """Eén kolom-snapshot terug naar fetch_weather-rijvorm (dt/T_out/rh/…)."""
    rows = []
    epochs = snap.get("t") or []
    for i, epoch in enumerate(epochs):
        row = {"dt": datetime.fromtimestamp(epoch, TZ)}
        for col, field, scale in _FC_COLS:
            arr = snap.get(col) or []
            v = arr[i] if i < len(arr) else None
            row[field] = (v / scale) if v is not None else (None if field in ("T_out", "rh") else 0.0)
        rows.append(row)
    return rows

def load_forecast_log() -> list[dict]:
    """Alle gelogde forecast-snapshots, oud → nieuw: `[{"issued": datetime,
    "rows": [fetch_weather-rij, …]}, …]`. Leeg log → lege lijst (de consument —
    de backtest in forecast-modus — meldt dat dan zelf netjes)."""
    snaps = []
    for path in sorted(glob.glob(os.path.join(FORECAST_LOG_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                shard = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for s in shard.get("snapshots") or []:
            try:
                issued = datetime.fromisoformat(s["issued"])
            except (KeyError, TypeError, ValueError):
                continue
            snaps.append({"issued": issued, "rows": _decode_forecast_snapshot(s)})
    snaps.sort(key=lambda s: s["issued"])
    return snaps
