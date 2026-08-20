"""Pure-logica-tests voor de kinderkamer-nachtvoorspelling (`night_forecast.py`, Project 10).

Geen netwerk of Gist: de sim-integratietest draait op een mini-fixture-huis met
alleen de nursery-zone; main() wordt getest met gemonkeypatchte weer/artefact-seams
(o.a. dat de RunContext-ankers — buur + bodem — écht via make_context/build_timeline
doorgegeven worden; het oude module-global-rebinden bestaat in de herbouw niet meer).
"""
import math
from datetime import datetime, timedelta

import pytest

import night_forecast as nf
import vent_forecast as vfc
import vent_io as vio
import vent_physics as vp
from shared_const import TZ

NOW = datetime(2026, 7, 2, 18, 45, tzinfo=TZ)

# Reproduceert exact het oude module-default-gedrag (_LAT/_LON/_NEIGHBOR_TEMP/_GROUND_TEMP)
# voor de directe build_timeline/simulate-tests; main() bouwt zijn eigen ctx via make_context.
CTX = vp.RunContext(lat=52.09, lon=5.12,
                    neighbor_temp=vp.NEIGHBOR_TEMP, ground_temp=vp.GROUND_TEMP)

HOUSE = {
    "location": {"lat": 52.09, "lon": 5.12},
    "terrain": {},
    "rooms": {"nursery": {"label": "Nursery", "volume_m3": 32.0, "exterior_wall_m2": 12.0,
                      "floor": 0, "from_window_data": "Nursery"},
             "stair": {"label": "Trap", "volume_m3": 20.0, "exterior_wall_m2": 8.0,
                       "floor": 1}},
    "junctions": {},
    "windows": {
        "nursery_window": {"room": "nursery", "facade_azimuth_deg": 309.0, "glass_m2": 4.5,
                       "max_open_area_m2": 0.0, "tilt_deg": 90.0,
                       "center_height_m": 1.5, "shading": "lamella",
                       "shade": {"factor": 0.12, "label": "Gordijn"}},
        "nursery_small_window": {"room": "nursery", "facade_azimuth_deg": 309.0,
                             "glass_m2": 0.16, "max_open_area_m2": 0.16,
                             "open_type": "casement", "tilt_frac": 0.35,
                             "tilt_deg": 90.0, "center_height_m": 1.8,
                             "shading": "none"},
    },
    "vents": {},
    "doors": {
        "nursery_stair": {"between": ["nursery", "stair"], "area_m2": 1.8,
                     "center_height_m": 1.0, "default_state": "open",
                     "label": "Kinderkamer ↔ trap"},
    },
}


