"""de kinderkamer-nachtvoorspelling (Project 10) — hoe warm wordt de slaapkamer vannacht?

Draait 's avonds (orchestrator-doel 18:45) en
voorspelt met de gekalibreerde luchtstroom-tweeling (Project 8) hoe de kinderkamer
de nacht doorkomt:

1. **Nachtcurve, in twee fasen** — een *aanloop*-sim van 24u (`WARMUP_H`,
   geseed op de oudste tado-temp in dat venster) laat de massaknoop
   equilibreren en re-simuleert het etmaal tot nu met de échte gerapporteerde
   log + het échte weer (geen scenario). Op "nu" wordt herankerd op de meest
   recente tado-meting per kamer (mits vers genoeg — zie
   `ANCHOR_MAX_STALENESS_MIN`) via **het ankerpad van de tweeling zelf**
   (`vent_forecast.anchor_seed`): de luchtknoop naar de meting mét
   sensor-bias-inversie, de massaknoop met dezelfde delta mee. Dat verving in
   aug 2026 de eigen EWMA-massa-ijking (`anchor_mass_now`, τ=8u) die hier
   stond: de A/B op avond-oorsprongen (18/19u, 13u-horizon, 76 dagen shards,
   `tools/horizon_backtest.py --tm-mode ewma`) gaf shift nursery 0,61 °C tegen
   ewma 0,70, gepoold 0,80 tegen 1,03 — en op de kamers met een
   `sensor_outdoor_frac` (bedroom/office) was de EWMA-variant zónder inversie
   zelfs slechter dan helemaal niet herankeren. Massa-ijken zelf blijft de
   grootste enkele winst (warm-modus: gepoold 1,09). Pas ná het anker start
   de *forecast*-sim (nu → morgen 08:00) — zo draagt de nachtvoorspelling
   geen ongecorrigeerde 24u-drift meer mee. De `end_h`-parameter van
   build_timeline rekt die tweede fase op; fetch_weather's forecast_days=2
   dekt de horizon ruim.
2. **Raam-scenario's** — drie forecast-sims vanaf nu: (a) `nursery_small_window`
   dicht, `nursery_stair` dicht (rooster blijft in alle scenario's ongemoeid
   open) — **dit is de aanname voor de échte nacht** — deur én raampje gaan
   's nachts standaard dicht, dus dit scenario is het hoofdbericht + de basis
   voor het slaapzakadvies; (b) `nursery_small_window` open, `nursery_stair` nog
   steeds dicht — zonder de deur geforceerd dicht te houden zou de sim 's
   nachts blijven meekoelen met het (stratifiërende, dak-gekoelde) trapgat
   terwijl de deur in werkelijkheid dicht gaat; (c) **alles open** —
   `nursery_small_window` open én *elk* raam en *elke* deur in het huis open
   (incl. `nursery_stair`) — het meest gunstige doorwaai-scenario. (b) en (c)
   zijn louter een informatieve vergelijking ("zou dit schelen"), geen advies
   om het raampje of de deuren ook echt open te zetten.
3. **Gordijnroutine** — het verduisteringsgordijn vóór `nursery_window` (het grote
   vaste raam, een boom + overburen schaduwen het al deels — vandaar het lage
   horizon_elevation_deg — maar niet 's avonds vóór het dichtgaat) gaat elke
   avond ~19:00 dicht, ongeacht wat de openingen-log op dat
   moment toevallig meldt. Sinds aug 2026 komt die routine uit
   `house_model.json` (`routines`-blok, afgedwongen via `vio.apply_routines`)
   — dezelfde config die de 12u-vooruitblik van de tweeling gebruikt, i.p.v.
   de hardcode die hier stond. Toegepast op **beide** fasen: zonder dit
   rekende de aanloopsim een avond met een in werkelijkheid al dicht gordijn
   alsnog als open door (fors avondzon-vermogen door een 3×1.5m raam), wat de
   niet-geankerde massaknoop een structurele warm-bias gaf die de
   forecast-fase optilde — een voorspelde nachtstijging die in de echte
   tado-metingen niet terugkwam (gediagnosticeerd juli 2026: 07:00 voorspeld
   ~1°C te warm, twee dagen op rij, terwijl de gemeten kamer al daalde).
4. **Tog/slaapzak-advies** — het nachtgemiddelde van het dicht-scenario door de
   standaard peuter-slaapzaktabel.

Bewust GEEN WU-verfijning (de sim is forecast-gedreven en de seed komt van
tado — het station voegt hier niets toe en zo blijven de WU-secrets uit deze
workflow) en geen dashboard-artefact (v1 is stateless; alleen Telegram).

Verzend-poort: in het zomerseizoen (mei–sep) elke avond; daarbuiten alleen als
de voorspelde nacht-max ≥ NIGHT_INTEREST_C (een warme najaarsnacht telt nog,
een stabiele gestookte winternacht niet). Gaat naar de **groepschat**
(`TELEGRAM_CHAT_GROUP_ID`), net als de weerbriefing — niet naar de privé-chat.
"""

