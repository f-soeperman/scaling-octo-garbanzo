"""Regressie-vangnet voor `vent_io.py` — de data-loodgieterij van de herbouwde
ventilatie-tweeling (Project 13).

Geport uit tests/test_airflow_model.py (openingen-log, collect_*, learned/params-
migratie, om_learned_from, model_version, build_timeline — nu met een expliciete
RunContext i.p.v. module-globals) en uit tests/test_airflow2_model.py (de maand-
shards, de enige overlevenden van dat bestand). Plus één nieuwe test: make_context.

Bewust geen netwerk: fetch_weather/fetch_weather_archive/refine_outside_now en de
Gist-lezers blijven ongetest (netwerk-I/O), zoals in de oude suites.
"""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

import shared_const
import vent_io as vio
import vent_physics as vp

TZ = vio.TZ
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Vaste run-context voor de timeline-tests: locatie Utrecht, de module-default-ankers.
CTX = vp.RunContext(lat=52.09, lon=5.12,
                    neighbor_temp=vp.NEIGHBOR_TEMP, ground_temp=vp.GROUND_TEMP)


# ── 1. openings_at + _open_frac-semantiek ────────────────────────────────────────────

def test_openings_at_timeline():
    t0 = datetime(2026, 6, 1, 8, 0, tzinfo=TZ)
    log = [
        {"t": t0.isoformat(), "states": {"w": "open"}},
        {"t": (t0 + timedelta(hours=4)).isoformat(), "states": {"w": "closed"}},
    ]
    # Vóór de eerste log: leeg.
    assert vio.openings_at(log, t0 - timedelta(hours=1)) == {}
    # Tussen log 1 en 2: eerste snapshot geldt.
    assert vio.openings_at(log, t0 + timedelta(hours=2))["w"] == "open"
    # Na log 2: tweede snapshot geldt.
    assert vio.openings_at(log, t0 + timedelta(hours=6))["w"] == "closed"


def test_openings_at_accumulates_incremental():
    # Kleine, losse meldingen: een element houdt zijn laatst-gezette waarde ook als een
    # latere snapshot 'm niet herhaalt (zo kun je één raam wijzigen zonder de rest op te geven).
    t0 = datetime(2026, 6, 1, 8, 0, tzinfo=TZ)
    log = [
        {"t": t0.isoformat(), "states": {"a": "open", "b": "dicht"}},
        {"t": (t0 + timedelta(hours=1)).isoformat(), "states": {"b": "tilt"}},   # alleen b
    ]
    st = vio.openings_at(log, t0 + timedelta(hours=2))
    assert st["a"] == "open"      # behouden uit de eerdere snapshot
    assert st["b"] == "tilt"      # bijgewerkt door de latere


def test_open_frac_mapping():
    # _open_frac/_default_frac leven nu in vent_physics (pure fysica-invoer).
    elem = {"tilt_frac": 0.2}
    assert vp._open_frac("open", elem) == 1.0
    assert vp._open_frac("dicht", elem) == 0.0
    assert vp._open_frac("tilt", elem) == 0.2
    assert vp._open_frac(0.5, elem) == 0.5
    assert vp._open_frac("tilt", {}) == 0.15          # zonder tilt_frac → default kier
    assert vp._open_frac("onzin", elem) == 0.0        # onbekend → veilig dicht


def test_default_frac_basistoestanden():
    # Basistoestand vóór enige rapportage: ramen dicht, binnendeuren open, roosters open.
    assert vp._default_frac({}, "window") == 0.0
    assert vp._default_frac({}, "vent") == 1.0
    assert vp._default_frac({}, "door") == 1.0
    assert vp._default_frac({"default_state": "dicht"}, "door") == 0.0
    assert vp._default_frac({"default_state": "tilt", "tilt_frac": 0.3}, "vent") == 0.3


# ── 2. AC-sleutel (ac_room) in de openingen-log ──────────────────────────────────────

def test_ac_room_at_forward_fill():
    # De airco-kamer wordt voorwaarts geaccumuleerd uit de log (net als openings_at): vóór de
    # eerste melding geen airco, daarna de laatst-gezette kamer; "geen"/"" zet 'm weer uit.
    t0 = datetime(2026, 6, 1, 8, 0, tzinfo=TZ)
    log = [
        {"t": t0.isoformat(), "states": {"w": "open", vio.AC_STATE_KEY: "office"}},
        {"t": (t0 + timedelta(hours=3)).isoformat(), "states": {vio.AC_STATE_KEY: "living"}},
        {"t": (t0 + timedelta(hours=6)).isoformat(), "states": {vio.AC_STATE_KEY: "geen"}},
    ]
    chg = vio.ac_changes(log)
    assert vio.ac_room_at(chg, t0 - timedelta(hours=1)) is None   # vóór de eerste melding
    assert vio.ac_room_at(chg, t0 + timedelta(hours=1)) == "office"
    assert vio.ac_room_at(chg, t0 + timedelta(hours=4)) == "living"
    assert vio.ac_room_at(chg, t0 + timedelta(hours=7)) is None   # "geen" → uit
    # Een log zonder enige ac_room-sleutel levert geen wijzigingen → altijd None.
    assert vio.ac_changes([{"t": t0.isoformat(), "states": {"w": "open"}}]) == []


def test_norm_ac_room():
    assert vio._norm_ac_room("office") == "office"
    assert vio._norm_ac_room("  Office ") == "office"   # genormaliseerd (trim + lower)
    assert vio._norm_ac_room("") is None
    assert vio._norm_ac_room("geen") is None
    assert vio._norm_ac_room(None) is None


# ── 3. Pauze-sleutel (paused) in de openingen-log ────────────────────────────────────

def test_norm_paused():
    assert vio._norm_paused(True) is True
    assert vio._norm_paused(False) is False
    assert vio._norm_paused("true") is True
    assert vio._norm_paused("gepauzeerd") is True
    assert vio._norm_paused("") is False
    assert vio._norm_paused("uit") is False


def test_pause_changes_and_paused_at():
    t0 = datetime(2026, 6, 1, 8, 0, tzinfo=TZ)
    log = [
        {"t": t0.isoformat(), "states": {"w": "open", vio.PAUSE_STATE_KEY: True}},
        {"t": (t0 + timedelta(hours=2)).isoformat(), "states": {vio.PAUSE_STATE_KEY: False}},
        {"t": (t0 + timedelta(hours=5)).isoformat(), "states": {vio.PAUSE_STATE_KEY: True}},
    ]
    chg = vio.pause_changes(log)
    assert vio.paused_at(chg, t0 - timedelta(hours=1)) is False   # vóór eerste melding
    assert vio.paused_at(chg, t0 + timedelta(hours=1)) is True
    assert vio.paused_at(chg, t0 + timedelta(hours=3)) is False
    assert vio.paused_at(chg, t0 + timedelta(hours=6)) is True
    # Log zonder paused-sleutel → geen wijzigingen.
    assert vio.pause_changes([{"t": t0.isoformat(), "states": {"w": "open"}}]) == []


