#!/usr/bin/env python3
"""Rolling-origin h-ahead backtest voor de ventilatie-tweeling — de ontbrekende maat.

De scores die we hadden meten allebei iets ánders dan wat het dashboard belooft:

  * `docs/vent_learned.json` RMSE ~0.54 is een **nowcast** — de productie herzaait en
    herkalibreert elk kwartier op verse tado-metingen.
  * `pred_twin1_c` in de ML-export is een **5-daagse vrijloop** — één keer gezaaid en
    daarna tot 120 uur laten driften.

Geen van beide is "gegeven wat ik nú weet, hoe warm is elke kamer morgenochtend om
07:00?". Dít gereedschap meet precies dat, onder een **perfecte-forecast-aanname**: het
historische (hindcast) weer gaat erin alsóf het een forecast was, zodat de getallen de
*model*fout isoleren van de *weersvoorspellings*fout. Ze zijn daarmee een optimistische
bovengrens op de live prestatie; het gat is pas te kwantificeren zodra er
forecast-vs-werkelijk-paren gelogd zijn (zie AIRFLOW3_ASSESSMENT.md §6).

Protocol, per uitgiftetijd t0 (rollende oorsprong, stap `--stride-h`):

  1. Aanloop over [t0 − WARMUP_H, t0], gezaaid op de meting aan het begin, met
     `snapshot_t=t0` — dit laat de trage massaknoop equilibreren.
  2. **Herankeren op t0**: de luchtknoop wordt teruggezet op de *gemeten* kamertemp op
     t0 (wat je op voorspelmoment echt weet), en de massaknoop schuift met dezelfde
     delta mee (`--tm-mode shift`; `warm` = de naïeve variant die 'm laat staan).
     Junctions (geen sensor) houden `Ta_now`.
  3. Voorspelpas over [t0, t0 + horizon], gescoord tegen de meting op elke 15-min stap.

Stap 2 is de hele clou, en precies wat de vrijloop-baseline weggooit.

Baselines op exact hetzelfde (t0, horizon, kamer)-raster, zodat de vergelijking
appels-met-appels blijft:

  persist    T(t0)                     — "het blijft zoals het nu is"
  persist24  T(t0 + h − 24u)           — "net als gisteren om deze tijd"
  clim       uur-van-de-dag-gemiddelde — expanderend venster, strikt < t0 (geen lekkage)
  freerun    fysica ZONDER stap 2      — isoleert de waarde van het herankeren

Gebruik:
    python tools/horizon_backtest.py                      # 12u, 3u stride
    python tools/horizon_backtest.py --horizon-h 24
    python tools/horizon_backtest.py --stride-h 6 --jobs 4
    python tools/horizon_backtest.py --out tools/out/h12.json
    python tools/horizon_backtest.py --weather forecast   # échte forecasts (forecast-log)
    python tools/horizon_backtest.py --origin-hours 18,19 --horizon-h 13 --tm-mode ewma
    python tools/horizon_backtest.py --stratify-openings  # fout per raamstand-klasse
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vent_fit as vf          # noqa: E402
import vent_io as vio          # noqa: E402
import vent_physics as vp      # noqa: E402

WARMUP_H = vio.WARMUP_H        # 24u — massaknoop-equilibratie vóór de oorsprong
STEP_MIN = 15                  # het tijdlijn-raster
EWMA_TAU_H = 8.0               # tm-mode "ewma": night_forecast.MASS_ANCHOR_TAU_H gerepliceerd
FC_SNAPSHOT_MAX_AGE_H = 3.75   # forecast-modus: max leeftijd van het snapshot op de oorsprong
                               # (log-cadans is 3u — ouder betekent een gat in het log)


# ---------------------------------------------------------------- metingen

class Measured:
    """Gemeten kamertemps met dichtstbijzijnde-sample-opzoeking + hygiënevlaggen.

    `clean` spiegelt het kalibratiefilter van de tweeling zelf (stook-/mobiele-airco-/
    handmatig-gepauzeerde momenten eruit — de fysica heeft geen actieve verwarmings- of
    koelterm, dus die samples meten iets wat het model nooit beweert te verklaren).
    """

    def __init__(self, ds: dict, tol_min: float):
        self.tol = timedelta(minutes=tol_min)
        self.raw = {r: sorted(s) for r, s in ds["actual"].items()}
        self.times = {r: [t for t, _ in s] for r, s in self.raw.items()}

        # Dezelfde filterketen als de productie-fit.
        t_max = max((t for s in self.raw.values() for t, _ in s), default=None)
        acc = vio.ac_changes(ds["log"])
        pau = vio.paused_intervals(vio.pause_changes(ds["log"]), t_max)
        f, _ = vf.filter_heating_samples(ds["actual"], ds["heat_on"])
        f, _ = vf.filter_ac_samples(f, acc, None, t_max, guard_h=0.0)
        f, _ = vf.filter_paused_samples(f, pau)
        self.clean_ts = {r: {t for t, _ in s} for r, s in f.items()}

    def at(self, room: str, t: datetime, clean_only: bool = False):
        """Dichtstbijzijnde meting bij `t` binnen de tolerantie, anders None."""
        ts = self.times.get(room)
        if not ts:
            return None
        i = bisect_left(ts, t)
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(ts):
                d = abs(ts[j] - t)
                if d <= self.tol and (best is None or d < best[0]):
                    best = (d, j)
        if best is None:
            return None
        j = best[1]
        if clean_only and ts[j] not in self.clean_ts.get(room, ()):
            return None
        return self.raw[room][j][1]


# ------------------------------------------------------------------- één oorsprong

def air_from_sensor(house, rid, t_sensor, t_out):
    """Keer de sensor-plaatsingsbias om: haal de *luchtknoop*-temp terug uit wat de
    tado-sensor leest.

    `vp._sensor_temp` mapt lucht → sensor als `Ts = (1−frac)·Ta + frac·T_out` voor kamers
    met de voeler op een buitenmuur (`sensor_outdoor_frac`, 0.15 voor bedroom en office).
    De luchtknoop rechtstreeks met `Ts` zaaien en de uitvoer dán terugscoren in
    sensorruimte past die blend twéé keer toe — goed voor ~0.15·(Ta − T_out), oftewel
    ruim 1 °C op een koude nacht, en het valt op als een grote fout op h=1 waar de
    voorspelling per constructie bijna exact hoort te zijn.
    """
    frac = house.get("rooms", {}).get(rid, {}).get("sensor_outdoor_frac", 0.0)
    if not frac or t_out is None:
        return t_sensor
    return (t_sensor - frac * t_out) / (1.0 - frac)


def anchor_forecast_seed(house, rooms, meas_at, warm_sim, t_out0, tm_mode="shift",
                         meas_window=None, t0=None):
    """Bouw het (Ta, Tm)-zaad voor de voorspelpas door op de meting op t0 te herankeren.

    `meas_at(rid) -> °C | None` levert de gemeten sensorwaarde op de oorsprong. De
    massaknoop schuift met dezelfde delta mee als de luchtknoop: de (Ta − Tm)-differentie
    uit de aanloop codeert de thermische *toestand* — laadt de kamer op of ontlaadt hij —
    en die is het waard om te houden; alleen het absolute niveau is scheef. Alleen de lucht
    herankeren laat de massaknoop tot ~0.6 °C inconsistent staan, waarna de sterke
    `h_am`-koppeling de luchtknoop binnen één of twee stappen weer van de waarneming af
    trekt (h=1 RMSE 1.76 vs 0.48, RESULTS-phase0 §2.2).

    `tm_mode="ewma"` repliceert `night_forecast.anchor_mass_now`: Tm = exponentieel
    gewogen gemiddelde (τ = `EWMA_TAU_H`) van de *gemeten* kamertemp over het
    aanloopvenster (`meas_window(rid) -> [(t, °C), …]`), bewust zónder sensor-bias-
    inversie — exact wat de nachtvoorspelling in productie doet, zodat het A/B-verschil
    tussen de twee ankerpaden hier geïsoleerd meetbaar is (WS "unify anchoring").

    Geeft `(seed_Ta, seed_Tm, n_anchored)`. Kamers zonder meting houden hun aanloopwaarde
    (fail open, net als `night_forecast.anchor_now`).
    """
    seed = dict(warm_sim["Ta_now"])
    tm = dict(warm_sim["Tm_now"])
    anchored = 0
    for rid in rooms:
        v = meas_at(rid)
        if v is None:
            continue
        ta_new = air_from_sensor(house, rid, v, t_out0)
        delta = ta_new - warm_sim["Ta_now"].get(rid, ta_new)
        seed[rid] = ta_new
        if tm_mode == "shift" and rid in tm:
            tm[rid] = tm[rid] + delta
        elif tm_mode == "ewma" and rid in tm and meas_window is not None and t0 is not None:
            num = den = 0.0
            for ts, temp in meas_window(rid):
                age_h = (t0 - ts).total_seconds() / 3600.0
                if age_h < 0:
                    continue
                w = math.exp(-age_h / EWMA_TAU_H)
                num += w * temp
                den += w
            if den > 0:
                tm[rid] = num / den
        anchored += 1
    return seed, tm, anchored


def fc_snapshot_for(fc_log, t0, max_age_h=FC_SNAPSHOT_MAX_AGE_H):
    """Jongste forecast-snapshot uitgegeven óp of vóór `t0`, mits vers genoeg — anders
    None (die oorsprong wordt dan overgeslagen: er is geen forecast om op te scoren)."""
    best = None
    for s in fc_log:
        if s["issued"] <= t0:
            best = s
        else:
            break
    if best is None or (t0 - best["issued"]).total_seconds() / 3600.0 > max_age_h:
        return None
    return best


def run_origin(house, ds, params, meas, t0, horizon_h, rooms, tm_mode="shift", fc_log=None):
    """Voorspel vanaf één oorsprong. Geeft {kamer: {h_min: (pred, freerun, actual)}}."""
    rows = ds["weather_rows"]
    if fc_log is not None:
        # Échte-forecast-modus: het verleden (aanloop) blijft hindcast — dat is wat de
        # productie op t0 óók als verleden kent — maar vanaf t0 rijden we op wat
        # Open-Meteo op het jongste uitgiftemoment vóór t0 werkelijk voorspelde.
        snap = fc_snapshot_for(fc_log, t0)
        if snap is None:
            return None
        rows = [r for r in rows if r["dt"] <= t0] + \
               [r for r in snap["rows"] if r["dt"] > t0]
    ctx = vio.make_context(house, {"hourly": rows}, t0)

    # Eén raster over aanloop + voorspelling: [t0 − WARMUP_H, t0 + horizon_h].
    tl = vio.build_timeline(house, {"hourly": rows, "current": {}}, ds["log"],
                            t0, WARMUP_H, ctx, beam_iam=True, end_h=horizon_h)
    if not tl:
        return None
    warm = [s for s in tl if s["t"] <= t0]
    fore = [s for s in tl if s["t"] >= t0]
    if len(warm) < 4 or len(fore) < 2:
        return None

    # --- fase 1: aanloop, om de massaknoop te equilibreren --------------------
    seed0 = {}
    for rid in rooms:
        v = meas.at(rid, warm[0]["t"])
        if v is not None:
            seed0[rid] = air_from_sensor(house, rid, v, warm[0]["T_out"])
    for z in list(house.get("rooms", {})) + list(house.get("junctions", {})):
        seed0.setdefault(z, warm[0]["T_out"])
    warm_sim = vp.simulate(house, params, warm, seed0, ctx, snapshot_t=t0)

    # --- fase 2: heranker lucht (+ massa) op wat we op t0 werkelijk meten ------
    warm_start = t0 - timedelta(hours=WARMUP_H)
    seed1, tm1, anchored = anchor_forecast_seed(
        house, rooms, lambda rid: meas.at(rid, t0), warm_sim, fore[0]["T_out"], tm_mode,
        meas_window=lambda rid: [(t, v) for t, v in meas.raw.get(rid, [])
                                 if warm_start <= t <= t0],
        t0=t0)
    if anchored == 0:                          # niets gemeten op de oorsprong
        return None
    fc = vp.simulate(house, params, fore, seed1, ctx, tm_seed=tm1)

    # --- vrijloop-controle: geen herankering, rechtdoor vanuit de aanloop ------
    fr = vp.simulate(house, params, fore, dict(warm_sim["Ta_now"]), ctx,
                     tm_seed=warm_sim["Tm_now"])

    out = {}
    for rid in rooms:
        pred = dict(vp._to_sensor_series(house, fore, rid, fc["series"].get(rid, [])))
        free = dict(vp._to_sensor_series(house, fore, rid, fr["series"].get(rid, [])))
        per_h = {}
        for step in fore:
            t = step["t"]
            h_min = round((t - t0).total_seconds() / 60.0)
            if h_min <= 0:
                continue
            act = meas.at(rid, t, clean_only=True)
            if act is None or t not in pred:
                continue
            per_h[h_min] = (pred[t], free.get(t), act)
        if per_h:
            out[rid] = per_h
    return out


def _worker(payload):
    t0 = payload
    return t0, run_origin(_G["house"], _G["ds"], _G["params"], _G["meas"],
                          t0, _G["horizon_h"], _G["rooms"], _G["tm_mode"], _G["fc_log"])


_G: dict = {}


def _init(house, ds, params, meas, horizon_h, rooms, tm_mode, fc_log):
    _G.update(house=house, ds=ds, params=params, meas=meas,
              horizon_h=horizon_h, rooms=rooms, tm_mode=tm_mode, fc_log=fc_log)


# -------------------------------------------------------------------- baselines

def build_baselines(meas, rooms):
    """Schone samples per kamer — de basis voor persist24 + climatologie."""
    return {rid: [(t, v) for t, v in meas.raw.get(rid, [])
                  if t in meas.clean_ts.get(rid, ())] for rid in rooms}


def clim_at(samples, t, before):
    """Uur-van-de-dag-gemiddelde over samples strikt vóór `before` — geen toekomstlekkage."""
    tot = n = 0.0
    for ts, v in samples:
        if ts >= before:
            break
        if ts.hour == t.hour:
            tot += v
            n += 1
    return tot / n if n else None


# ------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--horizon-h", type=float, default=12.0)
    ap.add_argument("--stride-h", type=float, default=3.0)
    ap.add_argument("--join-tol-min", type=float, default=10.0)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--out", default=None, help="schrijf de per-oorsprong-resultaten als JSON")
    ap.add_argument("--tm-mode", choices=["shift", "warm", "ewma"], default="shift",
                    help="shift = massaknoop schuift mee met het luchtanker (default); "
                         "warm = laat 'm op de aanloopwaarde staan (de naïeve herankering); "
                         "ewma = night_forecast.anchor_mass_now gerepliceerd (τ=8u gewogen "
                         "gemiddelde van de gemeten kamertemp — het productie-ankerpad van "
                         "de nachtvoorspelling, voor de A/B tegen shift)")
    ap.add_argument("--weather", choices=["hindcast", "forecast"], default="hindcast",
                    help="hindcast = perfecte-forecast-aanname (default); forecast = rijd "
                         "vanaf elke oorsprong op de échte Open-Meteo-forecast uit "
                         "data/forecast_log (oorsprongen zonder snapshot worden "
                         "overgeslagen — met een leeg log scoort er dus niets, dat is "
                         "geen fout maar een nog niet gevuld log)")
    ap.add_argument("--origin-hours", default=None,
                    help="komma-gescheiden lokale uren; alleen oorsprongen op die uren "
                         "(bv. 18,19 voor het avond-ankerpunt van de nachtvoorspelling)")
    ap.add_argument("--stratify-openings", action="store_true",
                    help="extra rapport: fysica-fout per kamer gesplitst naar de eigen "
                         "raamstand op de oorsprong (dicht / open, open nog eens naar "
                         "windregime) — de plek waar de scenario-adviezen op leunen")
    ap.add_argument("--summary-out", default=None,
                    help="append een compacte samenvatting (gepoolde + per-kamer RMSE) "
                         "aan dit JSON-bestand — het wekelijkse evaluatiespoor")
    ap.add_argument("--limit", type=int, default=None, help="debug: eerste N oorsprongen")
    ap.add_argument("--keep-learned", action="store_true",
                    help="negeer de PHYSICS_REV-poort en houd de geleerde params vast. Nodig om "
                         "een fysica-wijziging GEÏSOLEERD te meten: zonder dit reset "
                         "merged_params bij een rev-bump alles naar de priors, en meet je de "
                         "parameter-reset in plaats van de fysica.")
    args = ap.parse_args()

    house = vio.load_house()
    ds = vio.load_dataset(house)
    learned = vio.load_learned()
    if args.keep_learned and learned.get("params"):
        learned = dict(learned, physics_rev=vio.PHYSICS_REV)
    params = vio.merged_params(house, learned)
    meas = Measured(ds, args.join_tol_min)
    rooms = [r for r, cfg in house.get("rooms", {}).items()
             if cfg.get("from_window_data")]

    ts_all = sorted(t for s in meas.raw.values() for t, _ in s)
    t_min, t_max = ts_all[0], ts_all[-1]
    first = t_min + timedelta(hours=WARMUP_H)
    last = t_max - timedelta(hours=args.horizon_h)

    origins, t = [], first
    while t <= last:
        origins.append(t)
        t += timedelta(hours=args.stride_h)
    if args.origin_hours:
        hours = {int(h) for h in args.origin_hours.split(",") if h.strip()}
        origins = [t for t in origins if t.hour in hours]
    if args.limit:
        origins = origins[:args.limit]

    fc_log = None
    if args.weather == "forecast":
        fc_log = vio.load_forecast_log()
        with_snap = sum(1 for t in origins if fc_snapshot_for(fc_log, t) is not None)
        print(f"forecast-log: {len(fc_log)} snapshots; {with_snap}/{len(origins)} "
              "oorsprongen hebben er een")
        if not with_snap:
            print("  → nog niets te scoren; het log groeit vanzelf met de kwartierruns mee.")

    print(f"kamers     : {', '.join(rooms)}")
    print(f"record     : {t_min:%Y-%m-%d %H:%M} → {t_max:%Y-%m-%d %H:%M}")
    print(f"oorsprongen: {len(origins)}  (stride {args.stride_h}u"
          + (f", uren {args.origin_hours}" if args.origin_hours else "") + ")")
    print(f"horizon    : {args.horizon_h}u   aanloop {WARMUP_H}u   jobs {args.jobs}")
    print(f"tm-mode    : {args.tm_mode}")
    print("aanname    : perfecte weersvoorspelling (hindcast-weer afgespeeld)\n"
          if args.weather == "hindcast" else
          "weer       : échte Open-Meteo-forecasts (data/forecast_log)\n")

    results = {}
    if args.jobs > 1:
        import multiprocessing as mp
        with mp.Pool(args.jobs, initializer=_init,
                     initargs=(house, ds, params, meas, args.horizon_h,
                               rooms, args.tm_mode, fc_log)) as pool:
            for i, (t0, r) in enumerate(pool.imap_unordered(_worker, origins, chunksize=4)):
                if r:
                    results[t0] = r
                if (i + 1) % 25 == 0:
                    print(f"  {i + 1}/{len(origins)} oorsprongen", flush=True)
    else:
        _init(house, ds, params, meas, args.horizon_h, rooms, args.tm_mode, fc_log)
        for i, t0 in enumerate(origins):
            r = run_origin(house, ds, params, meas, t0, args.horizon_h, rooms,
                           args.tm_mode, fc_log)
            if r:
                results[t0] = r
            if (i + 1) % 25 == 0:
                print(f"  {i + 1}/{len(origins)} oorsprongen", flush=True)

    print(f"\ngescoord: {len(results)} / {len(origins)} oorsprongen\n")
    err = score(results, meas, rooms, args.horizon_h)
    if args.stratify_openings:
        stratify_report(results, ds, house, rooms, args.horizon_h)
    if args.summary_out:
        write_summary(args.summary_out, args, err, rooms, len(results))

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        ser = {t0.isoformat(): {r: {str(h): v for h, v in d.items()}
                                for r, d in rr.items()}
               for t0, rr in results.items()}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"horizon_h": args.horizon_h, "stride_h": args.stride_h,
                       "origins": ser}, f)
        print(f"\ngeschreven: {args.out}")


def _rmse(v):
    return math.sqrt(sum(x * x for x in v) / len(v)) if v else None


def _mae(v):
    return sum(abs(x) for x in v) / len(v) if v else None


def score(results, meas, rooms, horizon_h):
    clim = build_baselines(meas, rooms)

    # errors[methode][kamer][h_bucket] -> lijst
    err = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for t0, rr in results.items():
        for rid, per_h in rr.items():
            t0_meas = meas.at(rid, t0)
            for h_min, (pred, free, act) in per_h.items():
                t = t0 + timedelta(minutes=h_min)
                b = int(math.ceil(h_min / 60.0))
                err["physics"][rid][b].append(pred - act)
                if free is not None:
                    err["freerun"][rid][b].append(free - act)
                if t0_meas is not None:
                    err["persist"][rid][b].append(t0_meas - act)
                p24 = meas.at(rid, t - timedelta(hours=24))
                if p24 is not None:
                    err["persist24"][rid][b].append(p24 - act)
                c = clim_at(clim.get(rid, []), t, t0)
                if c is not None:
                    err["clim"][rid][b].append(c - act)

    methods = ["physics", "freerun", "persist", "persist24", "clim"]
    hb = sorted({b for m in methods for r in err[m] for b in err[m][r]})

    print("=" * 78)
    print(f"RMSE (°C) per kamer — gepoold over de 0–{horizon_h:.0f}u horizon")
    print("=" * 78)
    print(f"{'kamer':10}" + "".join(f"{m:>11}" for m in methods) + f"{'n':>8}")
    for rid in rooms:
        line = f"{rid:10}"
        n = 0
        for m in methods:
            v = [x for b in err[m][rid] for x in err[m][rid][b]]
            line += f"{_rmse(v):11.3f}" if v else f"{'-':>11}"
            if m == "physics":
                n = len(v)
        print(line + f"{n:8}")
    line = f"{'GEPOOLD':10}"
    for m in methods:
        v = [x for r in err[m] for b in err[m][r] for x in err[m][r][b]]
        line += f"{_rmse(v):11.3f}" if v else f"{'-':>11}"
    print(line)

    print()
    print("=" * 78)
    print("RMSE (°C) per horizon-uur — gepoold over de kamers")
    print("=" * 78)
    print(f"{'h':>4}" + "".join(f"{m:>11}" for m in methods) + f"{'n':>8}")
    for b in hb:
        line = f"{b:>4}"
        n = 0
        for m in methods:
            v = [x for r in err[m] for x in err[m][r].get(b, [])]
            line += f"{_rmse(v):11.3f}" if v else f"{'-':>11}"
            if m == "physics":
                n = len(v)
        print(line + f"{n:8}")

    print()
    print("=" * 78)
    print(f"fysica: MAE / bias per kamer (0–{horizon_h:.0f}u)")
    print("=" * 78)
    print(f"{'kamer':10}{'MAE':>9}{'bias':>9}{'p90|e|':>9}")
    for rid in rooms:
        v = [x for b in err["physics"][rid] for x in err["physics"][rid][b]]
        if not v:
            continue
        a = sorted(abs(x) for x in v)
        print(f"{rid:10}{_mae(v):9.3f}{sum(v) / len(v):9.3f}{a[int(.9 * len(a))]:9.3f}")

    print()
    print("=" * 78)
    print("fysica: bias per doel-uur (lokaal) — de diurnale handtekening")
    print("=" * 78)
    by_hour = defaultdict(lambda: defaultdict(list))
    for t0, rr in results.items():
        for rid, per_h in rr.items():
            for h_min, (pred, _free, act) in per_h.items():
                if h_min < 360:            # alleen 6u+ vooruit: de structurele staart
                    continue
                by_hour[(t0 + timedelta(minutes=h_min)).hour][rid].append(pred - act)
    print(f"{'uur':>4}" + "".join(f"{r:>10}" for r in rooms))
    for h in sorted(by_hour):
        if h % 3:
            continue
        line = f"{h:>4}"
        for rid in rooms:
            v = by_hour[h].get(rid, [])
            line += f"{sum(v) / len(v):10.2f}" if v else f"{'-':>10}"
        print(line)

    return err


# ------------------------------------------------------------ raamstand-stratificatie

LOW_WIND_MS = 2.0     # splitsgrens open-raam-regime: het bekende +0.49 °C-residu zit ónder ~2 m/s


def _room_window_open(house, states, rid):
    """Staat er op dit moment een beweegbaar raam van kamer `rid` open (gemeld of
    default)? Roosters tellen niet mee — die staan structureel open."""
    for wid, w in house.get("windows", {}).items():
        if w.get("room") != rid or not w.get("max_open_area_m2"):
            continue
        rep = states.get(wid)
        frac = vp._open_frac(rep, w) if rep is not None else vp._default_frac(w, "window")
        if frac > 0.0:
            return True
    return False


def stratify_report(results, ds, house, rooms, horizon_h):
    """Fysica-fout per kamer, gesplitst naar de eigen raamstand op de oorsprong (en het
    windregime als het raam open staat). Dit is geen counterfactual-validatie — dat kán
    niet zonder een parallel huis — maar het begrenst wél hoe goed elke *arm* van een
    scenario-advies is in de regimes die het huis werkelijk bezocht heeft."""
    wrows = [(r["dt"], r.get("wind_speed") or 0.0) for r in ds["weather_rows"]]
    wrows.sort()

    def wind_mean(t0):
        end = t0 + timedelta(hours=horizon_h)
        v = [w for t, w in wrows if t0 <= t <= end]
        return sum(v) / len(v) if v else None

    # klasse per (oorsprong, kamer): "dicht" | "open-laagwind" | "open-wind"
    errs = defaultdict(lambda: defaultdict(list))
    for t0, rr in results.items():
        states = vio.openings_at(ds["log"], t0)
        wm = wind_mean(t0)
        for rid, per_h in rr.items():
            if _room_window_open(house, states, rid):
                cls = ("open·wind<2" if wm is not None and wm < LOW_WIND_MS
                       else "open·wind≥2")
            else:
                cls = "dicht"
            for _h_min, (pred, _free, act) in per_h.items():
                errs[rid][cls].append(pred - act)

    classes = ["dicht", "open·wind<2", "open·wind≥2"]
    print()
    print("=" * 78)
    print(f"fysica: RMSE / bias per raamstand-klasse op de oorsprong (0–{horizon_h:.0f}u)")
    print("=" * 78)
    print(f"{'kamer':10}" + "".join(f"{c:>22}" for c in classes))
    for rid in rooms:
        line = f"{rid:10}"
        for c in classes:
            v = errs[rid].get(c, [])
            if v:
                line += f"{_rmse(v):7.3f}/{sum(v) / len(v):+6.2f} n={len(v):<5}".rjust(22)
            else:
                line += f"{'-':>22}"
        print(line)
    line = f"{'GEPOOLD':10}"
    for c in classes:
        v = [x for rid in errs for x in errs[rid].get(c, [])]
        if v:
            line += f"{_rmse(v):7.3f}/{sum(v) / len(v):+6.2f} n={len(v):<5}".rjust(22)
        else:
            line += f"{'-':>22}"
    print(line)


# ------------------------------------------------------------------ samenvattingsspoor

SUMMARY_KEEP = 300     # ~6 jaar wekelijkse runs — ruim genoeg voor elke trendvraag


def write_summary(path, args, err, rooms, n_origins):
    """Append één compacte regel evaluatie-uitkomst aan `path` (het wekelijkse
    docs/twin_eval.json-spoor): gepoolde RMSE per methode + per-kamer fysica-RMSE.
    De volle per-oorsprong-dump blijft in tools/out/ (gitignored) — dit spoor is er
    zodat een trend ("wordt de voorspelfout kleiner?") zonder handwerk zichtbaar is."""
    methods = ["physics", "freerun", "persist", "persist24", "clim"]
    pooled = {}
    for m in methods:
        v = [x for r in err[m] for b in err[m][r] for x in err[m][r][b]]
        pooled[m] = round(_rmse(v), 3) if v else None
    per_room = {}
    for rid in rooms:
        v = [x for b in err["physics"][rid] for x in err["physics"][rid][b]]
        if v:
            per_room[rid] = round(_rmse(v), 3)
    entry = {"date": datetime.now(vio.TZ).isoformat(timespec="minutes"),
             "weather": args.weather, "tm_mode": args.tm_mode,
             "horizon_h": args.horizon_h, "stride_h": args.stride_h,
             "origin_hours": args.origin_hours, "n_origins": n_origins,
             "physics_rev": vio.PHYSICS_REV,
             "pooled": pooled, "rooms": per_room}
    try:
        with open(path, encoding="utf-8") as f:
            hist = json.load(f)
        if not isinstance(hist, list):
            hist = []
    except (FileNotFoundError, json.JSONDecodeError):
        hist = []
    hist.append(entry)
    hist = hist[-SUMMARY_KEEP:]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)
    print(f"\nsamenvatting → {path} ({len(hist)} runs)")


if __name__ == "__main__":
    main()
