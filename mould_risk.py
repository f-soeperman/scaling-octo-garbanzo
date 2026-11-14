"""Schimmelrisico per kamer uit drie metingen: kamertemperatuur, kamer-RH en buitentemp.

Schimmel groeit niet waar de *lucht* vochtig is maar waar een *oppervlak* dagenlang boven
~80 % RH staat: de koudste plek van de kamer (buitenhoek, raamdag, achter een kast). Die
plek is kouder naarmate het buiten kouder is, dus de kamer-RH die nog veilig is schuift
mee met het weer — een vaste "60 % is goed" is op een vriesdag te ruim en op een zachte
dag te streng.

Zuivere functies, geen I/O. De oppervlaktetemperatuur volgt uit de temperatuurfactor
f (fRsi): Ts = Tin − (1 − f)·(Tin − Tbuiten). f is een eigenschap van de bouwkundige
detaillering en is hier een AANNAME, geen meting — zie `FRSI_DEFAULT`.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

FRSI_DEFAULT = 0.65    # temperatuurfactor van de koudste plek. 0.65 is de ondergrens voor
                       # nieuwbouw; een oudere koudebrug zit lager (strenger). Aanname tot
                       # er een waarneming is om 'm tegen te leggen (bv. condens op een dag
                       # waarop de index "veilig" zei → f omlaag voor die kamer).
ROOM_FRSI: dict[str, float] = {}   # per-kamer afwijking van de aanname (gepubliceerde naam)

SURFACE_RH_RISK  = 80.0   # % aan het oppervlak — schimmelgroei bij dagenlang aanhouden
SURFACE_RH_WATCH = 70.0   # % — marge wordt krap
OUTSIDE_MEAN_H   = 24.0   # uur — een muur volgt het daggemiddelde buiten, niet het moment
TALLY_KEEP_D     = 14     # dagen in het rollende logboek
TALLY_MAX_GAP_H  = 0.5    # een gat tussen twee runs telt hooguit zo lang mee
WEEK_D           = 7


def _es(temp_c: float) -> float:
    """Saturatiedampdruk (kPa), Magnus/Tetens — dezelfde vorm als window_advisor._es."""
    return 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))


def frsi(room: str) -> float:
    return ROOM_FRSI.get(room, FRSI_DEFAULT)


def surface_temp(t_in: float, t_out: float, f: float = FRSI_DEFAULT) -> float:
    """Temperatuur van de koudste binnenoppervlakte. Is het buiten warmer dan binnen, dan
    is er geen koude plek: het oppervlak is dan gewoon op kamertemperatuur."""
    return t_in - (1.0 - f) * max(0.0, t_in - t_out)


def surface_rh(t_in: float, rh_in: float, t_surf: float) -> float:
    """RH (%) van de kamerlucht tegen het koude oppervlak — de dampdruk blijft gelijk,
    het verzadigingspunt zakt mee met de temperatuur. Geklemd op 100 (= condens)."""
    return min(100.0, rh_in * _es(t_in) / _es(t_surf))


def allowed_rh(t_in: float, t_surf: float, limit: float = SURFACE_RH_RISK) -> float:
    """De kamer-RH (%) waarbij het koude oppervlak precies op `limit` staat."""
    return min(100.0, limit * _es(t_surf) / _es(t_in))


def level(surf_rh: float) -> str:
    if surf_rh >= SURFACE_RH_RISK:
        return "risico"
    if surf_rh >= SURFACE_RH_WATCH:
        return "let_op"
    return "ok"


def outside_mean(history: list[dict], now: datetime, fallback: float | None,
                 window_h: float = OUTSIDE_MEAN_H) -> float | None:
    """Gemiddelde buitentemperatuur over het laatste etmaal uit `outside_history`
    (samples `{"t": ISO, "temp": °C}`); zonder bruikbare samples de nu-waarde."""
    since = now - timedelta(hours=window_h)
    vals = []
    for s in history or []:
        try:
            t = datetime.fromisoformat(s["t"])
        except (KeyError, TypeError, ValueError):
            continue
        if since <= t <= now and s.get("temp") is not None:
            vals.append(float(s["temp"]))
    return sum(vals) / len(vals) if vals else fallback


def assess(room: str, t_in: float | None, rh_in: float | None,
           t_out_mean: float | None) -> dict | None:
    """De index voor één kamer op dit moment, of None zonder volledige meting."""
    if t_in is None or rh_in is None or t_out_mean is None:
        return None
    f = frsi(room)
    ts = surface_temp(t_in, t_out_mean, f)
    srh = surface_rh(t_in, rh_in, ts)
    ok_to = allowed_rh(t_in, ts)
    return {
        "surface_temp": round(ts, 1),
        "surface_rh":   round(srh),
        "allowed_rh":   round(ok_to),
        "headroom":     round(ok_to - rh_in),   # %RH tot de grens; negatief = erover
        "level":        level(srh),
        "frsi":         f,
    }


def update_tally(tally: dict | None, now: datetime, per_room: dict[str, dict | None]) -> dict:
    """Tel de sinds de vorige run verstreken tijd bij in het daglogboek: per kamer de uren
    gemeten (`h`), boven de let-op-grens (`watch_h`) en boven de risicogrens (`risk_h`),
    plus het dagmaximum. Geeft een nieuw dict terug; het origineel blijft ongemoeid."""
    tally = tally or {}
    days = {d: {r: dict(v) for r, v in rooms.items()}
            for d, rooms in (tally.get("days") or {}).items()}
    dt_h = 0.25
    try:
        gap = (now - datetime.fromisoformat(tally["last_t"])).total_seconds() / 3600.0
        dt_h = min(max(gap, 0.0), TALLY_MAX_GAP_H)
    except (KeyError, TypeError, ValueError):
        pass
    today = now.date().isoformat()
    bucket = days.setdefault(today, {})
    for room, a in per_room.items():
        if not a:
            continue
        row = bucket.setdefault(room, {"h": 0.0, "watch_h": 0.0, "risk_h": 0.0, "max": 0})
        row["h"] = round(row["h"] + dt_h, 2)
        if a["surface_rh"] >= SURFACE_RH_WATCH:
            row["watch_h"] = round(row["watch_h"] + dt_h, 2)
        if a["surface_rh"] >= SURFACE_RH_RISK:
            row["risk_h"] = round(row["risk_h"] + dt_h, 2)
        row["max"] = max(row["max"], a["surface_rh"])
    cutoff = (now.date() - timedelta(days=TALLY_KEEP_D - 1)).isoformat()
    days = {d: v for d, v in days.items() if d >= cutoff}
    return {"last_t": now.isoformat(), "days": dict(sorted(days.items()))}


def week_summary(tally: dict, now: datetime, room: str, days: int = WEEK_D) -> dict:
    """Som over de laatste `days` dagen voor één kamer."""
    cutoff = (now.date() - timedelta(days=days - 1)).isoformat()
    out = {"h": 0.0, "watch_h": 0.0, "risk_h": 0.0, "max": 0}
    for d, rooms in (tally.get("days") or {}).items():
        row = rooms.get(room)
        if d < cutoff or not row:
            continue
        for k in ("h", "watch_h", "risk_h"):
            out[k] = round(out[k] + row.get(k, 0.0), 2)
        out["max"] = max(out["max"], row.get("max", 0))
    return out
