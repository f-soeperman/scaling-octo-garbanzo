#!/usr/bin/env python3
"""
cooldown_notify.py — het avond-koelplan (Project 14): welke ramen en deuren open vannacht?

Draait 's avonds (orchestrator-doel 21:15, ná de kinderkamer-nachtvoorspelling en vóór het naar
bed gaan) en beantwoordt met de gekalibreerde tweeling de vraag waar hij voor bestaat:
niet alleen *hoe warm wordt het*, maar *wat moet ik openzetten om dat te veranderen*.

Opzet (het bewezen twee-fasen-patroon van night_forecast):
1. **Aanloop** — 24u re-simulatie op de échte log + het échte weer, dan herankeren op de
   verse tado-metingen via het ankerpad van de tweeling (vent_forecast.anchor_seed:
   lucht mét sensor-bias-inversie, massa met dezelfde delta mee).
2. **Scenario-sims** — de gecureerde grammatica van vent_suggest (~15 standencombinaties,
   gesnoeid op regen/windstoten/nacht-veiligheid via de `advice`-vlaggen in
   house_model.json), elk gesimuleerd over [nu, morgen 08:00] bóvenop de dicht-baseline.
3. **Rangschikking + bericht** — per advieskamer het 07:00-verschil t.o.v. dicht,
   geklemd op de comfortband; het kleinste effectieve plan wint; één runner-up en het
   alles-open-plafond (nadrukkelijk geen advies) erbij. Stil als geen kamer koeling
   nodig heeft of het beste plan onder DELTA_MIN_C blijft.

Gaat naar de **groepschat** (TELEGRAM_CHAT_GROUP_ID), zoals de nachtvoorspelling.
`DRY_RUN=1` print zonder te sturen. Read-only op vent_physics/vent_io (ctx via
make_context — vergeten = TypeError); schrijft niets, commit niets.
"""

import os
from datetime import datetime

import vent_forecast as vfc
import vent_io as vio
import vent_physics as vp
import vent_suggest as vs
from notify import run_guarded, send_telegram
from shared_const import TZ

WARMUP_H = 24.0                  # aanloop-sim zodat de massaknoop equilibreert
ANCHOR_MAX_STALENESS_MIN = 30    # zelfde versheidsgrens als de nachtvoorspelling


def sensor_series(house: dict, steps: list[dict], sim: dict) -> dict:
    """Sim-uitvoer → sensorruimte per kamer (wat tado morgen echt zal tonen)."""
    return {rid: vp._to_sensor_series(house, steps, rid, s)
            for rid, s in sim["series"].items()}