def test_paused_intervals_open_ended_when_still_active():
    t0 = datetime(2026, 6, 1, 8, 0, tzinfo=TZ)
    now = t0 + timedelta(hours=6)
    chg = [(t0, True), (t0 + timedelta(hours=2), False), (t0 + timedelta(hours=5), True)]
    intervals = vio.paused_intervals(chg, now)
    assert intervals == [(t0, t0 + timedelta(hours=2)), (t0 + timedelta(hours=5), now)]
    # Nooit gepauzeerd → geen intervallen.
    assert vio.paused_intervals([], now) == []
    # Volledig afgesloten (geen actieve pauze op `now`) → laatste interval sluit netjes af,
    # geen extra open-eindig interval.
    chg2 = [(t0, True), (t0 + timedelta(hours=2), False)]
    assert vio.paused_intervals(chg2, now) == [(t0, t0 + timedelta(hours=2))]


# ── 4. collect_actual / collect_heating_on / heating_now ─────────────────────────────

def _sensor_house():
    return {
        "location": {"lat": 52.09, "lon": 5.12},
        "rooms": {"nursery": {"from_window_data": "Nursery", "volume_m3": 30},
                  "bath": {"from_window_data": "Shower", "volume_m3": 18},
                  "stair": {"volume_m3": 26}},                      # sensorloos
        "junctions": {}, "windows": {}, "vents": {}, "doors": {},
    }


def test_collect_actual_leest_en_sorteert_history():
    now = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
    since = now - timedelta(hours=4)
    ts = [now - timedelta(hours=h) for h in range(4, -1, -1)]
    wd = {"rooms": {
        # Bewust ongesorteerd + een None-temp + een sample vóór het venster.
        "Nursery": {"history": [
            {"t": ts[2].isoformat(), "temp": 21.0},
            {"t": ts[0].isoformat(), "temp": 20.0},
            {"t": ts[1].isoformat(), "temp": None},
            {"t": (since - timedelta(hours=2)).isoformat(), "temp": 19.0},
        ]},
        "Elders": {"history": [{"t": ts[0].isoformat(), "temp": 25.0}]},   # geen kamer-mapping
    }}
    actual = vio.collect_actual(_sensor_house(), wd, since)
    assert list(actual) == ["nursery"]                     # bath ontbreekt in wd, stair sensorloos
    assert actual["nursery"] == [(ts[0], 20.0), (ts[2], 21.0)]   # gesorteerd, None + te oud weg


def test_collect_heating_on_en_heating_now():
    now = datetime(2026, 1, 15, 22, 0, tzinfo=TZ)
    since = now - timedelta(hours=5)
    ts = [now - timedelta(hours=h) for h in range(4, -1, -1)]   # 5 samples, elk uur
    # Nursery stookt op de laatste 2 samples; de badkamer nooit.
    wd = {"rooms": {
        "Nursery": {"heating": True, "history": [
            {"t": ts[0].isoformat(), "temp": 18.0},
            {"t": ts[1].isoformat(), "temp": 18.5},
            {"t": ts[2].isoformat(), "temp": 19.0},
            {"t": ts[3].isoformat(), "temp": 20.5, "heat": 1},
            {"t": ts[4].isoformat(), "temp": 21.5, "heat": 1},
        ]},
        "Shower": {"heating": False, "history": [
            {"t": ts[i].isoformat(), "temp": 22.0} for i in range(5)]},
    }}
    house = _sensor_house()
    heat_on = vio.collect_heating_on(house, wd, since)
    assert heat_on["nursery"] == {ts[3], ts[4]}
    assert "bath" not in heat_on                       # badkamer stookte niet
    assert vio.heating_now(house, wd) == {"nursery": True, "bath": False}


# ── 5. load_learned / default_params / merged_params + PHYSICS_REV-poort ────────────

def test_load_learned_graceful(tmp_path, monkeypatch):
    # Lokale-pad-modus (geen ARTEFACT_GIST_ID) — het bootstrap-/test-pad.
    monkeypatch.delenv("ARTEFACT_GIST_ID", raising=False)
    # Ontbrekend of onleesbaar bestand → lege staat (verse deploy), nooit een crash.
    monkeypatch.setattr(vio, "LEARNED_FILE", str(tmp_path / "nope.json"))
    assert vio.load_learned() == {}
    p = tmp_path / "learned.json"
    p.write_text("{dit is geen json", encoding="utf-8")
    monkeypatch.setattr(vio, "LEARNED_FILE", str(p))
    assert vio.load_learned() == {}
    p.write_text(json.dumps({"params": {"cp_shelter": 0.4}}), encoding="utf-8")
    assert vio.load_learned()["params"]["cp_shelter"] == 0.4


def test_load_learned_leest_uit_de_artefact_gist(tmp_path, monkeypatch):
    """Privatisering (aug 2026): met ARTEFACT_GIST_ID gezet leest load_learned uit
    dezelfde privé artefact-gist als data.json/mowing_data.json — dit is de
    read-back die de online kalibratie van run naar run laat doorlopen."""
    monkeypatch.setenv("ARTEFACT_GIST_ID", "abc123")
    monkeypatch.setenv("GIST_TOKEN", "tok")
    monkeypatch.setattr(vio.artefact_io.gist_io, "read_json",
                        lambda gid, fn, token=None, default=None, label=None:
                            {"params": {"cp_shelter": 0.9}} if fn == "vent_learned.json" else default)
    assert vio.load_learned()["params"]["cp_shelter"] == 0.9


def test_physics_rev_migration_resets_everything():
    # Geleerde staat van een oudere fysica-revisie → ÁLLES terug naar de priors, globalen
    # én kamer-params (de oude waren compensaties voor precies de fysica die veranderde).
    # Rev 7 = de kruipruimte-verankering + de per-kamer parametervloer (aug 2026); de
    # geleerde params absorbeerden de te koude kruipruimte, dus die compensaties mogen de
    # nieuwe fysica niet in.
    assert vio.PHYSICS_REV == 7
    house = {"rooms": {"a": {}}}
    old = {"params": {"cp_shelter": 0.1, "vent_eff": 0.43, "a": {"c_air": 1.2}},
           "physics_rev": vio.PHYSICS_REV - 1}
    assert vio.physics_rev_migration_needed(old) is True
    p = vio.merged_params(house, old)
    assert p["cp_shelter"] == vp.PRIORS["cp_shelter"]
    assert p["vent_eff"] == vp.PRIORS["vent_eff"]
    assert p["a"]["c_air"] == vp.PRIORS["c_air"]       # kamer-params óók gereset
    cur = {"params": {"cp_shelter": 0.9, "a": {"c_air": 1.2}}, "physics_rev": vio.PHYSICS_REV}
    assert vio.physics_rev_migration_needed(cur) is False
    assert vio.merged_params(house, cur)["cp_shelter"] == 0.9
    assert vio.physics_rev_migration_needed({}) is False   # lege staat: niets te migreren


def test_merged_params_fills_new_rooms_and_keys():
    house = {"rooms": {"a": {}, "b": {}}}
    learned = {"params": {"cp_shelter": 0.42, "a": {"c_air": 123.0}},
               "physics_rev": vio.PHYSICS_REV}
    p = vio.merged_params(house, learned)
    assert p["cp_shelter"] == 0.42                     # geleerd blijft staan
    assert p["a"]["c_air"] == 123.0
    for k in vp.PER_ROOM_PARAMS:                        # ontbrekende keys → prior
        assert k in p["a"] and k in p["b"]
    assert p["b"]["c_air"] == vp.PRIORS["c_air"]        # nieuwe kamer → priors
    for g in vp.GLOBAL_PARAMS:
        assert g in p