import json
import os
from datetime import datetime, timedelta

import vent_forecast as vfc
import vent_io as vio
import vent_physics as vp
from notify import run_guarded, send_telegram
from shared_const import TZ, format_date_nl

ROOM_ID = "nursery"                  # zone-id in house_model.json
WINDOW_ID = "nursery_small_window"   # het openbare raampje voor het scenario
DOOR_ID = "nursery_stair"            # deur naar het trapgat — 's nachts standaard dicht
WD_KEY = "Nursery"                   # sleutel in window_data.json / ROOM_COMFORT

NIGHT_START_H = 21               # nachtvenster: vanavond 21:00 → morgen 08:00
NIGHT_END_H = 8
MARKS = (23, 3, 7)               # uur-punten in het bericht
WARMUP_H = 24.0                  # aanloop-sim zodat de massaknoop equilibreert
ANCHOR_MAX_STALENESS_MIN = 30    # oudere actuele meting → niet vertrouwen, sim-waarde staat
SEASON_MONTHS = range(5, 10)     # mei–sep: altijd sturen
NIGHT_INTEREST_C = 19.0          # daarbuiten: alleen bij een warme nacht

# Voorspellingslog (aug 2026): elke avond-run legt zijn dicht-scenario-voorspelling vast in
# een maand-shard, zodat tools/night_verify.py hem de ochtend erna kan afrekenen tegen de
# gemeten kinderkamer-temps die tóch al in data/twin2_history staan. Vóór dit log was deze
# voorspelling precies één keer gevalideerd (9 held-out nachten, RMSE 0,86) en daarna
# nooit meer — elke wijziging aan het ankerpad was "hopen" i.p.v. "meten".
NIGHT_LOG_DIR = os.getenv("NIGHT_FC_LOG_DIR", "data/night_forecast_log")

# Standaard peuter-slaapzaktabel op het voorspelde nachtgemiddelde:
# (ondergrens °C, tog, kleding) — eerste rij waarvan de grens gehaald wordt wint.
TOG_TABLE = [
    (24.0, "0.5 tog", "korte pyjama of alleen romper"),
    (21.0, "1.0 tog", "korte pyjama"),
    (18.0, "2.5 tog", "lange pyjama"),
    (16.0, "2.5 tog", "warme pyjama + romper"),
    (None, "3.5 tog", "warme pyjama + romper"),
]


# ── Pure hulpfuncties ─────────────────────────────────────────────────────────────────

def hours_until_morning(now: datetime, end_h: int = NIGHT_END_H) -> float:
    """Uren van nu tot morgen `end_h`:00 lokale tijd (de sim-horizon)."""
    target = (now + timedelta(days=1)).replace(hour=end_h, minute=0,
                                               second=0, microsecond=0)
    return (target - now).total_seconds() / 3600.0


def scenario_timeline(timeline: list[dict], now: datetime, state: str) -> list[dict]:
    """Kopie van de timeline waarin het raampje vanaf nu op `state` staat én de deur
    naar het trapgat vanaf nu dicht (de aanname voor een échte nacht, in beide
    scenario's — alleen het raampje varieert); het verleden (de gemelde log) blijft
    onaangeroerd, het origineel wordt niet gemuteerd."""
    return [({**step, "states": {**step["states"], WINDOW_ID: state, DOOR_ID: "dicht"}}
             if step["t"] >= now else step)
            for step in timeline]


