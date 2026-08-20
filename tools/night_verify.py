#!/usr/bin/env python3
"""Reken de gelogde nachtvoorspellingen (Project 10) af tegen de gemeten kinderkamer-temps.

`night_forecast.py` legt elke avond zijn dicht-scenario-voorspelling vast in
`data/night_forecast_log/`; de gemeten kamertemps staan tóch al in
`data/twin2_history` (de kwartierrun append't ze). Dit gereedschap voegt die twee
samen tot een doorlopende scorekaart: per nacht RMSE/bias over de hele curve plus
de fout op de merkuren (23/03/07) waar het bericht letterlijk getallen voor
noemt. Vóór dit spoor was de nachtvoorspelling precies één keer gevalideerd
(9 held-out nachten, RMSE 0,86 °C) en daarna nooit meer.

Bewust tegen de RUWE metingen: dit scoort wat de ontvanger van het bericht is
beloofd, niet de modelfit — een nacht waarin de airco aanging of gestookt werd is
voor de ontvanger een échte misser, ook al kán de voorspelling dat niet weten.

De uitkomst gaat sinds de privacy-assessment (aug 2026) naar de privé
artefact-gist (`ARTEFACT_GIST_ID`, via artefact_io — zelfde patroon als de
overige geprivatiseerde artefacten): per-nacht scores van de kinderkamer tegen
gemeten temperaturen zijn gedragsdata en horen niet publiek onder `docs/`.
Zonder het secret valt de writer terug op het lokale `--out`-pad (gitignored).

Gebruik (wekelijks via twin-eval.yml, of los):
    python tools/night_verify.py
    python tools/night_verify.py --out docs/night_verify.json --last 60
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from bisect import bisect_left
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import artefact_io               # noqa: E402
import vent_io as vio            # noqa: E402
from night_forecast import MARKS, NIGHT_LOG_DIR, ROOM_ID  # noqa: E402
from shared_const import TZ, utc_now_iso  # noqa: E402

JOIN_TOL_MIN = 10.0     # kwartierpunt ↔ dichtstbijzijnde meting
MARK_TOL_MIN = 30.0     # merkuur ↔ dichtstbijzijnde meting (zelfde tolerantie als night_stats)
AGG_RECENT_N = 14       # "recent"-venster in de samenvatting


def load_night_log(log_dir: str = NIGHT_LOG_DIR) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(os.path.join(log_dir, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                shard = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        rows.extend(shard.get("forecasts") or [])
    rows.sort(key=lambda r: r.get("date") or "")
    return rows


def _nearest(measured: tuple[list, list], t: datetime, tol_min: float) -> float | None:
    """Dichtstbijzijnde meting bij `t` binnen de tolerantie. `measured` = (times, vals),
    beide oplopend op tijd — één keer voorbereid in main() i.p.v. per opzoeking."""
    times, vals = measured
    i = bisect_left(times, t)
    best = best_d = None
    for j in (i - 1, i):
        if 0 <= j < len(times):
            d = abs((times[j] - t).total_seconds()) / 60.0
            if d <= tol_min and (best_d is None or d < best_d):
                best, best_d = vals[j], d
    return best


def verify_night(row: dict, measured: tuple[list, list]) -> dict | None:
    """Score één gelogde nacht tegen de metingen ((times, vals)-paar). None als de nacht
    nog loopt of er (nog) geen metingen tegenover staan."""
    series = [(datetime.fromtimestamp(e, TZ), v / 10.0)
              for e, v in row.get("series_dicht") or []]
    if not series:
        return None
    if datetime.now(TZ) < series[-1][0]:
        return None                      # nacht nog niet om
    errs = []
    for t, pred in series:
        act = _nearest(measured, t, JOIN_TOL_MIN)
        if act is not None:
            errs.append(pred - act)
    if not errs:
        return None
    mark_err = {}
    marks = (row.get("scenarios") or {}).get("dicht", {}).get("marks") or {}
    base = datetime.fromisoformat(row["t"])
    for hh in MARKS:
        pred = marks.get(str(hh))
        if pred is None:
            continue
        day = base if hh >= 21 else base + timedelta(days=1)
        mark_t = day.replace(hour=hh, minute=0, second=0, microsecond=0)
        act = _nearest(measured, mark_t, MARK_TOL_MIN)
        if act is not None:
            mark_err[str(hh)] = round(pred - act, 2)
    return {"date": row["date"], "sent": bool(row.get("sent")),
            "n": len(errs),
            "rmse": round(math.sqrt(sum(e * e for e in errs) / len(errs)), 3),
            "bias": round(sum(errs) / len(errs), 3),
            "marks": mark_err}


def _agg(nights: list[dict]) -> dict | None:
    if not nights:
        return None
    # Gepoolde RMSE gewogen op #punten per nacht; bias idem.
    tot_sq = tot_b = tot_n = 0.0
    for x in nights:
        tot_sq += (x["rmse"] ** 2) * x["n"]
        tot_b += x["bias"] * x["n"]
        tot_n += x["n"]
    m7 = [x["marks"].get("7") for x in nights if x["marks"].get("7") is not None]
    return {"nights": len(nights),
            "rmse": round(math.sqrt(tot_sq / tot_n), 3),
            "bias": round(tot_b / tot_n, 3),
            "bias_07": round(sum(m7) / len(m7), 3) if m7 else None}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="docs/night_verify.json")
    ap.add_argument("--last", type=int, default=90, help="max #nachten in het artefact")
    args = ap.parse_args()

    house = vio.load_house()
    ds = vio.load_dataset(house)
    samples = sorted(ds["actual"].get(ROOM_ID, []))
    measured = ([t for t, _ in samples], [v for _, v in samples])
    rows = load_night_log()
    print(f"gelogde voorspellingen: {len(rows)}; metingen {ROOM_ID}: {len(samples)}")

    nights = []
    for row in rows:
        v = verify_night(row, measured)
        if v:
            nights.append(v)
    nights = nights[-args.last:]

    out = {"updated_at": utc_now_iso(), "room": ROOM_ID,
           "aggregate": _agg(nights),
           "recent": _agg(nights[-AGG_RECENT_N:]),
           "nights": nights}
    dest = artefact_io.write_json_str("night_verify.json", args.out,
                                      json.dumps(out, ensure_ascii=False, indent=1))

    if not nights:
        print("nog geen afgeronde, meetbare nachten in het log — artefact leeg geschreven.")
        return
    # De per-nacht-tabel alleen lokaal (eigenaar-tool): in CI is stdout een
    # publieke Actions-log en horen er geen gedateerde per-nacht scores van de
    # kinderkamer in — de geaggregeerde regels hieronder volstaan daar.
    if not artefact_io.gist_active():
        print(f"\n{'datum':12}{'n':>5}{'rmse':>8}{'bias':>8}   marks (23/03/07)")
        for x in nights[-20:]:
            mk = "/".join(f"{x['marks'].get(str(h), '—')}" for h in MARKS)
            print(f"{x['date']:12}{x['n']:>5}{x['rmse']:>8.2f}{x['bias']:>+8.2f}   {mk}")
    a, r = out["aggregate"], out["recent"]
    print(f"\ntotaal : {a['nights']} nachten, RMSE {a['rmse']:.2f} °C, bias {a['bias']:+.2f}"
          + (f", bias@07 {a['bias_07']:+.2f}" if a.get("bias_07") is not None else ""))
    if r and r["nights"] < a["nights"]:
        print(f"recent : {r['nights']} nachten, RMSE {r['rmse']:.2f} °C, bias {r['bias']:+.2f}")
    print(f"\ngeschreven: {dest}")


if __name__ == "__main__":
    main()