def test_merged_params_strips_cd_fossil():
    house = {"rooms": {"a": {}}}
    learned = {"params": {"cd": 0.30, "cp_shelter": 0.4, "a": {"c_air": 1.2}},
               "physics_rev": vio.PHYSICS_REV}
    p = vio.merged_params(house, learned)
    assert "cd" not in p                               # fossiel gestript
    assert p["cp_shelter"] == 0.4                      # geleerde waarden onaangeroerd


def test_default_params_structure():
    house = {"rooms": {"a": {}, "b": {}}}
    p = vio.default_params(house)
    assert set(vp.GLOBAL_PARAMS) <= set(p)
    for rid in ("a", "b"):
        assert set(p[rid]) == set(vp.PER_ROOM_PARAMS)
        for k in vp.PER_ROOM_PARAMS:
            assert p[rid][k] == vp.PRIORS[k]
    assert "cd" not in p                               # cd is geen leerbare param meer


# ── 6. om_learned_from ───────────────────────────────────────────────────────────────

def test_om_learned_from_leeg_geeft_none():
    # Nog niets geleerd → None → build_timeline gedraagt zich als vóór de correctie.
    assert vio.om_learned_from({}) is None
    assert vio.om_learned_from({"om_bias": {}}) is None
    assert vio.om_learned_from({"om_bias": {"night": 0.0, "day": 0.0,
                                            "n_night": 3, "n_day": 5}}) is None


def test_om_learned_from_geeft_het_blok_door():
    ob = {"night": 1.4, "day": 0.5, "n_night": 120, "n_day": 200}
    assert vio.om_learned_from({"om_bias": ob}) == ob


# ── 7. model_version-stempel (RMSE ↔ codeversie) ─────────────────────────────────────

def test_model_version_prefers_github_sha(monkeypatch):
    monkeypatch.setattr(vio, "_MODEL_VERSION", None)
    monkeypatch.setenv("GITHUB_SHA", "abcdef1234567890")
    assert vio.model_version() == "abcdef1"   # short-SHA (7 tekens)


def test_model_version_always_nonempty(monkeypatch):
    monkeypatch.setattr(vio, "_MODEL_VERSION", None)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    v = vio.model_version()
    assert isinstance(v, str) and v   # git short-SHA of 'unknown', nooit leeg


# ── 8. build_timeline (nu met expliciete RunContext) ─────────────────────────────────

def test_build_timeline_averages_solar_over_step():
    # build_timeline middelt de instraling over elke 15-min stap (SOLAR_SUBSTEPS sub-samples op
    # de midden-regel) i.p.v. één punt-sample aan de stap-rand → dempt de avond-aliasing van de
    # snel-draaiende lage NW-zon. Verifieer dat de geraster-irr exact dat sub-sample-gemiddelde is.
    house = {
        "rooms": {"r": {}},
        "windows": {"w": {"room": "r", "facade_azimuth_deg": 309.0,
                          "glass_m2": 1.0, "tilt_deg": 90.0}},
    }
    base = datetime(2026, 6, 14, 17, 0, tzinfo=timezone.utc)
    rows = [{"dt": base + timedelta(hours=h), "T_out": 16.0, "direct": 600.0, "diffuse": 100.0,
             "wind_speed": 3.0, "wind_dir": 309.0, "gust": 5.0, "precip": 0.0, "rh": 60.0}
            for h in range(0, 5)]
    now = base + timedelta(hours=2)        # 19:00 UTC — lage avondzon in het NW
    grid = vio.build_timeline(house, {"hourly": rows}, [], now, 1.0, CTX)

    step = next(s for s in grid if s["t"] == now)
    expected = 0.0
    for j in range(vp.SOLAR_SUBSTEPS):
        ts = now + timedelta(hours=0.25 * (j + 0.5) / vp.SOLAR_SUBSTEPS)
        s_az, s_el = vp.sun_position(CTX.lat, CTX.lon, ts.astimezone(timezone.utc))
        expected += 0.7 * vp.facade_irradiance(309.0, s_az, s_el, 600.0, 100.0, 90.0, False, 0.0)
    expected /= vp.SOLAR_SUBSTEPS
    assert step["irr"]["r"] == pytest.approx(expected, abs=1e-9)
    # De rij bewaart de representatieve zon op het stap-midden (voor het dashboard).
    mid_az, mid_el = vp.sun_position(CTX.lat, CTX.lon,
                                     (now + timedelta(hours=0.125)).astimezone(timezone.utc))
    assert step["sun_el"] == pytest.approx(mid_el, abs=1e-9)
    assert step["sun_az"] == pytest.approx(mid_az, abs=1e-9)


def test_build_timeline_end_h_default_unchanged():
    # Default end_h=2.0 → het raster eindigt exact op now+2u; een expliciete end_h rekt de
    # vooruitblik op zonder iets anders te raken (night_forecast-gebruik).
    house = {
        "rooms": {"r": {}},
        "windows": {"w1": {"room": "r", "facade_azimuth_deg": 309.0, "glass_m2": 1.0,
                           "tilt_deg": 90.0}},
    }
    base = datetime(2026, 6, 14, 10, 0, tzinfo=timezone.utc)
    now = base + timedelta(hours=2)
    rows = [{"dt": base + timedelta(hours=h), "T_out": 16.0, "direct": 600.0,
             "diffuse": 100.0, "wind_speed": 3.0, "wind_dir": 309.0, "gust": 5.0,
             "precip": 0.0, "rh": 60.0} for h in range(0, 5)]
    weather = {"hourly": rows}
    grid_default = vio.build_timeline(house, weather, [], now, 1.0, CTX)
    assert grid_default[-1]["t"] == now + timedelta(hours=2)
    grid_long = vio.build_timeline(house, weather, [], now, 1.0, CTX, end_h=13.0)
    assert grid_long[-1]["t"] == now + timedelta(hours=13)
    # Het overlappende deel is identiek (zelfde drivers, zelfde middeling).
    for s_def, s_long in zip(grid_default, grid_long):
        assert s_def["t"] == s_long["t"]
        assert s_def["irr"]["r"] == pytest.approx(s_long["irr"]["r"], abs=1e-12)


def test_wu_solar_scale_factor_decays_to_one():
    # Op nu (age 0) → vol k; buiten het venster → 1.0 (pure OM). De uitdoving is SYMMETRISCH:
    # `k` is een momentopname van de WU/OM-zonverhouding en veroudert vooruit net zo hard als
    # achteruit — met een 12-uurs voorspelling zou de bewolkingsverhouding van nú anders de hele
    # nacht blijven gelden.
    D = vio.WU_SOLAR_SCALE_DECAY_H
    assert vio.wu_solar_scale_factor(1.4, 0.0) == pytest.approx(1.4)
    assert vio.wu_solar_scale_factor(1.4, D) == pytest.approx(1.0)
    assert vio.wu_solar_scale_factor(1.4, 2 * D) == pytest.approx(1.0)
    assert vio.wu_solar_scale_factor(1.4, -D) == pytest.approx(1.0)             # ver vooruit
    assert vio.wu_solar_scale_factor(1.4, -2 * D) == pytest.approx(1.0)
    for age in (D / 2, -D / 2):
        assert 1.0 < vio.wu_solar_scale_factor(1.4, age) < 1.4
    # Spiegelsymmetrie expliciet: even ver terug en vooruit weegt gelijk.
    assert (vio.wu_solar_scale_factor(1.4, 1.0)
            == pytest.approx(vio.wu_solar_scale_factor(1.4, -1.0)))
    assert vio.wu_solar_scale_factor(None, 0.0) == 1.0                          # WU ontbrak → no-op