def all_open_timeline(timeline: list[dict], house: dict, now: datetime) -> list[dict]:
    """Kopie van de timeline waarin vanaf nu élk raam én élke deur in het huis open
    staat (incl. `nursery_stair`) — het meest gunstige doorwaai-scenario, puur informatief
    (geen advies om alles ook echt open te zetten). Ramen zonder bewegend deel
    (`max_open_area_m2` 0) blijven fysiek dicht, ook al krijgen ze de "open"-state — de
    sim rekent er dan gewoon geen oppervlak voor. Het verleden (de gemelde log) blijft
    onaangeroerd, het origineel wordt niet gemuteerd."""
    override = {eid: "open" for eid in list(house.get("windows", {}))
               + list(house.get("doors", {}))}
    return [({**step, "states": {**step["states"], **override}}
             if step["t"] >= now else step)
            for step in timeline]


def night_stats(series: list[tuple], now: datetime) -> dict | None:
    """Nachtstatistiek uit een sim-serie [(t, °C)]: temps op de MARKS-uren
    (dichtstbijzijnde rasterpunt), min/max/gemiddelde over het nachtvenster."""
    start = now.replace(hour=NIGHT_START_H, minute=0, second=0, microsecond=0)
    end = (now + timedelta(days=1)).replace(hour=NIGHT_END_H, minute=0,
                                            second=0, microsecond=0)
    night = [(t, v) for t, v in series if start <= t <= end]
    if not night:
        return None
    temps = [v for _, v in night]
    stats = {"min": min(temps), "max": max(temps),
             "mean": sum(temps) / len(temps), "marks": {}}
    for hh in MARKS:
        base = now if hh >= NIGHT_START_H else now + timedelta(days=1)
        mark = base.replace(hour=hh, minute=0, second=0, microsecond=0)
        t, v = min(night, key=lambda s: abs((s[0] - mark).total_seconds()))
        if abs((t - mark).total_seconds()) <= 1800:   # ≤ een half uur ernaast
            stats["marks"][hh] = v
    return stats


def tog_advice(night_mean: float) -> tuple[str, str]:
    for floor, tog, clothing in TOG_TABLE:
        if floor is None or night_mean >= floor:
            return tog, clothing
    return TOG_TABLE[-1][1], TOG_TABLE[-1][2]   # pragma: no cover — vangnet


def build_message(now: datetime, inside_now: float | None, out_min: float | None,
                  closed_stats: dict, open_stats: dict, all_open_stats: dict,
                  reported_open: bool, *, band_07: tuple | None = None) -> str:
    """Het avondbericht. `closed_stats` = het hoofdscenario (deur + raampje
    dicht, rooster open — de aanname voor een echte nacht); `open_stats`
    (raampje open, deur dicht) en `all_open_stats` (raampje + alle ramen/deuren
    in het huis open) zijn puur informatieve vergelijkingen. `reported_open` =
    de huidige gemelde raampje-stand (waarschuwt als die van de aanname
    afwijkt). `band_07` = optionele (laag, hoog)-marge rond het 07:00-getal
    uit de empirische band (zie `band_for`)."""
    d = format_date_nl(now.date())
    lines = [f"🌙 <b>Kinderkamer-nacht</b> — {d}"]
    ctx = []
    if inside_now is not None:
        ctx.append(f"Nu {inside_now:.1f}° binnen")
    if out_min is not None:
        ctx.append(f"buiten koelt naar {out_min:.0f}°")
    if ctx:
        lines.append(" · ".join(ctx))

    afwijking = (" (raampje staat nu open — voorspelling gaat uit van dicht)"
                if reported_open else "")
    marks = closed_stats["marks"]
    mark_txt = " · ".join(f"{hh:02d}:00 <b>{marks[hh]:.1f}°</b>"
                          for hh in MARKS if hh in marks)
    lines.append(f"\nVoorspelling (deur + raampje dicht, rooster open){afwijking}:")
    lines.append(f"{mark_txt}  (min {closed_stats['min']:.1f}°)")
    if band_07 is not None:
        lines.append(f"Typisch {band_07[0]:.1f}–{band_07[1]:.1f}° om 07:00 "
                     "(empirische marge, excl. weersvoorspelfout)")

    o7 = open_stats["marks"].get(7)
    c7 = closed_stats["marks"].get(7)
    if o7 is not None and c7 is not None:
        delta = o7 - c7
        lines.append(f"\n🪟 Raampje ook open zou <b>{delta:+.1f}°</b> schelen om 07:00 "
                     f"({o7:.1f}° i.p.v. {c7:.1f}°)")

    a7 = all_open_stats["marks"].get(7)
    if a7 is not None and c7 is not None:
        delta_all = a7 - c7
        lines.append(f"🏠 Alles open (heel huis) zou <b>{delta_all:+.1f}°</b> schelen om 07:00 "
                     f"({a7:.1f}° i.p.v. {c7:.1f}°)")

    tog, clothing = tog_advice(closed_stats["mean"])
    lines.append(f"\n👶 Slaapzak: <b>{tog} + {clothing}</b> "
                 f"(nachtgemiddeld ~{closed_stats['mean']:.0f}°, deur + raampje dicht)")
    return "\n".join(lines)