def main() -> None:
    now = datetime.now(TZ)
    print(f"[koelplan] Start — {now.isoformat()}")
    if now.month not in vs.SEASON_MONTHS:
        print("[koelplan] buiten het zomerseizoen — stil.")
        return

    house = vio.load_house()
    weather = vio.fetch_weather(*vio.house_location(house))
    ctx = vio.make_context(house, weather, now)
    log = vio.load_openings_log()
    params = vio.merged_params(house, vio.load_learned())
    wd = vio.load_window_data()
    om_learned = vio.om_learned_from(wd)

    # ── Fase 1: aanloop + anker (zie night_forecast voor de volledige motivatie) ──
    warmup_tl = vio.build_timeline(house, weather, log, now, WARMUP_H, ctx,
                                   beam_iam=True, end_h=0.0, om_learned=om_learned)
    if not warmup_tl:
        print("[koelplan] Geen weerdata → stop.")
        raise SystemExit(1)
    warmup_tl = vio.apply_routines(warmup_tl, house, log=log)

    actual = vio.collect_actual(house, wd, now - vio._timedelta_h(WARMUP_H))
    warmup_seed = {rid: s[0][1] for rid, s in actual.items() if s}
    for rid in house.get("rooms", {}):
        warmup_seed.setdefault(rid, warmup_tl[0]["T_out"])
    warmup_sim = vp.simulate(house, params, warmup_tl, warmup_seed, ctx, snapshot_t=now)

    measured_now = vfc.latest_actual(actual, now,
                                     max_age_h=ANCHOR_MAX_STALENESS_MIN / 60.0)
    ta_now, tm_now, anchored = vfc.anchor_seed(
        house, warmup_sim, measured_now, warmup_tl[-1]["T_out"])
    print(f"[koelplan] {anchored} kamer(s) op de meting geankerd.")

    # ── Fase 2: scenario-sims over [nu, morgen 08:00] ──
    end_h = vs.hours_until_morning(now)
    fcst_tl = vio.build_timeline(house, weather, log, now, 0.0, ctx,
                                 beam_iam=True, end_h=end_h, om_learned=om_learned)
    if not fcst_tl:
        print("[koelplan] Geen forecast-data → stop.")
        raise SystemExit(1)
    fcst_tl = vio.apply_routines(fcst_tl, house, log=log)

    wet, gusty = vs.night_weather(fcst_tl, now)
    if wet or gusty:
        print(f"[koelplan] restricties: regen={wet} vlagen={gusty}")
    scenarios = vs.practical_filter(vs.scenario_set(house), house, wet, gusty)
    base_states = vs.baseline_states(house)

    def run(states: dict) -> dict:
        tl = vs.apply_scenario(fcst_tl, now, states)
        sim = vp.simulate(house, params, tl, ta_now, ctx, tm_seed=tm_now)
        return sensor_series(house, tl, sim)

    base_series = run(base_states)
    bands = vs.room_bands(house)

    scored = []
    for sc in scenarios:
        # Scenario bóvenop de dicht-baseline: "solo kinderkamerraampje" betekent alléén dat
        # raampje open, niet "plus wat de log toevallig nog open heeft staan".
        series = run({**base_states, **sc["states"]})
        res = vs.score_plan(base_series, series, bands, now, n_actions=len(sc["states"]))
        if res:
            scored.append({**sc, **res})
    ranked = vs.rank_plans(scored)
    ceiling = next((s for s in scored if s.get("ceiling")), None)

    # Scenario-ranglijst alleen onder DRY_RUN — welke ramen het huis vanavond zou
    # openzetten hoort niet in het publieke Actions-log.
    if os.environ.get("DRY_RUN") == "1":
        for s in ranked[:5]:
            print(f"[koelplan] {s['id']:24} score {s['score']:+.2f} "
                  f"(voordeel {s['benefit']:.2f}, onderkoeling {s['overcool']:.2f})")

    if not vs.should_send(now, ranked):
        why = ("geen kamer heeft koeling nodig" if ranked else "geen scoorbaar scenario")
        if ranked and ranked[0]["score"] < vs.DELTA_MIN_C:
            why = f"beste plan blijft onder {vs.DELTA_MIN_C}° ({ranked[0]['score']:+.2f})"
        print(f"[koelplan] {why} — stil.")
        return

    best = ranked[0]
    # Marge-regel op de kamer met het grootste voordeel, uit de gedeelde band.
    band_line = None
    top_rid = max((r for r in best["rooms"].items() if r[1]["needs"]),
                  key=lambda kv: kv[1]["benefit"], default=(None, None))[0]
    if top_rid:
        band = vio.band_for(best["rooms"][top_rid]["s07"], end_h,
                            vio.load_uncertainty(), room=top_rid)
        if band:
            band_line = (f"(typisch {band[0]:.1f}–{band[1]:.1f}° — empirische marge, "
                         "excl. weersvoorspelfout)")

    night_out = [s["T_out"] for s in fcst_tl if s.get("T_out") is not None]
    out_min = min(night_out) if night_out else None

    msg = vs.build_message(now, ranked, ceiling, house, out_min, wet,
                           band_line=band_line)
    if os.environ.get("DRY_RUN") == "1":
        # Berichttekst (kamertemps + raam-plan) alleen onder DRY_RUN — publiek log.
        print(msg)
        print("DRY_RUN=1, niet verzonden.")
        return
    send_telegram(msg, chat_id=os.getenv("TELEGRAM_CHAT_GROUP_ID"), muted_in_quiet=True)


if __name__ == "__main__":
    run_guarded(main, "koelplan", chat_id=os.getenv("TELEGRAM_CHAT_GROUP_ID"),
                fail_threshold=2)