def test_build_timeline_applies_wu_solar_scale():
    # Met een WU/OM-schaal wordt de instraling op de nu-stap ~k× de ongeschaalde waarde (de OM
    # direct+diffuus schalen mee, split behouden). Zonder schaal identiek aan de basis.
    house = {"rooms": {"r": {}},
             "windows": {"w": {"room": "r", "facade_azimuth_deg": 309.0,
                               "glass_m2": 1.0, "tilt_deg": 90.0}}}
    base = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)
    rows = [{"dt": base + timedelta(hours=h), "T_out": 20.0, "direct": 600.0, "diffuse": 100.0,
             "wind_speed": 3.0, "wind_dir": 309.0, "gust": 5.0, "precip": 0.0, "rh": 50.0}
            for h in range(0, 4)]
    now = base + timedelta(hours=1)
    plain = vio.build_timeline(house, {"hourly": rows}, [], now, 1.0, CTX)
    scaled = vio.build_timeline(house, {"hourly": rows}, [], now, 1.0, CTX, wu_solar_scale=1.5)
    sp = next(s for s in plain if s["t"] == now)["irr"]["r"]
    ss = next(s for s in scaled if s["t"] == now)["irr"]["r"]
    assert sp > 0.0
    assert ss == pytest.approx(1.5 * sp, rel=1e-9)       # nu-stap: vol k


# ── 8b. Open-Meteo-modelbias op de driver (om_learned) ───────────────────────────────

def _om_rows(base, t_out=25.0, rh=60.0, hours=6):
    return [{"dt": base + timedelta(hours=h), "T_out": t_out, "rh": rh,
             "direct": 0.0, "diffuse": 0.0, "wind_speed": 3.0, "wind_dir": 200.0,
             "gust": 5.0, "precip": 0.0} for h in range(hours)]


def test_build_timeline_zonder_om_learned_is_ongewijzigd():
    # Terugvalgarantie: geen geleerde bias → bit-voor-bit de oude driver.
    house = {"rooms": {"r": {}}, "windows": {}}
    base = datetime(2026, 7, 29, 0, 0, tzinfo=TZ)
    rows = _om_rows(base)
    now = base + timedelta(hours=2)
    for learned in (None, {}):
        grid = vio.build_timeline(house, {"hourly": rows}, [], now, 1.0, CTX,
                                  om_learned=learned)
        step = next(s for s in grid if s["t"] == now)
        assert step["T_out"] == pytest.approx(25.0)
        assert step["weather"]["rh"] == pytest.approx(60.0)


def test_build_timeline_trekt_de_nachtbias_van_de_driver_af():
    # De kern: 's nachts leest Open-Meteo te warm, dus de driver moet omlaag.
    house = {"rooms": {"r": {}}, "windows": {}}
    base = datetime(2026, 7, 29, 0, 0, tzinfo=TZ)
    now = base + timedelta(hours=2)                       # 02:00 → volle nachtemmer
    grid = vio.build_timeline(house, {"hourly": _om_rows(base)}, [], now, 1.0, CTX,
                              om_learned={"night": 1.4, "day": 0.5})
    step = next(s for s in grid if s["t"] == now)
    assert step["T_out"] == pytest.approx(25.0 - 1.4)


def test_build_timeline_laat_de_vochtigheid_meeschuiven():
    # Bij een temperatuurcorrectie blijft de dampinhoud behouden → koeler = hogere RH.
    # Alleen de temp corrigeren zou de tweeling stiekem uitdrogen.
    house = {"rooms": {"r": {}}, "windows": {}}
    base = datetime(2026, 7, 29, 0, 0, tzinfo=TZ)
    now = base + timedelta(hours=2)
    grid = vio.build_timeline(house, {"hourly": _om_rows(base)}, [], now, 1.0, CTX,
                              om_learned={"night": 1.4, "day": 0.5})
    step = next(s for s in grid if s["t"] == now)
    assert step["weather"]["rh"] > 60.0
    assert step["weather"]["rh"] == pytest.approx(
        vio.convert_rh(60.0, 25.0, 25.0 - 1.4), abs=1e-6)


def test_build_timeline_gebruikt_de_emmer_van_de_stap():
    # Niet de emmer van "nu", maar die van elke stap zelf bepaalt de correctie.
    house = {"rooms": {"r": {}}, "windows": {}}
    base = datetime(2026, 7, 29, 12, 0, tzinfo=TZ)      # middag
    rows = _om_rows(base, hours=16)
    now = base + timedelta(hours=14)                     # 02:00 → nacht
    grid = vio.build_timeline(house, {"hourly": rows}, [], now, 14.0, CTX,
                              om_learned={"night": 1.4, "day": 0.4})
    dag = next(s for s in grid if s["t"] == base + timedelta(hours=1))
    nacht = next(s for s in grid if s["t"] == now)
    assert dag["T_out"] == pytest.approx(25.0 - 0.4)
    assert nacht["T_out"] == pytest.approx(25.0 - 1.4)


# ── 8c. _interp_hourly / _timedelta_h ────────────────────────────────────────────────

def test_interp_hourly_lineair_en_klemt_aan_de_randen():
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=TZ)
    rows = [{"dt": t0, "T_out": 10.0}, {"dt": t0 + timedelta(hours=1), "T_out": 12.0}]
    assert vio._interp_hourly(rows, t0 + timedelta(minutes=30), "T_out") == pytest.approx(11.0)
    assert vio._interp_hourly(rows, t0 - timedelta(hours=1), "T_out") == 10.0   # klem links
    assert vio._interp_hourly(rows, t0 + timedelta(hours=5), "T_out") == 12.0   # klem rechts
    assert vio._interp_hourly(rows, t0 + timedelta(minutes=30), "rh") == 0.0    # key ontbreekt → 0
    assert vio._timedelta_h(1.5) == timedelta(hours=1, minutes=30)


# ── 9. make_context (nieuw: de RunContext-bouw) ──────────────────────────────────────

def test_make_context_bouwt_ankers_en_locatie():
    house = {"location": {"lat": 51.5, "lon": 4.5}, "rooms": {}}
    now = datetime(2026, 7, 15, 12, 0, tzinfo=TZ)
    # Hittegolf-venster: 3-daags gemiddelde 30° → het buur-anker wordt op het zomerplafond gekapt.
    rows = [{"dt": now - timedelta(hours=h), "T_out": 30.0} for h in range(0, 72)]
    ctx = vio.make_context(house, {"hourly": rows}, now)
    assert ctx.lat == 51.5 and ctx.lon == 4.5           # locatie uit het huismodel
    assert ctx.neighbor_temp == pytest.approx(vp.NEIGHBOR_SUMMER_CAP)
    assert ctx.ground_temp == pytest.approx(vp.ground_temp_estimate(rows, now))
    # Koeler venster → het anker volgt de schatting zelf (geen kap).
    rows_koel = [{"dt": now - timedelta(hours=h), "T_out": 20.0} for h in range(0, 72)]
    ctx2 = vio.make_context(house, {"hourly": rows_koel}, now)
    assert ctx2.neighbor_temp == pytest.approx(
        vp.neighbor_temp_estimate(rows_koel, now))
    assert ctx2.neighbor_temp < vp.NEIGHBOR_SUMMER_CAP
    # Zonder locatie in het huismodel → de gedeelde Utrecht-Oost-constanten; zonder
    # weer-historie → de module-default-ankers (NEIGHBOR_TEMP onder de kap, GROUND_TEMP).
    ctx3 = vio.make_context({}, {"hourly": []}, now)
    assert ctx3.lat == shared_const.LATITUDE and ctx3.lon == shared_const.LONGITUDE
    assert ctx3.neighbor_temp == pytest.approx(min(vp.NEIGHBOR_SUMMER_CAP, vp.NEIGHBOR_TEMP))
    assert ctx3.ground_temp == pytest.approx(vp.GROUND_TEMP)


