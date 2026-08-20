"""Hoe doet het FAO-56-bodemmodel het tegen de GARDENA-bodemsensor?

DE VRAAG, EN WAAROM HIJ LASTIGER IS DAN HIJ LIJKT
--------------------------------------------------
Project 16 archiveert sinds aug 2026 de bodemsensor (19040-20) in
`data/gardena_history/`. Dat is de eerste directe meting van bodemvocht in deze
tuin — tot dan was `docs/data.json` een volledig ongetoetste waterbalans.

Alleen: sensor en model meten niet hetzelfde ding, op drie manieren tegelijk.

  1. **Andere eenheid.** De sensor rapporteert "soil humidity" in procenten op
     een niet-gedocumenteerde schaal. Het model rekent in θ (m³/m³). 70 % kán
     geen volumetrisch vochtgehalte zijn — dat ligt boven de porositeit van
     zand. Er is dus een *mapping* nodig, en die is onbekend. Deze module
     rekent daarom niet één vertaling door maar **alle plausibele kandidaten
     naast elkaar** (`candidate_mappings`), zodat de groeiende reeks zelf mag
     uitwijzen welke standhoudt i.p.v. dat wij er één kiezen en 'm daarna
     bevestigd zien worden.
  2. **Andere diepte.** De prikker meet op ~5–10 cm. Het model heeft daar geen
     enkele toestandsvariabele voor: het draagt een *oppervlaktelaag* (`De`,
     Ze = 0.10 m) die alleen door verdamping leegloopt, en een *wortelzone*
     (`theta`, Zr = 0.20 m gras / 0.50 m struiken) die door transpiratie
     leegloopt. De sensor zit fysiek in de eerste en meet effectief mee met de
     tweede — wortels onttrekken juist bovenin het meest. De verwachting is dus
     dat de meting ergens tússen de twee curves valt; beide worden gerapporteerd.
  3. **Ander punt in de ruimte.** Eén prikker in één bed tegen een zone-gemiddelde
     over de hele tuin. Ruimtelijke variatie in bodemvocht is groot; een
     systematisch niveauverschil is dus géén modelfout.

WAT DEZE MODULE DAAROM WÉL EN NIET MEET
----------------------------------------
Niet: "de RMSE tussen sensor en model". Dat getal zou een precisie suggereren
die de drie punten hierboven uitsluiten — met een onbekende mapping is elke
RMSE een keuze van de mapping, niet een eigenschap van het model.

Wel, in volgorde van bewijskracht:

  1. `dynamics` — lopen de *veranderingen* mee? Dit is de kern. Een onbekende
     mapping en een ruimtelijke offset zijn allebei ongeveer constant; een
     droogteperiode en een regenbui zijn dat niet. Zakt de meting terwijl het
     model zakt, en springt hij op de dag dat het model naar veldcapaciteit
     gaat, dan klopt de waterbalans — ongeacht het niveau.
  2. `level_table` — de niveauvergelijking onder elke kandidaat-mapping, als
     hypothesegenerator. Eén meting tegen één modelwaarde is nooit bewijs;
     hij dient om de kandidaten te ordenen voor punt 1.
  3. `temp_table` — bodemtemperatuur. Hier is de sensor wél direct
     vergelijkbaar (°C is °C) en toetst hij twee dingen: de additieve
     `Tsoil_*`-overlay uit Open-Meteo (een gridmodel, geen meting) en op termijn
     de lucht-proxy achter `temp_factor` (zie `soil_temp_proxy.py`). Die tweede
     vraag is pas in het schouderseizoen beantwoordbaar: boven 8 °C staat
     `temp_factor` op 1.0 en verandert geen enkele beslissing.
  4. `pending_test` — wat het model voor de komende dagen *voorspelt*, uitgedrukt
     in de kandidaat-mappings. Vooraf opschrijven wat er zou moeten gebeuren is
     de enige manier om achteraf niet de uitkomst te kunnen napraten; zelfde
     forward-chaining-gedachte als `bias_eval`.

Zuivere functies over gewone dicts; **geen netwerk**. Alles draait op lokale
artefacten (`docs/data.json`, `data/gardena_history/`, en optioneel een lokale
twin2-shard-kopie voor uurlijkse luchttemperatuur — de shards zelf leven sinds
de privacy-assessment aug 2026 in de privé Gist, dus wijs `--twin-dir` of
`VENT_HISTORY_DIR` naar een export) — het `weekjournaal`-patroon.
Runner: `python tools/gardena_sensor_eval.py`.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared_const import TZ  # noqa: E402
from soil_model import SURFACE_LAYER, ZONES  # noqa: E402

# ── Afstelbare aannames (domeinbeslissingen — niet terloops wijzigen) ────────

# Een vers ingeprikte sensor staat niet meteen in evenwicht: het lichaam heeft
# de temperatuur van waar hij vandaan kwam en de bodem moet zich om de prikker
# sluiten voordat de capacitieve meting representatief is. Rijen binnen dit
# venster ná de állereerste observatie worden gemarkeerd en standaard uit de
# statistiek gelaten (`--settle-h 0` zet dat uit). 2 uur is ruim voor de
# thermische settle die in de eerste rijen zichtbaar was.
SETTLE_H = 2.0

# Porositeit van klei-verrijkt ophoogzand, alleen gebruikt voor de
# "% van verzadiging"-kandidaat. Ruwe waarde: die mapping valt in de praktijk
# meteen af, hij staat er om 'm expliciet te kunnen afstrepen.
THETA_SAT = 0.43

# In welke zone zit de prikker (bewonersopgave, aug 2026)? Bepaalt welke
# modelkolom de vergelijking draagt; de andere zone blijft als referentie in het
# rapport staan. Bewust een constante en geen gok uit de data: `gardena_config.json`
# leeft in de Gist en draagt geen zoneveld, dus dit is opgegeven kennis.
SENSOR_ZONE = "shrubs"

# Onder dit aantal gepaarde dagen doet `dynamics` geen uitspraak. Drie dagen
# geven twee verschillen — genoeg om een teken te zien, te weinig voor een
# correlatie; het rapport zegt er zelf bij hoe hard het is.
MIN_DYNAMICS_DAYS = 3

# Een dag telt alleen mee in de dagstatistiek als de sensor er minstens zoveel
# uur van dekt. Een dag met drie nachtelijke rijen heeft geen dagmiddel dat
# tegen een 24-uurs modelwaarde gelegd mag worden.
MIN_DAY_COVERAGE_H = 18.0


# ── Sensor-archief ──────────────────────────────────────────────────────────

def load_sensor_rows(history_dir: str) -> List[dict]:
    """Alle rijen uit alle maand-shards, chronologisch."""
    rows: List[dict] = []
    for path in sorted(glob.glob(os.path.join(history_dir, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                shard = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        rows.extend(shard.get("rows") or [])
    rows.sort(key=lambda r: r["t"])
    return rows


def parse_t(row: dict) -> datetime:
    return datetime.fromisoformat(row["t"]).astimezone(timezone.utc)


def mark_settling(rows: Sequence[dict], settle_h: float = SETTLE_H) -> List[dict]:
    """Markeert de inregel-rijen ná installatie met `settling: True`.

    Puur op tijd sinds de eerste observatie — bewust geen slimme
    uitschieterdetectie, want die zou op een echte natuurlijke sprong (een
    regenbui vlak na installatie) precies het signaal weggooien waar het om gaat.
    """
    if not rows:
        return []
    t0 = parse_t(rows[0])
    out = []
    for r in rows:
        age_h = (parse_t(r) - t0).total_seconds() / 3600.0
        out.append({**r, "settling": age_h < settle_h})
    return out


def resolution(values: Sequence[Optional[float]]) -> dict:
    """Waarnemingsresolutie van een sensorkanaal.

    Waarom dit er staat: als de sensor in stappen van 5 % rapporteert, is een
    modelvoorspelling van 3 % drift per dag principieel onmeetbaar en is "de
    sensor stond stil" geen bevestiging maar een niet-meting. De stap wordt
    geschat als de grootste gemene deler van de waargenomen verschillen.

    Bewust over **alle** rijen, inregel-rijen incluis: de stapgrootte is een
    eigenschap van hoe het apparaat rapporteert, niet van de bodem, en juist de
    eerste (afwijkende) waarde levert het eerste verschil om 'm uit te schatten.
    """
    vals = [v for v in values if v is not None]
    distinct = sorted(set(vals))
    diffs = [b - a for a, b in zip(distinct, distinct[1:])]
    step = None
    if diffs:
        if all(float(d).is_integer() for d in diffs):
            step = math.gcd(*(int(d) for d in diffs)) if len(diffs) > 1 else int(diffs[0])
        else:
            step = min(diffs)
    return {"n": len(vals), "distinct": distinct, "n_distinct": len(distinct),
            "step": step, "span": (max(vals) - min(vals)) if vals else None}


def daily_sensor(rows: Sequence[dict], field: str = "soil_hum") -> Dict[str, dict]:
    """Per lokale datum een samenvatting van het sensorkanaal.

    `coverage_h` = het tijdsverschil tussen de eerste en laatste rij van die dag,
    zodat het rapport een halve dag nooit als dagmiddel presenteert.
    """
    by_day: Dict[str, List[tuple]] = defaultdict(list)
    for r in rows:
        if r.get("settling") or r.get(field) is None:
            continue
        local = parse_t(r).astimezone(TZ)
        by_day[local.date().isoformat()].append((local, float(r[field])))
    out = {}
    for day, pairs in by_day.items():
        pairs.sort()
        vals = [v for _, v in pairs]
        out[day] = {"n": len(vals), "mean": sum(vals) / len(vals),
                    "min": min(vals), "max": max(vals),
                    "first": vals[0], "last": vals[-1],
                    "coverage_h": (pairs[-1][0] - pairs[0][0]).total_seconds() / 3600.0}
    return out


# ── Kandidaat-mappings sensor-% ↔ model ─────────────────────────────────────

def available_water(theta: float, fc: float, wp: float) -> float:
    """Plantbeschikbaar water als % van de bandbreedte WP→FC (= 100 − depletie)."""
    return (theta - wp) / (fc - wp) * 100.0


def surface_available(de: Optional[float], tew: float) -> Optional[float]:
    """Vulling van de oppervlaktelaag als %: 100 % = net bevochtigd, 0 % = TEW leeg."""
    return None if de is None else (1.0 - de / tew) * 100.0


def refill_mm(day: dict, zone: str, fc: float, wp: float) -> Dict[str, Optional[float]]:
    """Hoeveel bevochtiging elke bak nog nodig heeft om vol te staan.

    Dit is de scherpste toets die er is op de dieptevraag uit de moduledocstring,
    en de enige die niet aan de onbekende mapping hangt. Regen en irrigatie
    worden in FAO-56 §7.4.5 van **beide** boekhoudingen tegelijk afgetrokken —
    het zijn twee rekeningen over hetzelfde fysieke water — dus ze reageren op
    dezelfde invoer. Wat ze onderscheidt is hoe snel ze **vol** zitten: de
    oppervlaktelaag loopt over bij TEW (18 mm, en staat onder een dichte canopy
    toch al bijna vol), de wortelzone moet het hele tekort t.o.v. veldcapaciteit
    goedmaken — voor struiken een veelvoud daarvan.

    Een flinke regenbui scheidt de twee hypotheses daarom op **timing**, niet op
    grootte: zit de sensor in de oppervlaktelaag, dan schiet hij binnen de eerste
    millimeters naar zijn plafond en blijft daar; volgt hij de wortelzone, dan
    klimt hij nog een etmaal door. Dat is op uurresolutie zichtbaar en het werkt
    ook als de sensorschaal niet-lineair is — de *vorm* draagt de conclusie.
    """
    theta, de = day.get(f"{zone}_theta"), day.get(f"{zone}_De")
    awc = (fc - wp) * ZONES[zone]["Zr"] * 1000.0
    return {
        "surface_mm": de,                      # De is per definitie het tekort
        "rootzone_mm": (None if theta is None
                        else max(0.0, (fc - theta) * ZONES[zone]["Zr"] * 1000.0)),
        "awc_mm": awc,
    }


def candidate_mappings(day: dict, zone: str, fc: float, wp: float,
                       theta_sat: float = THETA_SAT) -> Dict[str, Optional[float]]:
    """Alle plausibele vertalingen van de modelstand naar een sensor-%.

    De namen zeggen wélke grootheid de sensor dan zou rapporteren. Ze worden
    bewust allemaal doorgerekend: welke standhoudt is een empirische vraag die
    alleen de dynamiek over weken kan beantwoorden.
    """
    theta = day.get(f"{zone}_theta")
    de = day.get(f"{zone}_De")
    if theta is None:
        return {}
    return {
        # De sensor rapporteert θ direct (× 100). Valt vrijwel zeker af: θ voor
        # zand ligt rond 0.10–0.20, dus 10–20 % — ver onder wat de sensor toont.
        "theta_x100": theta * 100.0,
        # De sensor rapporteert % van het plantbeschikbare water in de wortelzone.
        "available_water": available_water(theta, fc, wp),
        # De sensor rapporteert % van verzadiging (θ / porositeit).
        "saturation": theta / theta_sat * 100.0,
        # De sensor rapporteert de vulling van de oppervlaktelaag — de laag waar
        # de prikker fysiek in zit, maar die in dit model alleen door verdamping
        # leegloopt (en dus onder een dichte canopy bijna vol blijft staan).
        "surface_layer": surface_available(de, SURFACE_LAYER["TEW"]),
    }


# ── Rapportonderdelen ───────────────────────────────────────────────────────

def level_table(days: Sequence[dict], sensor_days: Dict[str, dict],
                fc: float, wp: float) -> List[dict]:
    """Per gepaarde dag: sensorwaarde naast elke kandidaat-mapping, per zone."""
    index = {d["date"]: d for d in days}
    out = []
    for date in sorted(sensor_days):
        day = index.get(date)
        if day is None or day.get("forecast"):
            continue
        s = sensor_days[date]
        row = {"date": date, "sensor_mean": s["mean"], "sensor_n": s["n"],
               "coverage_h": s["coverage_h"], "zones": {}}
        for zone in ZONES:
            row["zones"][zone] = candidate_mappings(day, zone, fc, wp)
        out.append(row)
    return out


def dynamics(days: Sequence[dict], sensor_days: Dict[str, dict],
             fc: float, wp: float,
             min_days: int = MIN_DYNAMICS_DAYS,
             min_coverage_h: float = MIN_DAY_COVERAGE_H) -> dict:
    """Lopen de dag-op-dag *veranderingen* van sensor en model mee?

    Dit is de maat die er toe doet: een onbekende schaalfactor en een ruimtelijke
    offset overleven een differentie niet, een kloppende waterbalans wel. Per
    kandidaat-mapping wordt de correlatie én de helling van Δsensor tegen Δmodel
    gegeven — een helling van ~1 bij die mapping is het bewijs dat we zoeken,
    een helling ver van 1 zegt dat de mapping schaal-verkeerd is terwijl de
    *vorm* nog steeds kan kloppen (dat leest af aan de correlatie).
    """
    index = {d["date"]: d for d in days}
    usable = [d for d in sorted(sensor_days)
              if d in index and not index[d].get("forecast")
              and sensor_days[d]["coverage_h"] >= min_coverage_h]
    if len(usable) < min_days:
        return {"status": "insufficient", "n_days": len(usable),
                "need": min_days, "days": usable}
    out = {"status": "ok", "n_days": len(usable), "days": usable, "zones": {}}
    d_sensor = [sensor_days[b]["mean"] - sensor_days[a]["mean"]
                for a, b in zip(usable, usable[1:])]
    for zone in ZONES:
        per_mapping = {}
        for name in ("theta_x100", "available_water", "saturation", "surface_layer"):
            model = [candidate_mappings(index[d], zone, fc, wp).get(name) for d in usable]
            if any(m is None for m in model):
                continue
            d_model = [b - a for a, b in zip(model, model[1:])]
            per_mapping[name] = {"corr": _corr(d_sensor, d_model),
                                 "slope": _slope(d_model, d_sensor),
                                 "mean_abs_model": sum(abs(x) for x in d_model) / len(d_model),
                                 "mean_abs_sensor": sum(abs(x) for x in d_sensor) / len(d_sensor)}
        out["zones"][zone] = per_mapping
    return out


def _corr(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = len(a)
    if n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    saa = sum((x - ma) ** 2 for x in a)
    sbb = sum((x - mb) ** 2 for x in b)
    sab = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return sab / math.sqrt(saa * sbb) if saa > 0 and sbb > 0 else None


def _slope(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    """Kleinste-kwadraten helling van y op x, door de oorsprong-vrije vorm."""
    n = len(x)
    if n < 2:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((v - mx) ** 2 for v in x)
    if sxx <= 0:
        return None
    return sum((v - mx) * (w - my) for v, w in zip(x, y)) / sxx


def load_air_hours(twin_dir: str) -> Dict[datetime, float]:
    """Uurlijkse buitentemperatuur uit de tweeling-shards (UTC-uur → °C).

    Optioneel: zonder dit bestand vervalt alleen de demping-vergelijking.
    """
    out: Dict[datetime, float] = {}
    for path in sorted(glob.glob(os.path.join(twin_dir, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                shard = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for w in shard.get("weather") or []:
            if w.get("T_out") is None:
                continue
            dt = datetime.fromisoformat(w["dt"]).astimezone(timezone.utc)
            out[dt.replace(minute=0, second=0, microsecond=0)] = float(w["T_out"])
    return out


def temp_table(rows: Sequence[dict], days: Sequence[dict],
               air_hours: Dict[datetime, float]) -> dict:
    """Bodemtemperatuur: sensor vs. de Open-Meteo-overlay vs. de lucht.

    Twee getallen dragen de conclusie. (1) Het verschil tussen de sensor en
    `Tsoil_shallow` — dat is de toets op de overlay, en die is alleen geldig op
    dagen met (bijna) volledige dekking, want een nachtmiddel tegen een
    24-uurs modelmiddel leggen meet het etmaal, niet de fout. (2) De
    dempingsverhouding sensor/lucht: hoeveel van de dagelijkse luchtswing
    bereikt de sensordiepte. Die verhouding is een eigenschap van de diepte en
    de bodem, en is dus de sanity-check op waar de prikker eigenlijk zit.
    """
    index = {d["date"]: d for d in days}
    by_day: Dict[str, List[tuple]] = defaultdict(list)
    for r in rows:
        if r.get("settling") or r.get("soil_temp") is None:
            continue
        local = parse_t(r).astimezone(TZ)
        by_day[local.date().isoformat()].append((parse_t(r), float(r["soil_temp"])))
    out = []
    for date in sorted(by_day):
        pairs = sorted(by_day[date])
        vals = [v for _, v in pairs]
        coverage = (pairs[-1][0] - pairs[0][0]).total_seconds() / 3600.0
        air = [air_hours[t.replace(minute=0, second=0, microsecond=0)]
               for t, _ in pairs
               if t.replace(minute=0, second=0, microsecond=0) in air_hours]
        day = index.get(date) or {}
        out.append({
            "date": date, "n": len(vals), "coverage_h": coverage,
            "sensor_mean": sum(vals) / len(vals), "sensor_min": min(vals),
            "sensor_max": max(vals), "sensor_amp": max(vals) - min(vals),
            "air_mean": (sum(air) / len(air)) if air else None,
            "air_amp": (max(air) - min(air)) if air else None,
            "damping": ((max(vals) - min(vals)) / (max(air) - min(air)))
                       if air and max(air) > min(air) else None,
            "Tsoil_shallow": day.get("Tsoil_shallow"),
            "Tsoil_root": day.get("Tsoil_root"),
            "full_day": coverage >= MIN_DAY_COVERAGE_H,
        })
    return {"days": out,
            "note": "Verschillen op dagen met full_day=False meten het etmaal, niet de modelfout."}


def pending_test(days: Sequence[dict], fc: float, wp: float,
                 today: str) -> List[dict]:
    """Wat het model voor de forecast-dagen voorspelt, in sensor-taal.

    Vooraf vastleggen — anders is elke uitkomst achteraf te verklaren. Naast de
    kandidaat-mappings draagt elke rij het bijvul-tekort van beide bakken
    (`refill_mm`), want dáár zit het onderscheidend vermogen bij een regenbui.
    """
    out = []
    for d in days:
        if d["date"] < today:
            continue
        row = {"date": d["date"], "forecast": bool(d.get("forecast")),
               "precip": d.get("precip"), "ET0": d.get("ET0"),
               "zones": {}, "refill": {}}
        for zone in ZONES:
            row["zones"][zone] = candidate_mappings(d, zone, fc, wp)
            row["refill"][zone] = refill_mm(d, zone, fc, wp)
        out.append(row)
    return out


# ── Runner ──────────────────────────────────────────────────────────────────

def build_report(data_path: str, history_dir: str, twin_dir: str,
                 settle_h: float = SETTLE_H, zone: str = SENSOR_ZONE) -> dict:
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)
    fc, wp = data["soil"]["FC"], data["soil"]["WP"]
    days = data["days"]
    today = max((d["date"] for d in days if not d.get("forecast")), default="")

    rows = mark_settling(load_sensor_rows(history_dir), settle_h)
    dropped = [r for r in rows if r.get("settling")]
    sensor_days = daily_sensor(rows)

    first = parse_t(rows[0]).astimezone(TZ).isoformat() if rows else None
    last = parse_t(rows[-1]).astimezone(TZ).isoformat() if rows else None
    span_h = ((parse_t(rows[-1]) - parse_t(rows[0])).total_seconds() / 3600.0) if rows else 0.0
    now = _today_row(days, today)

    return {
        "generated_from": {"data": data_path, "history": history_dir,
                           "model_generated_at": data.get("generated_at")},
        "sensor_zone": zone,
        "record": {"n_rows": len(rows), "n_settling": len(dropped),
                   "first_local": first, "last_local": last, "span_h": span_h,
                   "settle_h": settle_h,
                   "settling_rows": [{"t": r["t"], "soil_hum": r.get("soil_hum"),
                                      "soil_temp": r.get("soil_temp")} for r in dropped]},
        # Resolutie over álle rijen — zie de docstring van `resolution`.
        "resolution": {"soil_hum": resolution([r.get("soil_hum") for r in rows]),
                       "soil_temp": resolution([r.get("soil_temp") for r in rows])},
        "model_now": {zone: {
            "theta": now.get(f"{zone}_theta"),
            "available_water_pct": (available_water(now[f"{zone}_theta"], fc, wp)
                                    if now.get(f"{zone}_theta") is not None else None),
            "surface_pct": surface_available(now.get(f"{zone}_De"), SURFACE_LAYER["TEW"]),
        } for zone in ZONES},
        "level": level_table(days, sensor_days, fc, wp),
        "dynamics": dynamics(days, sensor_days, fc, wp),
        "temperature": temp_table(rows, days, load_air_hours(twin_dir)),
        "pending_test": pending_test(days, fc, wp, today),
    }


def _today_row(days: Sequence[dict], today: str) -> dict:
    for d in days:
        if d["date"] == today:
            return d
    return {}


def _fmt(v, spec="6.1f"):
    return "  n/a " if v is None else format(v, spec)


def _zone_order(rep: dict) -> List[str]:
    """De zone waar de prikker in zit eerst; de andere blijft als referentie."""
    zone = rep.get("sensor_zone")
    return [zone] + [z for z in ZONES if z != zone] if zone in ZONES else list(ZONES)


def _zone_label(rep: dict, zone: str) -> str:
    return zone if zone == rep.get("sensor_zone") else f"{zone}*"


def print_report(rep: dict) -> None:
    rec = rep["record"]
    order = _zone_order(rep)
    print("=" * 78)
    print("GARDENA-bodemsensor vs. FAO-56-bodemmodel")
    print("=" * 78)
    print(f"prikker in zone: {rep.get('sensor_zone')}   (* = andere zone, alleen referentie)")
    print(f"model-artefact : {rep['generated_from']['model_generated_at']}")
    print(f"sensor-record  : {rec['first_local']} → {rec['last_local']}")
    print(f"                 {rec['n_rows']} rijen over {rec['span_h']:.1f} u "
          f"({rec['n_settling']} als inregel-rij weggelaten, venster {rec['settle_h']} u)")
    for r in rec["settling_rows"]:
        print(f"                 weggelaten: {r['t']}  hum={r['soil_hum']} temp={r['soil_temp']}")

    print("\n── Waarnemingsresolutie " + "─" * 54)
    for chan, res in rep["resolution"].items():
        print(f"{chan:<10} n={res['n']:<4} distinct={res['n_distinct']:<3} "
              f"waarden={res['distinct']} stap≈{res['step']}")
    print("  Een modeldrift kleiner dan de stap is principieel onmeetbaar —")
    print("  'de sensor stond stil' is dan geen bevestiging maar een niet-meting.")

    print("\n── Niveau: sensor naast elke kandidaat-mapping " + "─" * 31)
    print("  (hypothesegenerator, geen bewijs — zie de moduledocstring)")
    hdr = f"{'datum':<11}{'sensor':>7}{'dek':>6}  {'zone':<7}"
    for name in ("theta_x100", "available_water", "saturation", "surface_layer"):
        hdr += f"{name:>17}"
    print(hdr)
    for row in rep["level"]:
        for zone in order:
            mapping = row["zones"].get(zone) or {}
            line = (f"{row['date']:<11}{row['sensor_mean']:>7.1f}"
                    f"{row['coverage_h']:>5.0f}u  {_zone_label(rep, zone):<7}")
            for name in ("theta_x100", "available_water", "saturation", "surface_layer"):
                line += f"{_fmt(mapping.get(name), '17.1f')}"
            print(line)

    dyn = rep["dynamics"]
    print("\n── Dynamiek: lopen de veranderingen mee? " + "─" * 37)
    if dyn["status"] != "ok":
        print(f"  NOG GEEN UITSPRAAK — {dyn['n_days']} bruikbare dag(en), "
              f"{dyn['need']} nodig.")
        print("  Dit is de maat die er toe doet; alles hierboven is voorwerk.")
    else:
        print(f"  {dyn['n_days']} dagen: {dyn['days'][0]} → {dyn['days'][-1]}")
        for zone in order:
            for name, st in (dyn["zones"].get(zone) or {}).items():
                print(f"  {_zone_label(rep, zone):<7} {name:<17} corr={_fmt(st['corr'], '5.2f')} "
                      f"helling={_fmt(st['slope'], '5.2f')} "
                      f"|Δmodel|={st['mean_abs_model']:.2f} |Δsensor|={st['mean_abs_sensor']:.2f}")

    print("\n── Bodemtemperatuur " + "─" * 58)
    print(f"{'datum':<11}{'n':>4}{'dek':>6}{'sensor':>8}{'amp':>6}{'lucht':>7}{'amp':>6}"
          f"{'demping':>9}{'Tsoil_sh':>10}{'Tsoil_rt':>10}  vol")
    for d in rep["temperature"]["days"]:
        print(f"{d['date']:<11}{d['n']:>4}{d['coverage_h']:>5.0f}u{d['sensor_mean']:>8.1f}"
              f"{d['sensor_amp']:>6.1f}{_fmt(d['air_mean'], '7.1f')}{_fmt(d['air_amp'], '6.1f')}"
              f"{_fmt(d['damping'], '9.2f')}{_fmt(d['Tsoil_shallow'], '10.2f')}"
              f"{_fmt(d['Tsoil_root'], '10.2f')}  {'ja' if d['full_day'] else 'NEE'}")
    print(f"  {rep['temperature']['note']}")

    print("\n── Vooraf vastgelegd: wat het model de komende dagen zegt " + "─" * 20)
    print("  (in sensor-taal, zodat de uitkomst achteraf niet te herinterpreteren is)")
    print("  'vol na' = bevochtiging die elke bak nog nodig heeft om vol te staan —")
    print("  bij regen scheidt dát de twee hypotheses, op timing i.p.v. op grootte.")
    hdr = (f"{'datum':<11}{'regen':>7}{'ET0':>6}  {'zone':<7}"
           f"{'available_water':>17}{'surface_layer':>17}"
           f"{'vol na: opp':>13}{'wortelzone':>12}")
    print(hdr)
    for row in rep["pending_test"]:
        for zone in order:
            mapping = row["zones"].get(zone) or {}
            fill = row["refill"].get(zone) or {}
            line = (f"{row['date']:<11}{_fmt(row['precip'], '7.1f')}{_fmt(row['ET0'], '6.2f')}"
                    f"  {_zone_label(rep, zone):<7}"
                    f"{_fmt(mapping.get('available_water'), '17.1f')}"
                    f"{_fmt(mapping.get('surface_layer'), '17.1f')}"
                    f"{_fmt(fill.get('surface_mm'), '11.1f')}mm"
                    f"{_fmt(fill.get('rootzone_mm'), '10.1f')}mm")
            print(line)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default="docs/data.json")
    ap.add_argument("--history-dir", default=os.getenv("GARDENA_HISTORY_DIR",
                                                       "data/gardena_history"))
    ap.add_argument("--twin-dir", default=os.getenv("VENT_HISTORY_DIR",
                                                    "data/twin2_history"))
    ap.add_argument("--settle-h", type=float, default=SETTLE_H,
                    help="inregel-venster na installatie (0 = niets weglaten)")
    ap.add_argument("--zone", default=SENSOR_ZONE, choices=sorted(ZONES),
                    help="zone waarin de prikker zit (bepaalt de leidende modelkolom)")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="schrijf het rapport ook als JSON naar dit pad")
    args = ap.parse_args()

    rep = build_report(args.data, args.history_dir, args.twin_dir,
                       args.settle_h, args.zone)
    print_report(rep)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=False)
        print(f"\nJSON → {args.json_out}")


if __name__ == "__main__":
    main()