def should_send(now: datetime, night_max: float) -> bool:
    if now.month in SEASON_MONTHS:
        return True
    return night_max >= NIGHT_INTEREST_C


def append_night_log(now: datetime, stats: dict, series_dicht: list[tuple],
                     tog: str, sent: bool) -> bool:
    """Append de voorspelling van vanavond aan de maand-shard (`NIGHT_LOG_DIR`), één rij
    per lokale datum — een tweede dispatch dezelfde avond (fallback-cron) is een no-op.
    De dicht-serie gaat er compact in ([epoch, °C×10] per kwartierpunt, alleen het
    nachtvenster + de aanloop vanaf nu); van open/all_open alleen de statistiek — het
    verschil is wat het bericht meldt, de volle serie is alleen voor het hoofdscenario
    nodig om tegen de metingen te leggen. Geeft True als er geschreven is.

    Bewust GEEN `reported_open`-veld (meer): dat was een gedateerde afgeleide van de
    privé openingen-log in een gecommit bestand. De verificatie (tools/night_verify.py)
    scoort toch onvoorwaardelijk tegen de ruwe metingen en leest het veld nergens."""
    month = now.strftime("%Y-%m")
    path = os.path.join(NIGHT_LOG_DIR, f"{month}.json")
    try:
        with open(path, encoding="utf-8") as f:
            shard = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        shard = {"schema": 1, "month": month, "forecasts": []}
    rows = shard.setdefault("forecasts", [])
    today = now.date().isoformat()
    if any(r.get("date") == today for r in rows):
        return False
    def _stats_out(s):
        return {"min": round(s["min"], 2), "max": round(s["max"], 2),
                "mean": round(s["mean"], 2),
                "marks": {str(h): round(v, 2) for h, v in s["marks"].items()}}
    rows.append({
        "date": today, "t": now.isoformat(), "sent": sent,
        "tog": tog,
        "scenarios": {k: _stats_out(s) for k, s in stats.items()},
        "series_dicht": [[int(t.timestamp()), int(round(v * 10))]
                         for t, v in series_dicht if t >= now],
    })
    os.makedirs(NIGHT_LOG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(shard, f, ensure_ascii=False, separators=(",", ":"))
    return True


# ── Runner ────────────────────────────────────────────────────────────────────────────

def main(now: datetime | None = None) -> None:
    now = now or datetime.now(TZ)
    print(f"[kinderkamer-nacht] Start — {now.isoformat()}")

    house = vio.load_house()
    weather = vio.fetch_weather(*vio.house_location(house))
    # Run-context: locatie + buur-/bodem-anker, expliciet doorgegeven (RunContext) — het
    # module-global-rebinden waar dit bestand de naamgever van was ("de night_forecast-les")
    # bestaat in de herbouw niet meer; vergeten is nu een TypeError. make_context legt óók
    # het zomerplafond (NEIGHBOR_SUMMER_CAP) op het buur-anker — het oude rebinden hier
    # deed dat niet, waardoor deze voorspelling op hittegolfdagen met een te warm anker
    # rekende; nu exact dezelfde gekapte curve als de tweeling zelf (cap23_night).
    ctx = vio.make_context(house, weather, now)
    print(f"[buren] party-muur-anker = {ctx.neighbor_temp:.1f} °C · "
          f"bodem-anker = {ctx.ground_temp:.1f} °C")

    log = vio.load_openings_log()
    params = vio.merged_params(house, vio.load_learned())
    wd = vio.load_window_data()

    # ── Fase 1: aanloop (nu−24u → nu), werkelijk weer + werkelijke log, geen scenario ──
    # Laat de massaknoop equilibreren en re-simuleert het etmaal tot nu; `end_h=0.0` zodat
    # het raster exact op `now` eindigt (start = now−WARMUP_H, stap 0.25u → altijd exact).
    om_learned = vio.om_learned_from(wd)
    warmup_tl = vio.build_timeline(house, weather, log, now, WARMUP_H, ctx,
                                   beam_iam=True, end_h=0.0, om_learned=om_learned)
    if not warmup_tl:
        print("[kinderkamer-nacht] Geen weerdata → stop.")
        raise SystemExit(1)
    # Vaste dagritmes (gordijnroutine e.d.) uit house_model.json — op béíde fasen, zie
    # de module-docstring §3. De log gaat mee: een expliciete melding in het lopende
    # routinevenster wint van de routine.
    warmup_tl = vio.apply_routines(warmup_tl, house, log=log)

    actual = vio.collect_actual(house, wd, now - timedelta(hours=WARMUP_H))
    warmup_seed = {rid: s[0][1] for rid, s in actual.items() if s}   # oudste meting in het venster
    for rid in house.get("rooms", {}):
        warmup_seed.setdefault(rid, warmup_tl[0]["T_out"])

    warmup_sim = vp.simulate(house, params, warmup_tl, warmup_seed, ctx, snapshot_t=now)
    ta_now = dict(warmup_sim.get("Ta_now", warmup_sim["Ta"]))
    tm_now = warmup_sim.get("Tm_now", warmup_sim["Tm"])

    # ── Herankeren op de meting — via het ankerpad van de tweeling (vent_forecast.
    # anchor_seed): luchtknoop naar de verse tado-meting mét sensor-bias-inversie, de
    # massaknoop met dezelfde delta mee. Massa-ijken is de grootste enkele winst (zonder:
    # de warmup-drift trekt de geijkte lucht er binnen een paar uur weer doorheen); de
    # delta-verschuiving won de A/B van de oude EWMA-ijking — zie de module-docstring §1.
    # Kamers zonder verse meting (≤ ANCHOR_MAX_STALENESS_MIN) houden hun sim-waarde.
    measured_now = vfc.latest_actual(actual, now,
                                     max_age_h=ANCHOR_MAX_STALENESS_MIN / 60.0)
    ta_now, tm_now, anchored = vfc.anchor_seed(
        house, {"Ta_now": ta_now, "Tm_now": tm_now}, measured_now,
        warmup_tl[-1]["T_out"])
    # Alleen het áántal geankerde kamers loggen — de per-kamer-deltas bevatten de
    # gemeten binnentemperaturen en horen niet in het publieke Actions-log.
    if anchored:
        print(f"[kinderkamer-nacht] anker-correctie toegepast ({anchored} kamer(s)).")

    # ── Fase 2: forecast (nu → morgen 08:00), scenario-geforceerd, geseed op het anker ──
    end_h = hours_until_morning(now)
    fcst_tl = vio.build_timeline(house, weather, log, now, 0.0, ctx,
                                 beam_iam=True, end_h=end_h, om_learned=om_learned)
    if not fcst_tl:
        print("[kinderkamer-nacht] Geen forecast-data → stop.")
        raise SystemExit(1)
    fcst_tl = vio.apply_routines(fcst_tl, house, log=log)
    print(f"[kinderkamer-nacht] forecast t/m {fcst_tl[-1]['t'].isoformat()} (end_h={end_h:.1f})")

    stats = {}
    series_dicht = []
    for state in ("open", "dicht"):
        sim = vp.simulate(house, params, scenario_timeline(fcst_tl, now, state),
                          ta_now, ctx, tm_seed=tm_now)
        stats[state] = night_stats(sim["series"].get(ROOM_ID, []), now)
        if state == "dicht":
            series_dicht = sim["series"].get(ROOM_ID, [])
    sim_all = vp.simulate(house, params, all_open_timeline(fcst_tl, house, now),
                          ta_now, ctx, tm_seed=tm_now)
    stats["all_open"] = night_stats(sim_all["series"].get(ROOM_ID, []), now)
    if not stats["open"] or not stats["dicht"] or not stats["all_open"]:
        print("[kinderkamer-nacht] Geen nachtvenster in de sim-serie → stop.")
        raise SystemExit(1)

    closed_stats = stats["dicht"]
    open_stats = stats["open"]
    all_open_stats = stats["all_open"]

    # Huidige gemelde raampje-stand (voor de afwijking-kopregel).
    w = house["windows"][WINDOW_ID]
    rep = vio.openings_at(log, now).get(WINDOW_ID)
    frac = vp._open_frac(rep, w) if rep is not None else vp._default_frac(w, "window")
    reported_open = frac > 0.0

    inside_now = (wd.get("rooms", {}).get(WD_KEY, {}) or {}).get("inside")
    night_out = [s["T_out"] for s in fcst_tl
                 if s["t"] >= now and s.get("T_out") is not None]
    out_min = min(night_out) if night_out else None

    night_max = max(stats["open"]["max"], stats["dicht"]["max"], stats["all_open"]["max"])
    # Marge rond het 07:00-getal uit de empirische band (ontbreekt het bestand of de
    # mark → geen regel; fail open zoals altijd). Loader + celkeuze wonen in vent_io —
    # het koelplan (Project 14) citeert dezelfde band.
    h07 = (now + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
    band_07 = vio.band_for(closed_stats["marks"].get(7),
                           (h07 - now).total_seconds() / 3600.0,
                           vio.load_uncertainty(), room=ROOM_ID)
    sent = False
    if should_send(now, night_max):
        msg = build_message(now, inside_now, out_min, closed_stats, open_stats,
                            all_open_stats, reported_open, band_07=band_07)
        if os.environ.get("DRY_RUN") == "1":
            # Berichttekst (kamertemps + raamstand) alleen onder DRY_RUN — publiek log.
            print(msg)
            print("DRY_RUN=1, niet verzonden.")
        else:
            send_telegram(msg, chat_id=os.getenv("TELEGRAM_CHAT_GROUP_ID"),
                          muted_in_quiet=True)
            sent = True
    else:
        print(f"[kinderkamer-nacht] buiten seizoen en koele nacht (max {night_max:.1f}°) — stil.")

    # Voorspellingslog — óók op een stille avond (een koude winternacht is nog steeds een
    # verifieerbare voorspelling), maar niet onder DRY_RUN: een testdispatch om 14:00 zou
    # anders het datum-slot van de échte avondrun opeten (zelfde afweging als het
    # experimentlogboek van de verwarming).
    if os.environ.get("DRY_RUN") == "1":
        print("[log] DRY_RUN=1 — voorspellingslog niet geschreven.")
    else:
        tog, _clothing = tog_advice(closed_stats["mean"])
        wrote = append_night_log(now, stats, series_dicht, tog, sent)
        print("[log] voorspelling vastgelegd." if wrote
              else "[log] al een voorspelling voor vandaag — log ongemoeid.")


if __name__ == "__main__":
    run_guarded(main, "kinderkamer-nacht", chat_id=os.getenv("TELEGRAM_CHAT_GROUP_ID"),
               fail_threshold=2)