def test_house_location_fallback():
    assert vio.house_location({"location": {"lat": 1.0, "lon": 2.0}}) == (1.0, 2.0)
    assert vio.house_location({}) == (shared_const.LATITUDE, shared_const.LONGITUDE)


# ── 10. Maand-shards (geërfd van tweeling 2 — de enige overlevers van die suite) ─────

def _wd_fixture(t0: datetime, n: int = 8) -> dict:
    hist = [{"t": (t0 + timedelta(minutes=15 * i)).isoformat(),
             "temp": 21.0 + 0.1 * i, "hum": 50 + i, "heat": 1 if i == 2 else 0}
            for i in range(n)]
    return {"rooms": {"Living room": {"history": hist, "inside": 22.0, "humidity": 55}}}


def test_append_history_shard_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path))
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
    wd = _wd_fixture(t0)
    log = [{"t": t0.isoformat(), "states": {"a_win": "open"}}]
    n1 = vio.append_history_shard(wd, log, t0)
    assert n1 == 8
    n2 = vio.append_history_shard(wd, log, t0)     # tweede aanroep: no-op
    assert n2 == 0
    shard = json.load(open(tmp_path / "2026-07.json"))
    assert len(shard["rooms"]["Living room"]["ts"]) == 8
    # Privacy-scrub: de openingen-snapshots gaan niet meer de gecommitte shard in —
    # elke rij was een minuut-gestempelde menselijke handeling in publieke historie.
    assert "openings" not in shard


def test_shard_excluded_rooms_vertaalt_naar_de_gepubliceerde_naam():
    """De vlag staat op de huismodel-id, de shards zijn op de window_data-naam
    gesleuteld — `shard_excluded_rooms` overbrugt dat. Geen huismodel → fail open."""
    house = {"rooms": {"bath": {"from_window_data": "Shower", "exclude_from_shards": True},
                       "living": {"from_window_data": "Living room"},
                       "stair": {"exclude_from_shards": True}}}   # sensorloos: niets te skippen
    assert vio.shard_excluded_rooms(house) == {"Shower"}
    assert vio.shard_excluded_rooms(None) == set()
    assert vio.shard_excluded_rooms({}) == set()


def test_append_history_shard_slaat_exclude_from_shards_kamers_over(tmp_path, monkeypatch):
    """Privacy-sweep aug 2026: badkamervocht per kwartier is een douche-/
    aanwezigheidsspoor en hoort niet blijvend in publieke git. De kamer blijft
    wél gewoon in window_data staan (fysica/plattegrond/kamerkaart)."""
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path))
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
    wd = _wd_fixture(t0)
    wd["rooms"]["Shower"] = dict(wd["rooms"]["Living room"])
    house = {"rooms": {"bath": {"from_window_data": "Shower", "exclude_from_shards": True}}}

    n = vio.append_history_shard(wd, [], t0, house=house)
    shard = json.load(open(tmp_path / "2026-07.json"))
    assert "Shower" not in shard["rooms"]
    assert len(shard["rooms"]["Living room"]["ts"]) == 8
    assert n == 8                                  # alleen de niet-uitgesloten kamer telt

    # Zonder huismodel blijft het oude gedrag staan (fail open).
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path / "open"))
    vio.append_history_shard(wd, [], t0)
    assert "Shower" in json.load(open(tmp_path / "open" / "2026-07.json"))["rooms"]


def test_geen_badkamer_in_de_gecommitte_shards():
    """Regressiewacht op de échte artefacten: de kamers met `exclude_from_shards`
    in house_model.json mogen in geen enkele gecommitte shard voorkomen.

    Op `git ls-files` en niet op een disk-glob: sinds de shard-privatisering
    (privacy-assessment aug 2026) is de lokale dir een gitignored terugval en
    telt alleen wat daadwerkelijk gepubliceerd wordt — een lokale
    bootstrap-shard mag deze test niet laten klappen. Zodra de zelf-uitvoerende
    migratie de boom heeft geschoond, itereert dit over niets en is dat de
    gewenste eindtoestand."""
    house = json.load(open(os.path.join(_ROOT, "house_model.json")))
    skip = vio.shard_excluded_rooms(house)
    assert skip, "verwacht ten minste één exclude_from_shards-kamer"
    tracked = subprocess.run(
        ["git", "-C", _ROOT, "ls-files", "data/twin2_history"],
        capture_output=True, text=True, check=True).stdout.split()
    for rel in tracked:
        path = os.path.join(_ROOT, rel)
        if not (rel.endswith(".json") and os.path.exists(path)):
            continue
        rooms = json.load(open(path))["rooms"]
        assert not (skip & set(rooms)), f"{os.path.basename(path)} draagt {skip & set(rooms)}"


def test_append_history_shard_month_split(tmp_path, monkeypatch):
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path))
    t0 = datetime(2026, 6, 30, 23, 30, tzinfo=TZ)   # samples rollen over de maandgrens
    wd = _wd_fixture(t0, n=6)
    vio.append_history_shard(wd, [], t0 + timedelta(hours=2))
    juni = json.load(open(tmp_path / "2026-06.json"))
    juli = json.load(open(tmp_path / "2026-07.json"))
    assert len(juni["rooms"]["Living room"]["ts"]) + \
        len(juli["rooms"]["Living room"]["ts"]) == 6


def test_load_dataset_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path / "shards"))
    monkeypatch.setenv("VENT_OPENINGS_ARCHIVE_DIR", str(tmp_path / "archief"))
    monkeypatch.delenv("GIST_ID", raising=False)
    house = {"rooms": {"a": {"from_window_data": "Living room"}}}
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
    log = [{"t": t0.isoformat(), "states": {"x": 1}}]
    vio.append_history_shard(_wd_fixture(t0), log, t0)
    assert vio.append_openings_archive(log) == 1     # log → privé archief (dir-override)
    ds = vio.load_dataset(house)
    assert len(ds["actual"]["a"]) == 8               # 'Living room' → kamer-id 'a'
    assert ds["actual"]["a"][0][1] == pytest.approx(21.0)
    assert len(ds["actual_rh"]["a"]) == 8
    assert len(ds["heat_on"]["a"]) == 1              # de ene heat-vlag
    assert ds["log"][0]["states"] == {"x": 1}
    assert ds["weather_rows"] == []                  # weer komt pas van de batch/backfill
    # Onbekende kamernaam (geen from_window_data-mapping) → samples vallen stil weg.
    assert vio.load_dataset({"rooms": {}}) == {"actual": {}, "actual_rh": {}, "heat_on": {},
                                               "weather_rows": [], "log": ds["log"]}


def _wx_rows(t0: datetime, n: int) -> list[dict]:
    return [{"dt": t0 + timedelta(hours=i), "T_out": 20.0 + i, "rh": 50.0, "precip": 0.0,
             "wind_speed": 1.0, "wind_dir": 200.0, "gust": 2.0,
             "shortwave": 100.0, "direct": 60.0, "diffuse": 40.0} for i in range(n)]