def _rows(now=NOW, night_out=14.0, day_out=26.0):
    """Synthetische dag/nacht-cyclus rond `now` (2 dagen terug + 2 vooruit)."""
    t0 = (now - timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    rows = []
    for h in range(96):
        t = t0 + timedelta(hours=h)
        sun = max(0.0, math.sin(math.pi * (t.hour - 5.5) / 15.5))
        rows.append({"dt": t, "T_out": night_out + (day_out - night_out) * sun,
                     "rh": 55, "precip": 0.0, "wind_speed": 2.5, "wind_dir": 220.0,
                     "gust": 4.0, "shortwave": 800 * sun, "direct": 600 * sun,
                     "diffuse": 200 * sun})
    return rows


# ── Horizon + scenario-injectie ──────────────────────────────────────────────────────

def test_hours_until_morning():
    assert nf.hours_until_morning(NOW) == pytest.approx(13.25)
    laat = datetime(2026, 7, 2, 23, 30, tzinfo=TZ)
    assert nf.hours_until_morning(laat) == pytest.approx(8.5)


def test_timeline_reaches_morning():
    tl = vio.build_timeline(HOUSE, {"hourly": _rows()}, [], NOW, 24.0, CTX,
                            end_h=nf.hours_until_morning(NOW))
    morgen_745 = (NOW + timedelta(days=1)).replace(hour=7, minute=45)
    assert tl[-1]["t"] >= morgen_745


def test_scenario_injection_future_only():
    tl = vio.build_timeline(HOUSE, {"hourly": _rows()}, [], NOW, 4.0, CTX,
                            end_h=6.0)
    open_tl = nf.scenario_timeline(tl, NOW, "open")
    for orig, sc in zip(tl, open_tl):
        if sc["t"] >= NOW:
            assert sc["states"]["nursery_small_window"] == "open"
            assert sc["states"]["nursery_stair"] == "dicht"   # deur dicht in béíde scenario's
            assert sc is not orig                      # kopie, geen mutatie
        else:
            assert sc is orig                          # verleden blijft de log
    assert "nursery_small_window" not in tl[-1]["states"]  # origineel ongemuteerd
    assert "nursery_stair" not in tl[-1]["states"]


def test_scenario_forces_door_closed_in_both_states():
    tl = vio.build_timeline(HOUSE, {"hourly": _rows()}, [], NOW, 4.0, CTX,
                            end_h=6.0)
    for state in ("open", "dicht"):
        sc = nf.scenario_timeline(tl, NOW, state)
        for step in sc:
            if step["t"] >= NOW:
                assert step["states"]["nursery_stair"] == "dicht"


def test_all_open_timeline_opens_every_window_and_door():
    tl = vio.build_timeline(HOUSE, {"hourly": _rows()}, [], NOW, 4.0, CTX,
                            end_h=6.0)
    all_open = nf.all_open_timeline(tl, HOUSE, NOW)
    for orig, sc in zip(tl, all_open):
        if sc["t"] >= NOW:
            for wid in HOUSE["windows"]:
                assert sc["states"][wid] == "open"
            for did in HOUSE["doors"]:
                assert sc["states"][did] == "open"
            assert sc is not orig                      # kopie, geen mutatie
        else:
            assert sc is orig                          # verleden blijft de log
    assert "nursery_stair" not in tl[-1]["states"]           # origineel ongemuteerd


def test_closed_door_retains_more_heat_overnight():
    # Kille trap (14°, zoals de koudere schacht 's nachts); nursery start warm. Met de deur
    # geforceerd dicht (het echte gedrag) moet nursery minder afkoelen dan een controle-run
    # waarin de deur openblijft.
    tl = vio.build_timeline(HOUSE, {"hourly": _rows()}, [], NOW, 24.0, CTX,
                            end_h=nf.hours_until_morning(NOW))
    params = vio.default_params(HOUSE)
    seed = {"nursery": 24.0, "stair": 14.0}

    door_closed_tl = nf.scenario_timeline(tl, NOW, "dicht")
    door_open_tl = [({**step, "states": {**step["states"], nf.WINDOW_ID: "dicht"}}
                     if step["t"] >= NOW else step) for step in tl]

    sim_closed = vp.simulate(HOUSE, params, door_closed_tl, seed, CTX)
    sim_open_door = vp.simulate(HOUSE, params, door_open_tl, seed, CTX)
    stats_closed = nf.night_stats(sim_closed["series"]["nursery"], NOW)
    stats_open_door = nf.night_stats(sim_open_door["series"]["nursery"], NOW)

    assert stats_closed["min"] > stats_open_door["min"]
    assert stats_closed["mean"] > stats_open_door["mean"]


def test_open_window_cools_more_overnight():
    # Buiten 14° 's nachts, kamer start 24°: het open raampje moet om 07:00
    # (en op z'n minst qua nacht-min) kouder uitkomen dan dicht.
    tl = vio.build_timeline(HOUSE, {"hourly": _rows()}, [], NOW, 24.0, CTX,
                            end_h=nf.hours_until_morning(NOW))
    params = vio.default_params(HOUSE)
    seed = {"nursery": 24.0}
    stats = {}
    for state in ("open", "dicht"):
        sim = vp.simulate(HOUSE, params, nf.scenario_timeline(tl, NOW, state), seed, CTX)
        stats[state] = nf.night_stats(sim["series"]["nursery"], NOW)
    assert stats["open"]["marks"][7] < stats["dicht"]["marks"][7]
    assert stats["open"]["min"] <= stats["dicht"]["min"]


def test_all_open_cools_at_least_as_much_as_window_only():
    # Alles open (incl. de trapdeur naar de koelere schacht) mag 's nachts niet
    # minder afkoelen dan alleen het raampje open (deur dicht).
    tl = vio.build_timeline(HOUSE, {"hourly": _rows()}, [], NOW, 24.0, CTX,
                            end_h=nf.hours_until_morning(NOW))
    params = vio.default_params(HOUSE)
    seed = {"nursery": 24.0, "stair": 24.0}
    sim_open = vp.simulate(HOUSE, params, nf.scenario_timeline(tl, NOW, "open"), seed, CTX)
    sim_all = vp.simulate(HOUSE, params, nf.all_open_timeline(tl, HOUSE, NOW), seed, CTX)
    stats_open = nf.night_stats(sim_open["series"]["nursery"], NOW)
    stats_all = nf.night_stats(sim_all["series"]["nursery"], NOW)
    assert stats_all["marks"][7] <= stats_open["marks"][7]


# ── Anker-correctie: sinds aug 2026 via het gedeelde ankerpad van de tweeling ─────────
# (vent_forecast.anchor_seed / latest_actual — de eigen anchor_now/anchor_mass_now zijn
# weg na de A/B op avond-oorsprongen: shift won op élke kamer, zie de module-docstring §1;
# de unit-dekking van het pad zelf staat in tests/test_vent_forecast.py.)

def test_ankerpad_is_gedeeld_met_de_tweeling(monkeypatch):
    """main() herankert via vent_forecast.anchor_seed met de nachteigen versheidsgrens
    (30 min) — vergeten door te geven = stilletjes de ruimere tweeling-default."""
    now = datetime.now(TZ)
    rows = _rows(now)
    wd = {"rooms": {"Nursery": {"history": [
        {"t": (now - timedelta(minutes=5)).isoformat(), "temp": 24.0}]}}}
    seen = {}
    orig_latest, orig_anchor = vfc.latest_actual, vfc.anchor_seed

    def spy_latest(actual, when, max_age_h=vfc.ANCHOR_MAX_AGE_H):
        seen["max_age_h"] = max_age_h
        return orig_latest(actual, when, max_age_h)

    def spy_anchor(*a, **kw):
        out = orig_anchor(*a, **kw)
        seen["anchored"] = out[2]
        return out

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(vio, "load_house", lambda: HOUSE)
    monkeypatch.setattr(vio, "fetch_weather", lambda lat, lon: {"hourly": rows, "current": {}})
    monkeypatch.setattr(vio, "load_openings_log", lambda: [])
    monkeypatch.setattr(vio, "load_learned", dict)
    monkeypatch.setattr(vio, "load_window_data", lambda: wd)
    monkeypatch.setattr(vfc, "latest_actual", spy_latest)
    monkeypatch.setattr(vfc, "anchor_seed", spy_anchor)
    nf.main()
    assert seen.get("max_age_h") == pytest.approx(nf.ANCHOR_MAX_STALENESS_MIN / 60.0)
    assert seen.get("anchored") == 1                     # de verse nursery-meting is verankerd


def test_main_applies_anchor_correction(monkeypatch, capsys):
    # Bewust de vaste NOW (een avond-oorsprong, zoals het project draait) en niet
    # de wandklok: de premisse van deze test is dat de verse meting van 30 °C
    # duidelijk afwijkt van wat de blinde 24u-warmup oplevert, en dat hangt aan
    # het tijdstip. Draait de suite midden op een synthetische zomerdag, dan zit
    # de blinde sim daar zélf al, valt de delta onder de 0.01-drempel en blijft
    # de regel uit — een rode suite zonder dat er iets stuk is (gezien 15 aug
    # 2026, 10:39). `main` neemt zijn klok al als argument; NOW gebruiken maakt
    # de test deterministisch. Zelfde patroon als test_ankering_bij_middernacht.
    now = NOW
    rows = _rows(now)
    history = [{"t": (now - timedelta(hours=h)).isoformat(), "temp": 24.0}
              for h in range(24, 0, -4)]
    # meest recente meting wijkt duidelijk af van wat de blinde 24u-warmup zou opleveren
    history.append({"t": (now - timedelta(minutes=5)).isoformat(), "temp": 30.0})
    wd = {"rooms": {"Nursery": {"history": history, "inside": 30.0}}}
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(vio, "load_house", lambda: HOUSE)
    monkeypatch.setattr(vio, "fetch_weather", lambda lat, lon: {"hourly": rows, "current": {}})
    monkeypatch.setattr(vio, "load_openings_log", lambda: [])
    monkeypatch.setattr(vio, "load_learned", dict)
    monkeypatch.setattr(vio, "load_window_data", lambda: wd)
    nf.main(now)
    out = capsys.readouterr().out
    assert "anker-correctie" in out


# ── Nachtstatistiek + advies + tog ───────────────────────────────────────────────────

def _series(now=NOW, start_t=23.0, end_t=19.0):
    """Lineair dalende kamertemp 19:00 → 08:00 (15-min raster)."""
    t0 = now.replace(hour=19, minute=0)
    steps = int(13 * 4) + 1
    return [(t0 + timedelta(minutes=15 * i),
             start_t + (end_t - start_t) * i / (steps - 1)) for i in range(steps)]


def test_night_stats_extraction():
    st = nf.night_stats(_series(), NOW)
    assert set(st["marks"]) == {23, 3, 7}
    assert st["marks"][23] > st["marks"][3] > st["marks"][7]   # daalt de nacht door
    assert st["min"] == pytest.approx(min(v for _, v in _series()
                                          if v is not None), abs=0.5)
    assert st["max"] <= 23.0
    assert nf.night_stats([], NOW) is None


def test_tog_table_boundaries():
    assert nf.tog_advice(24.0) == ("0.5 tog", "korte pyjama of alleen romper")
    assert nf.tog_advice(21.0) == ("1.0 tog", "korte pyjama")
    assert nf.tog_advice(18.0) == ("2.5 tog", "lange pyjama")
    assert nf.tog_advice(17.9) == ("2.5 tog", "warme pyjama + romper")
    assert nf.tog_advice(15.0) == ("3.5 tog", "warme pyjama + romper")


def test_season_gate():
    maart = datetime(2026, 3, 10, 18, 45, tzinfo=TZ)
    juni = datetime(2026, 6, 10, 18, 45, tzinfo=TZ)
    assert nf.should_send(juni, night_max=15.0)          # zomerseizoen: altijd
    assert not nf.should_send(maart, night_max=15.0)     # koude voorjaarsnacht: stil
    assert nf.should_send(maart, night_max=20.0)         # warme uitschieter: wél


def test_message_format():
    closed = {"min": 18.5, "max": 21.0, "mean": 19.5,
             "marks": {23: 20.5, 3: 19.5, 7: 18.8}}
    open_ = {"min": 17.0, "max": 20.5, "mean": 18.3,
             "marks": {23: 20.0, 3: 18.5, 7: 17.5}}
    all_open = {"min": 16.2, "max": 20.0, "mean": 17.6,
               "marks": {23: 19.5, 3: 17.8, 7: 16.5}}
    msg = nf.build_message(NOW, 22.5, 14.2, closed, open_, all_open, reported_open=True)
    assert "Kinderkamer-nacht" in msg
    assert "raampje dicht" in msg and "voorspelling gaat uit van dicht" in msg
    assert "23:00" in msg and "07:00" in msg
    assert "-1.3°" in msg                       # open zou 18.8 → 17.5 = -1.3° schelen
    assert "-2.3°" in msg                       # alles open zou 18.8 → 16.5 = -2.3° schelen
    assert "Alles open" in msg
    assert "2.5 tog" in msg                     # nachtgemiddeld (dicht) 19.5° → 18–21-band
    assert len(msg) < 4096


def test_message_format_matches_reported_stand():
    closed = {"min": 18.5, "max": 21.0, "mean": 19.5,
             "marks": {23: 20.5, 3: 19.5, 7: 18.8}}
    open_ = {"min": 17.0, "max": 20.5, "mean": 18.3,
             "marks": {23: 20.0, 3: 18.5, 7: 17.5}}
    all_open = {"min": 16.2, "max": 20.0, "mean": 17.6,
               "marks": {23: 19.5, 3: 17.8, 7: 16.5}}
    msg = nf.build_message(NOW, 22.5, 14.2, closed, open_, all_open, reported_open=False)
    assert "voorspelling gaat uit van dicht" not in msg


# ── main(): RunContext-ankers via de gemockte seams ──────────────────────────────────

def test_main_geeft_de_ctx_ankers_door(monkeypatch, capsys):
    """Herschreven _NEIGHBOR_TEMP-rebind-test: main() bouwt één RunContext (make_context)
    en geeft die aan élke build_timeline mee. Bewuste gedragswijziging t.o.v. het oude
    rebinden: make_context legt óók het zomerplafond (NEIGHBOR_SUMMER_CAP) op het
    buur-anker — hittegolf-rows horen dus op de kap uit te komen, niet op de rauwe
    schatting. Het bodem-anker (ground_temp) rijdt in dezelfde ctx mee."""
    now = datetime.now(TZ)
    rows = _rows(now, night_out=22.0, day_out=34.0)      # hittegolf: 3-daags gemiddelde > kap
    seen = []
    orig = vio.build_timeline

    def spy(*a, **kw):
        seen.append(a[5] if len(a) > 5 else kw.get("ctx"))
        return orig(*a, **kw)

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(vio, "load_house", lambda: HOUSE)
    monkeypatch.setattr(vio, "fetch_weather", lambda lat, lon: {"hourly": rows, "current": {}})
    monkeypatch.setattr(vio, "load_openings_log", lambda: [])
    monkeypatch.setattr(vio, "load_learned", dict)
    monkeypatch.setattr(vio, "load_window_data", dict)
    monkeypatch.setattr(vio, "build_timeline", spy)
    nf.main()
    assert seen and all(ctx is seen[0] for ctx in seen)  # één ctx voor warmup én forecast
    ctx = seen[0]
    raw = vp.neighbor_temp_estimate(rows, now)
    assert raw > vp.NEIGHBOR_SUMMER_CAP                  # de kap doet er in deze fixture echt toe
    assert ctx.neighbor_temp == pytest.approx(
        min(vp.NEIGHBOR_SUMMER_CAP, raw), abs=0.2)
    assert ctx.ground_temp == pytest.approx(vp.ground_temp_estimate(rows, now), abs=0.2)
    assert (ctx.lat, ctx.lon) == (52.09, 5.12)           # locatie uit het huismodel
    out = capsys.readouterr().out
    assert "Kinderkamer-nacht" in out or "stil" in out          # bericht of seizoenspoort


# ── Open-Meteo-modelbias op de driver ──────────────────────────────────────────

def test_main_geeft_de_geleerde_om_bias_door_aan_build_timeline(monkeypatch, capsys):
    """Spiegel van de ctx-ankers-test: de driver-correctie moet écht doorgegeven
    worden. Vergeten = de kinderkamer-voorspelling draait stil op de te warme nachtdriver, wat
    juist de reden was om 'm te bouwen — en niets zou dat zichtbaar maken."""
    rows = _rows(datetime.now(TZ))
    ob = {"night": 1.4, "day": 0.5, "n_night": 120, "n_day": 200}
    seen = []
    orig = vio.build_timeline

    def spy(*a, **kw):
        seen.append(kw.get("om_learned"))
        return orig(*a, **kw)

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(vio, "load_house", lambda: HOUSE)
    monkeypatch.setattr(vio, "fetch_weather", lambda lat, lon: {"hourly": rows, "current": {}})
    monkeypatch.setattr(vio, "load_openings_log", lambda: [])
    monkeypatch.setattr(vio, "load_learned", dict)
    monkeypatch.setattr(vio, "load_window_data", lambda: {"om_bias": ob})
    monkeypatch.setattr(vio, "build_timeline", spy)
    nf.main()
    assert seen, "build_timeline is niet aangeroepen"
    assert all(s == ob for s in seen), (
        f"niet elke timeline kreeg de correctie mee: {seen}")


# ── massaknoop mee-ijken (nu via de delta-shift van vent_forecast.anchor_seed) ─────────

def test_main_ijkt_de_massaknoop_mee(monkeypatch):
    """Wiring-test in het ctx-ankers-patroon: vergeten de massaknoop te ijken is
    stil en onzichtbaar — de voorspelling blijft draaien, alleen structureel te koud.

    Draait op de bevroren `NOW` (zoals alle andere tests hier), niet op de echte klok:
    `main()` nam vóór de `now`-parameter altijd `datetime.now(TZ)`, terwijl deze test de
    enige was die zijn fixtures (`_rows`/`wd`) ook rond de échte klok bouwde — twee losse
    `datetime.now(TZ)`-aanroepen die per definitie niet gegarandeerd samenvallen. Op de
    meeste momenten van de dag scheelt dat niets, maar bij toeval (bv. een dag-/seizoens-
    randgeval in `hours_until_morning`/`make_context`) kon het anker een heel andere
    aanname te pakken krijgen dan de fixture — vlokkig, en niet reproduceerbaar. Met een
    geïnjecteerde, bevroren klok (zelfde `NOW` als de rest van dit bestand) draait de test
    exact hetzelfde af ongeacht wanneer de suite draait."""
    rows = _rows(NOW)
    gezien = []
    orig = vp.simulate

    def spy(house, params, timeline, seed, ctx, **kw):
        gezien.append(kw.get("tm_seed"))
        return orig(house, params, timeline, seed, ctx, **kw)

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(vio, "load_house", lambda: HOUSE)
    monkeypatch.setattr(vio, "fetch_weather", lambda lat, lon: {"hourly": rows, "current": {}})
    monkeypatch.setattr(vio, "load_openings_log", lambda: [])
    monkeypatch.setattr(vio, "load_learned", dict)
    # Echte tado-historie zodat collect_actual samples oplevert: een kamer die de hele
    # dag stabiel 23° was, mét een verse meting (≤30 min — sinds de anker-unificatie
    # herankeren lucht + massa sámen op de verse meting, of allebei niet).
    t0 = NOW
    wd = {"rooms": {"Nursery": {"history": [
        {"t": (t0 - timedelta(hours=h)).isoformat(), "temp": 23.0}
        for h in range(int(nf.WARMUP_H), 0, -1)]
        + [{"t": (t0 - timedelta(minutes=5)).isoformat(), "temp": 23.0}]}}}
    monkeypatch.setattr(vio, "load_window_data", lambda: wd)
    monkeypatch.setattr(vp, "simulate", spy)
    nf.main(now=NOW)
    fcst = [s for s in gezien[1:] if s]
    assert fcst, "forecast-sim kreeg geen massaknoop mee"
    # De delta-shift-anker garandeert Tm_new - Ta_new == Tm_old - Ta_old: de massa
    # schuift met exact dezelfde delta mee als de lucht, dus hij landt niet ván nature
    # bóvenop de meting. Voor deze fixture (minimaal huis, priors i.p.v. geleerde
    # params, volle zomer-zonlast) is dat een echt, deterministisch lucht/massa-gat
    # van ~1,8 °C — geen ruis. Zónder anker blijft de massa op zijn ongeijkte,
    # weggedrifte warmup-waarde staan (hier ~34,8° tegen een meting van 23°, dus
    # >10° fout) — dát is de regressie waar deze wiring-test tegen bewaakt. abs=3.0
    # zit ruim boven het echte geankerde gat en ruim onder de ongeankerde fout.
    assert fcst[0].get("nursery") == pytest.approx(23.0, abs=3.0), (
        f"massaknoop niet op de metingen geijkt (kreeg {fcst[0].get('nursery')}) — "
        "de warmup-drift lekt de forecast in")


# ── voorspellingslog (data/night_forecast_log) — het verificatiespoor ──────────────────

def _log_stats():
    s = {"min": 19.5, "max": 22.5, "mean": 21.0, "marks": {23: 22.0, 3: 20.5, 7: 19.8}}
    return {"dicht": s, "open": {**s, "marks": {7: 19.0}}, "all_open": {**s, "marks": {7: 18.4}}}


def test_voorspellingslog_is_idempotent_per_datum(tmp_path, monkeypatch):
    """Eén rij per lokale datum: de fallback-cron die dezelfde avond nóg eens dispatcht
    mag het log niet stapelen (zelfde afweging als de guard-job, maar dan in de data)."""
    monkeypatch.setattr(nf, "NIGHT_LOG_DIR", str(tmp_path))
    series = [(NOW + timedelta(minutes=15 * i), 21.0 - i * 0.02) for i in range(8)]
    assert nf.append_night_log(NOW, _log_stats(), series, "1.0 tog", True) is True
    assert nf.append_night_log(NOW + timedelta(hours=1), _log_stats(), series,
                               "1.0 tog", True) is False
    import json as _json
    shard = _json.load(open(tmp_path / f"{NOW:%Y-%m}.json"))
    assert len(shard["forecasts"]) == 1
    row = shard["forecasts"][0]
    assert row["date"] == NOW.date().isoformat()
    assert row["scenarios"]["dicht"]["marks"]["7"] == 19.8


def test_voorspellingslog_serie_alleen_vanaf_nu_en_compact(tmp_path, monkeypatch):
    """De dicht-serie gaat compact ([epoch, °C×10]) het log in en alleen vanaf nu —
    het verleden staat al als meting in de twin2-shards."""
    monkeypatch.setattr(nf, "NIGHT_LOG_DIR", str(tmp_path))
    series = ([(NOW - timedelta(hours=2), 23.0)]
              + [(NOW + timedelta(minutes=15 * i), 21.5) for i in range(4)])
    nf.append_night_log(NOW, _log_stats(), series, "2.5 tog", False)
    import json as _json
    row = _json.load(open(tmp_path / f"{NOW:%Y-%m}.json"))["forecasts"][0]
    assert len(row["series_dicht"]) == 4                      # het verleden-punt valt af
    assert row["series_dicht"][0] == [int(NOW.timestamp()), 215]
    assert row["sent"] is False
    # Privacy-scrub: geen raamstand-afgeleide in het gecommitte log.
    assert "reported_open" not in row


def test_workflow_checkout_pint_branch_tip(assert_checkout_pinned):
    """De workflow commit sinds aug 2026 het voorspellingslog — dan geldt dezelfde
    branch-tip-regel als voor elke committerende dispatch-workflow."""
    assert_checkout_pinned("night-forecast.yml")


# ── onzekerheidsband in het bericht ────────────────────────────────────────────────────

def _unc():
    return {"bands": {"nursery": {
        "1": {"p10": -0.3, "p90": 0.1, "trusted": True},
        "12": {"p10": -0.9, "p90": 0.3, "trusted": True},
        "13": {"p10": -2.0, "p90": 2.0, "trusted": False},   # untrusted → nooit gebruikt
    }}}


def test_band_for_pakt_de_dichtstbijzijnde_trusted_cel():
    """~12u vooruit → de h12-cel; band op een voorspelling = [pred − p90, pred − p10].
    De untrusted h13-cel mag nóóit winnen, ook al ligt hij dichterbij."""
    lo, hi = vio.band_for(20.0, 12.2, _unc(), room="nursery")
    assert (lo, hi) == (pytest.approx(19.7), pytest.approx(20.9))
    lo, hi = vio.band_for(20.0, 13.4, _unc(), room="nursery")      # dichter bij 13, maar die is untrusted
    assert (lo, hi) == (pytest.approx(19.7), pytest.approx(20.9))


def test_band_for_zwijgt_zonder_band_of_voorspelling():
    assert vio.band_for(20.0, 12.0, None, room="nursery") is None
    assert vio.band_for(None, 12.0, _unc(), room="nursery") is None
    assert vio.band_for(20.0, 12.0, {"bands": {"nursery": {}}}, room="nursery") is None


def test_bericht_noemt_de_marge_alleen_met_band():
    stats = {"min": 19.5, "max": 22.5, "mean": 21.0, "marks": {23: 22.0, 3: 20.5, 7: 19.8}}
    met = nf.build_message(NOW, 24.0, 15.0, stats, stats, stats, False,
                           band_07=(19.3, 20.6))
    assert "Typisch 19.3–20.6° om 07:00" in met
    zonder = nf.build_message(NOW, 24.0, 15.0, stats, stats, stats, False)
    assert "Typisch" not in zonder
