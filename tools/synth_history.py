#!/usr/bin/env python3
"""Synthetische maand-shards voor de golden-vector en de surrogaat-distillatie.

De echte twin2-shards leven sinds de shard-privatisering (aug 2026) in de privé Gist en de
publieke git-historie is gesquasht, dus `tools/export_driver_timeline.py` kan de golden-vector
niet meer vanaf een echte oorsprong herslaan zonder Gist-creds. Dat hoeft ook niet: de
golden-test bewijst dat de JS-kern `vp.simulate` reproduceert (een PORT-contract), niet dat het
model het huis goed voorspelt — daarvoor is elke fysisch plausibele tijdlijn even goed. Dit
hulpje schrijft er een: een week zomerweer met een dagcyclus, kamertemperaturen en een
openingen-log die de belangrijkste paden aanzet (dwarsventilatie, schoorsteen, één open raam,
dichte tussendeur).

Volledig deterministisch (geen RNG) en zonder één gemeten waarde — de uitvoer mag dus publiek.

Gebruik (alles in een wegwerpmap, niets hiervan hoort in git):
    python tools/synth_history.py --out /tmp/synth
    VENT_HISTORY_DIR=/tmp/synth python tools/airflow_distill.py
    VENT_HISTORY_DIR=/tmp/synth python tools/export_driver_timeline.py --origin 2026-07-15T14:00:00+02:00
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared_const import TZ   # noqa: E402

START = datetime(2026, 7, 8, 0, 0, tzinfo=TZ)
DAYS = 10
# Kamernaam zoals window_data hem publiceert → (niveau °C, dagamplitude °C, naijling in uren).
ROOMS = {"Living room": (23.4, 1.1, 3.0), "Nursery": (22.6, 0.8, 4.0), "bedroom": (23.9, 1.3, 3.5),
         "office": (25.2, 1.9, 2.5), "Shower": (23.0, 0.3, 5.0)}
# (dag-offset, uur, standen) — elke regel is een snapshot zoals de meldmodal hem schrijft.
LOG = [
    (0, 7, {"bedroom_window": "dicht", "office_window": "dicht", "living_french": "dicht",
            "kitchen_door": "dicht", "nursery_small_window": "dicht", "stair_skylight": "dicht"}),
    (1, 20, {"bedroom_window": "open", "office_window": "tilt", "stair_skylight": "open"}),
    (2, 8, {"bedroom_window": "dicht", "office_window": "dicht", "stair_skylight": "dicht"}),
    (2, 14, {"living_french": "open", "kitchen_door": "open"}),
    (2, 21, {"living_french": "dicht", "kitchen_door": "dicht", "bedroom_window": "open"}),
    (3, 9, {"bedroom_window": "dicht", "living_hall": "dicht"}),
    (3, 18, {"living_hall": "open", "nursery_small_window": "tilt", "kitchen_top_tilt": "open"}),
    (4, 7, {"nursery_small_window": "dicht", "kitchen_top_tilt": "dicht", "hall_stair": "open"}),
    (4, 12, {"hall_stair": "dicht", "office_window": "open"}),
    (5, 19, {"office_window": "dicht", "bedroom_window": "open", "living_french": "tilt"}),
    (6, 8, {"bedroom_window": "dicht", "living_french": "dicht"}),
    (7, 11, {"living_french": "open", "office_window": "tilt", "stair_skylight": "open"}),
    (7, 22, {"living_french": "dicht", "bedroom_window": "open", "hall_bath": "open"}),
    (8, 9, {"bedroom_window": "dicht", "hall_bath": "dicht", "office_window": "dicht"}),
]


def _weather(t: datetime) -> dict:
    h = t.hour + t.minute / 60.0
    day = (t - START).days
    warm = 2.5 * math.sin(2 * math.pi * day / 7.0)                 # een warmere en koelere helft
    sun = max(0.0, math.sin(math.pi * (h - 5.5) / 15.5)) if 5.5 < h < 21.0 else 0.0
    cloud = 0.55 + 0.45 * math.cos(2 * math.pi * (day + 1) / 5.0) ** 2
    sw = 830.0 * sun ** 1.2 * cloud
    return {
        "dt": t.isoformat(),
        "T_out": round(19.0 + warm + 6.0 * math.sin(2 * math.pi * (h - 9.0) / 24.0), 2),
        "rh": round(62.0 - 18.0 * math.sin(2 * math.pi * (h - 9.0) / 24.0), 1),
        "precip": 0.0,
        "wind_speed": round(2.6 + 1.6 * math.sin(2 * math.pi * (h - 14.0) / 24.0) + 0.8 * math.cos(day), 2),
        "wind_dir": round((240.0 + 50.0 * math.sin(2 * math.pi * day / 6.0)) % 360.0, 1),
        "gust": round(5.0 + 2.0 * math.sin(2 * math.pi * (h - 14.0) / 24.0), 2),
        "shortwave": round(sw, 1), "direct": round(0.7 * sw, 1), "diffuse": round(0.3 * sw, 1),
    }


def build() -> dict:
    rooms = {name: {"ts": [], "temp": [], "hum": [], "heat": []} for name in ROOMS}
    weather, t, end = [], START, START + timedelta(days=DAYS)
    while t < end:
        if t.minute == 0:
            weather.append(_weather(t))
        h = t.hour + t.minute / 60.0
        day = (t - START).days
        for name, (level, amp, lag) in ROOMS.items():
            temp = level + 0.6 * math.sin(2 * math.pi * day / 7.0) + amp * math.sin(2 * math.pi * (h - 9.0 - lag) / 24.0)
            rooms[name]["ts"].append(int(t.timestamp()))
            rooms[name]["temp"].append(int(round(temp * 10)))
            rooms[name]["hum"].append(50)
            rooms[name]["heat"].append(0)
        t += timedelta(minutes=15)
    openings = [{"t": (START + timedelta(days=d, hours=hh)).isoformat(), "states": st} for d, hh, st in LOG]
    return {"schema": 1, "month": "2026-07", "rooms": rooms, "weather": weather, "openings": openings}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="wegwerpmap; wordt de VENT_HISTORY_DIR van de vervolgstappen")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "2026-07.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build(), f, separators=(",", ":"))
    print(f"[synth] {path}")


if __name__ == "__main__":
    main()