def test_refresh_shard_weather_merges_never_replaces(tmp_path, monkeypatch):
    """Het juli-2026-gat: een tweede fetch met een smaller bereik wíste de rest van de
    maand, waardoor het shard-weer op 07-16 bleef staan terwijl de kamerdata doorliep."""
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path))
    t0 = datetime(2026, 7, 10, 0, 0, tzinfo=TZ)
    assert vio.refresh_shard_weather(_wx_rows(t0, 24)) == 24
    # Smaller venster (bv. een half-mislukte staart-fallback) mag niets weggooien.
    assert vio.refresh_shard_weather(_wx_rows(t0 + timedelta(hours=20), 8)) == 4
    shard = json.load(open(tmp_path / "2026-07.json"))
    assert len(shard["weather"]) == 28
    assert [r["dt"] for r in shard["weather"]] == sorted(r["dt"] for r in shard["weather"])


def test_refresh_shard_weather_overwrite_flag(tmp_path, monkeypatch):
    """overwrite=True → archief wint; overwrite=False → alleen gaten vullen, zodat de
    kwartierrun een ERA5-rij nooit terugzet naar zijn forecast-waarde."""
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path))
    t0 = datetime(2026, 7, 10, 0, 0, tzinfo=TZ)
    vio.refresh_shard_weather(_wx_rows(t0, 3))
    warmer = [{**r, "T_out": 99.0} for r in _wx_rows(t0, 3)]
    vio.refresh_shard_weather(warmer, overwrite=False)
    shard = json.load(open(tmp_path / "2026-07.json"))
    assert [r["T_out"] for r in shard["weather"]] == [20.0, 21.0, 22.0]
    vio.refresh_shard_weather(warmer, overwrite=True)
    shard = json.load(open(tmp_path / "2026-07.json"))
    assert [r["T_out"] for r in shard["weather"]] == [99.0, 99.0, 99.0]


def test_append_shard_weather_drops_the_forecast_tail(tmp_path, monkeypatch):
    """De kwartierrun vult het weer bij uit zijn eigen fetch, maar alléén verstreken
    uren — de forecast-staart is gemodelleerde toekomst, geen grondwaarheid."""
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path))
    t0 = datetime(2026, 7, 10, 0, 0, tzinfo=TZ)
    now = t0 + timedelta(hours=5)
    weather = {"hourly": _wx_rows(t0, 12)}
    assert vio.append_shard_weather(weather, now) == 6          # t0..t0+5u
    shard = json.load(open(tmp_path / "2026-07.json"))
    assert len(shard["weather"]) == 6
    assert shard["weather"][-1]["dt"] == now.isoformat()
    assert vio.append_shard_weather(weather, now) == 0          # idempotent


def test_load_dataset_merges_weather_and_dedups_log(tmp_path, monkeypatch):
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path / "shards"))
    monkeypatch.setenv("VENT_OPENINGS_ARCHIVE_DIR", str(tmp_path / "archief"))
    monkeypatch.delenv("GIST_ID", raising=False)
    house = {"rooms": {"a": {"from_window_data": "Living room"}}}
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
    log = [{"t": t0.isoformat(), "states": {"x": 1}}]
    vio.refresh_shard_weather(_wx_rows(t0, 3))
    vio.append_history_shard(_wd_fixture(t0), log, t0)
    assert vio.append_openings_archive(log) == 1
    assert vio.append_openings_archive(log) == 0     # dubbele append → gededupliceerd
    ds = vio.load_dataset(house)
    assert len(ds["log"]) == 1
    assert len(ds["weather_rows"]) == 3
    # dt-stempels komen als tz-bewuste datetimes terug, chronologisch.
    dts = [r["dt"] for r in ds["weather_rows"]]
    assert all(isinstance(d, datetime) and d.tzinfo is not None for d in dts)
    assert dts == sorted(dts)


# ── forecast-log (data/forecast_log): de weersvoorspelling zelf als meetobject ──────────

def test_forecast_log_roundtrip_en_cadans(tmp_path, monkeypatch):
    """append_forecast_shard logt het lopende + toekomstige uur-venster compact, hooguit
    één snapshot per FORECAST_ISSUE_EVERY_H; load_forecast_log decodeert bit-getrouw
    genoeg (±0.05° op temp) terug naar fetch_weather-rijvorm."""
    monkeypatch.setattr(vio, "FORECAST_LOG_DIR", str(tmp_path))
    now = datetime(2026, 8, 13, 10, 7, tzinfo=TZ)
    weather = {"hourly": _wx_rows(now.replace(minute=0) - timedelta(hours=30), 78)}
    assert vio.append_forecast_shard(weather, now) > 0
    # Kwartierrun een kwartier later: binnen de cadans → no-op.
    assert vio.append_forecast_shard(weather, now + timedelta(minutes=15)) == 0
    # Ná de cadans: nieuw snapshot.
    assert vio.append_forecast_shard(weather, now + timedelta(hours=3, minutes=1)) > 0

    log = vio.load_forecast_log()
    assert len(log) == 2
    assert log[0]["issued"] == now
    rows = log[0]["rows"]
    # Alleen het venster vanaf ~2u vóór het uitgiftemoment (interpolatie-aanloop).
    assert rows[0]["dt"] >= now - timedelta(hours=2)
    orig = {r["dt"]: r for r in weather["hourly"]}
    for r in rows:
        assert abs(r["T_out"] - orig[r["dt"]]["T_out"]) <= 0.051
        assert abs(r["wind_speed"] - orig[r["dt"]]["wind_speed"]) <= 0.051
        assert r["rh"] == orig[r["dt"]]["rh"]


def test_forecast_log_leeg_geeft_lege_lijst(tmp_path, monkeypatch):
    monkeypatch.setattr(vio, "FORECAST_LOG_DIR", str(tmp_path / "bestaat-niet"))
    assert vio.load_forecast_log() == []


# ── vaste dagritmes (house_model.json `routines`) op de forecast-timelines ──────────────

def _routine_house():
    return {"routines": {
        "_README": "commentaar wordt overgeslagen",
        "nursery_window_shade": {"state": "dicht", "from_h": 19, "to_h": 8},
        "middag_element": {"state": "open", "from_h": 12, "to_h": 14},
    }}


def _routine_tl(t0: datetime, hours: int) -> list[dict]:
    return [{"t": t0 + timedelta(hours=h), "states": {"iets": "open"}}
            for h in range(hours)]


def test_apply_routines_dwingt_het_nachtvenster_af():
    """Over-middernacht-venster (19→08): actief 's avonds en 's ochtends vroeg, niet
    overdag; een dag-venster (12→14) werkt gewoon binnen de dag. Het origineel blijft
    onaangeroerd en niet-routine-standen blijven staan."""
    t0 = datetime(2026, 8, 13, 0, 0, tzinfo=TZ)
    tl = _routine_tl(t0, 24)
    out = vio.apply_routines(tl, _routine_house())
    by_hour = {s["t"].hour: s["states"] for s in out}
    for h in (19, 23, 0, 7):
        assert by_hour[h]["nursery_window_shade"] == "dicht", h
    for h in (8, 12, 18):
        assert "nursery_window_shade" not in by_hour[h], h
    assert by_hour[12]["middag_element"] == "open"
    assert by_hour[14].get("middag_element") is None
    assert all(s["states"]["iets"] == "open" for s in out)
    assert "nursery_window_shade" not in tl[20]["states"]      # origineel niet gemuteerd


def test_apply_routines_respecteert_from_t_en_leeg_huis():
    """`from_t` laat het verleden met rust (de gemelde log blijft daar de waarheid);
    zonder routines-blok komt exact dezelfde timeline terug."""
    t0 = datetime(2026, 8, 13, 18, 0, tzinfo=TZ)
    tl = _routine_tl(t0, 6)                                # 18:00 → 23:00
    out = vio.apply_routines(tl, _routine_house(), from_t=t0 + timedelta(hours=3))
    assert "nursery_window_shade" not in out[1]["states"]      # 19:00, vóór from_t → log
    assert out[4]["states"]["nursery_window_shade"] == "dicht"  # 22:00, ná from_t
    assert vio.apply_routines(tl, {"rooms": {}}) is tl


def test_scenario_override_wint_van_de_routine():
    """De nachtvoorspelling forceert scenario-standen ná de routine — een geforceerde
    stand op hetzelfde element moet dan winnen (dict-merge-volgorde)."""
    t0 = datetime(2026, 8, 13, 20, 0, tzinfo=TZ)
    tl = vio.apply_routines(_routine_tl(t0, 2), _routine_house())
    forced = [{**s, "states": {**s["states"], "nursery_window_shade": "open"}} for s in tl]
    assert all(s["states"]["nursery_window_shade"] == "open" for s in forced)


def test_apply_routines_expliciete_melding_in_het_venster_wint():
    """De log-wint-regel: op de zeldzame avond dat de deur wél opengezet en gemeld wordt
    (de kinderkamer te warm, buiten koeler) mag de routine het eigen rapport niet overschrijven —
    anders spreken dashboard en koelplan-baseline de gemelde stand tegen. Een melding
    van vóór het venster (gistermiddag) telt niet: dan geldt gewoon het dagritme."""
    huis = {"routines": {"nursery_stair": {"state": "dicht", "from_h": 19, "to_h": 8}}}
    t0 = datetime(2026, 8, 13, 22, 0, tzinfo=TZ)          # avond, in het venster
    tl = [{"t": t0 + timedelta(hours=h), "states": {"nursery_stair": "open"}}
          for h in range(4)]                              # 22:00 → 01:00 (over middernacht)
    binnen = [{"t": datetime(2026, 8, 13, 21, 30, tzinfo=TZ).isoformat(),
               "states": {"nursery_stair": "open"}}]
    ervoor = [{"t": datetime(2026, 8, 13, 14, 0, tzinfo=TZ).isoformat(),
               "states": {"nursery_stair": "open"}}]
    # Melding om 21:30 (ná venster-start 19:00) → log wint, ook voorbij middernacht.
    out = vio.apply_routines(tl, huis, log=binnen)
    assert all(s["states"]["nursery_stair"] == "open" for s in out)
    # Melding om 14:00 (vóór venster-start) → routine wint.
    out = vio.apply_routines(tl, huis, log=ervoor)
    assert all(s["states"]["nursery_stair"] == "dicht" for s in out)
    # Zonder log: routine wint altijd (oude gedrag).
    out = vio.apply_routines(tl, huis)
    assert all(s["states"]["nursery_stair"] == "dicht" for s in out)


def test_apply_routines_melding_over_een_ander_element_telt_niet():
    """Alleen een melding over hét routine-element schort de routine op — een
    raampje-melding om 21:00 zegt niets over de deur."""
    huis = {"routines": {"nursery_stair": {"state": "dicht", "from_h": 19, "to_h": 8}}}
    t0 = datetime(2026, 8, 13, 22, 0, tzinfo=TZ)
    tl = [{"t": t0, "states": {}}]
    log = [{"t": datetime(2026, 8, 13, 21, 0, tzinfo=TZ).isoformat(),
            "states": {"nursery_small_window": "open"}}]
    out = vio.apply_routines(tl, huis, log=log)
    assert out[0]["states"]["nursery_stair"] == "dicht"


# ── Openingen-archief (privé Gist; hier via de dir-override) ─────────────────────────

def test_openings_archief_maand_shards_en_dedup(tmp_path, monkeypatch):
    monkeypatch.setenv("VENT_OPENINGS_ARCHIVE_DIR", str(tmp_path))
    monkeypatch.delenv("GIST_ID", raising=False)
    t_jun = datetime(2026, 6, 30, 23, 30, tzinfo=TZ)
    t_jul = datetime(2026, 7, 1, 0, 15, tzinfo=TZ)
    log = [{"t": t_jun.isoformat(), "states": {"a": "open"}},
           {"t": t_jul.isoformat(), "states": {"a": "dicht"}}]
    assert vio.append_openings_archive(log) == 2
    assert vio.append_openings_archive(log) == 0        # idempotent op t
    jun = json.load(open(tmp_path / "house_openings_2026-06.json"))
    jul = json.load(open(tmp_path / "house_openings_2026-07.json"))
    assert [e["t"] for e in jun["log"]] == [t_jun.isoformat()]
    assert jul["log"][0]["states"] == {"a": "dicht"}
    merged = vio.load_openings_archive(include_live=False)
    assert [e["t"] for e in merged] == sorted(e["t"] for e in log)


def test_migrate_shard_openings_seed_verify_strip(tmp_path, monkeypatch):
    """De zelf-uitvoerende migratie: legacy shard-openings → archief, read-back-
    verificatie, dán pas strippen. Een tweede aanroep is een no-op."""
    shards = tmp_path / "shards"
    archief = tmp_path / "archief"
    monkeypatch.setattr(vio, "HISTORY_DIR", str(shards))
    monkeypatch.setenv("VENT_OPENINGS_ARCHIVE_DIR", str(archief))
    monkeypatch.delenv("GIST_ID", raising=False)
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
    shards.mkdir()
    json.dump({"schema": 1, "month": "2026-07", "rooms": {}, "weather": [],
               "openings": [{"t": t0.isoformat(), "states": {"a_win": "open"}},
                            {"t": (t0 + timedelta(hours=1)).isoformat(),
                             "states": {"a_win": "dicht"}}]},
              open(shards / "2026-07.json", "w"))
    assert vio.migrate_shard_openings() == 2
    shard = json.load(open(shards / "2026-07.json"))
    assert "openings" not in shard                       # gestript ná verificatie
    arch = json.load(open(archief / "house_openings_2026-07.json"))
    assert len(arch["log"]) == 2
    assert vio.migrate_shard_openings() == 0             # klaar → no-op
    # De dataset ziet de gemigreerde log gewoon terug via het archief.
    ds = vio.load_dataset({"rooms": {}})
    assert [e["states"]["a_win"] for e in ds["log"]] == ["open", "dicht"]


def test_migrate_shard_openings_zonder_archief_laat_shards_staan(tmp_path, monkeypatch):
    """Geen creds én geen dir-override → de migratie mag de shards NIET strippen
    (de shards zijn dan nog de enige plek waar de historie bestaat)."""
    shards = tmp_path / "shards"
    monkeypatch.setattr(vio, "HISTORY_DIR", str(shards))
    monkeypatch.delenv("VENT_OPENINGS_ARCHIVE_DIR", raising=False)
    monkeypatch.delenv("GIST_ID", raising=False)
    monkeypatch.delenv("GIST_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
    shards.mkdir()
    json.dump({"schema": 1, "month": "2026-07", "rooms": {}, "weather": [],
               "openings": [{"t": t0.isoformat(), "states": {"a": "open"}}]},
              open(shards / "2026-07.json", "w"))
    assert vio.migrate_shard_openings() == 0
    shard = json.load(open(shards / "2026-07.json"))
    assert len(shard["openings"]) == 1                   # niets verloren


# ── Shard-privatisering: Gist-backend + zelf-uitvoerende migratie (aug 2026) ──

def _fake_gist(monkeypatch, tmp_path, store: dict) -> None:
    """Gist-modus met een in-memory dubbelganger: HISTORY_DIR wijst naar tmp
    én _HISTORY_DIR_DEFAULT schuift mee (zo ziet _history_gist_active het
    'onaangepaste default-pad'), creds staan, en de drie Gist-randen
    (read_file/read_files/_gist_write_files) draaien op `store`."""
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path))
    monkeypatch.setattr(vio, "_HISTORY_DIR_DEFAULT", str(tmp_path))
    monkeypatch.setenv("GIST_ID", "g123")
    monkeypatch.setenv("GIST_TOKEN", "t456")
    monkeypatch.delenv("VENT_OPENINGS_ARCHIVE_DIR", raising=False)
    monkeypatch.setattr(vio.gist_io, "read_file",
                        lambda gid, name, token=None, timeout=20: store.get(name))
    monkeypatch.setattr(vio.gist_io, "read_files",
                        lambda gid, token=None, timeout=20: dict(store))
    monkeypatch.setattr(vio, "_gist_write_files",
                        lambda files: store.update(files))


def test_shard_gist_roundtrip_append_en_load_dataset(tmp_path, monkeypatch):
    store: dict[str, str] = {}
    _fake_gist(monkeypatch, tmp_path, store)
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
    n = vio.append_history_shard(_wd_fixture(t0), [], t0 + timedelta(hours=3))
    assert n == 8
    assert "twin2_history_2026-07.json" in store
    assert not list((tmp_path).glob("*.json"))          # niets lokaal geschreven
    house = {"rooms": {"a": {"from_window_data": "Living room"}}}
    ds = vio.load_dataset(house)
    assert len(ds["actual"]["a"]) == 8


def test_shard_gist_leesfout_raist_en_schrijft_niet(tmp_path, monkeypatch):
    """Een netwerkfout op de read-modify-write mag de Gist-maand nooit
    overschrijven met alleen verse samples (stil dataverlies)."""
    store: dict[str, str] = {}
    _fake_gist(monkeypatch, tmp_path, store)

    def boom(*a, **k):
        raise RuntimeError("gist down")
    monkeypatch.setattr(vio.gist_io, "read_file", boom)
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
    with pytest.raises(RuntimeError):
        vio.append_history_shard(_wd_fixture(t0), [], t0 + timedelta(hours=3))
    assert store == {}


def test_migrate_history_shards_seed_verify_delete(tmp_path, monkeypatch):
    store: dict[str, str] = {}
    # Eerst lokaal (geen creds → lokale modus) een boom-shard neerzetten.
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path))
    monkeypatch.delenv("GIST_ID", raising=False)
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
    vio.append_history_shard(_wd_fixture(t0), [], t0 + timedelta(hours=3))
    assert (tmp_path / "2026-07.json").exists()
    # Dan de Gist-modus aan: migratie moet seed'en, verifiëren en verwijderen.
    _fake_gist(monkeypatch, tmp_path, store)
    assert vio.migrate_history_shards() == 1
    assert not (tmp_path / "2026-07.json").exists()
    gist_shard = json.loads(store["twin2_history_2026-07.json"])
    assert len(gist_shard["rooms"]["Living room"]["ts"]) == 8
    # Idempotent: tweede aanroep vindt niets meer.
    assert vio.migrate_history_shards() == 0


def test_migrate_history_shards_union_gist_wint(tmp_path, monkeypatch):
    """Bestaat de Gist-maand al (de append van dezelfde run), dan is de migratie
    een unie per tijdstip waarin de Gist-kopie wint — geen verlies, geen dubbels."""
    store: dict[str, str] = {}
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path))
    monkeypatch.delenv("GIST_ID", raising=False)
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
    vio.append_history_shard(_wd_fixture(t0, n=4), [], t0 + timedelta(hours=3))
    _fake_gist(monkeypatch, tmp_path, store)
    # Gist draagt al een overlappende + een nieuwere kolom (temp afwijkend op t0).
    epoch = int(t0.timestamp())
    store["twin2_history_2026-07.json"] = json.dumps(
        {"schema": 1, "month": "2026-07",
         "rooms": {"Living room": {"ts": [epoch, epoch + 86400],
                                   "temp": [999, 250], "hum": [1, 2], "heat": [0, 0]}},
         "weather": []})
    assert vio.migrate_history_shards() == 1
    cols = json.loads(store["twin2_history_2026-07.json"])["rooms"]["Living room"]
    assert cols["ts"] == sorted(cols["ts"]) and len(cols["ts"]) == 5
    assert cols["temp"][cols["ts"].index(epoch)] == 999   # gist won op de overlap


def test_migrate_history_shards_zonder_creds_no_op(tmp_path, monkeypatch):
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path))
    monkeypatch.setattr(vio, "_HISTORY_DIR_DEFAULT", str(tmp_path))
    monkeypatch.delenv("GIST_ID", raising=False)
    monkeypatch.delenv("GIST_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
    vio.append_history_shard(_wd_fixture(t0), [], t0 + timedelta(hours=3))
    assert vio.migrate_history_shards() == 0
    assert (tmp_path / "2026-07.json").exists()           # boom ongemoeid


def test_migrate_history_shards_readback_mist_laat_boom_staan(tmp_path, monkeypatch, capsys):
    store: dict[str, str] = {}
    monkeypatch.setattr(vio, "HISTORY_DIR", str(tmp_path))
    monkeypatch.delenv("GIST_ID", raising=False)
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
    vio.append_history_shard(_wd_fixture(t0), [], t0 + timedelta(hours=3))
    _fake_gist(monkeypatch, tmp_path, store)
    # Schrijven "lukt" maar de read-back geeft een lege maand terug.
    monkeypatch.setattr(vio, "_gist_write_files", lambda files: None)
    monkeypatch.setattr(vio.gist_io, "read_file",
                        lambda gid, name, token=None, timeout=20: None)
    assert vio.migrate_history_shards() == 0
    assert (tmp_path / "2026-07.json").exists()
    assert "read-back" in capsys.readouterr().out


def test_load_dataset_lokale_overlay_wint_van_gist(tmp_path, monkeypatch):
    """De twin-eval-constructie: het ERA5-ververste lokale weer (zonder creds
    geschreven) wint per uur van de Gist-kopie."""
    store: dict[str, str] = {}
    _fake_gist(monkeypatch, tmp_path, store)
    iso = "2026-07-10T13:00:00+02:00"
    store["twin2_history_2026-07.json"] = json.dumps(
        {"schema": 1, "month": "2026-07", "rooms": {},
         "weather": [{"dt": iso, "T_out": 20.0}]})
    (tmp_path / "2026-07.json").write_text(json.dumps(
        {"schema": 1, "month": "2026-07", "rooms": {},
         "weather": [{"dt": iso, "T_out": 99.0}]}))
    ds = vio.load_dataset({"rooms": {}})
    assert [r["T_out"] for r in ds["weather_rows"]] == [99.0]
