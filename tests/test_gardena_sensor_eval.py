"""Tests voor de sensor-vs-model-evaluatie (`tools/gardena_sensor_eval.py`).

Geen netwerk, geen artefacten: alles draait op handgemaakte rijen. De tests
pinnen op de dingen die de conclusie dragen — de inregel-filter, de
resolutieschatting (die bepaalt wat er überhaupt meetbaar is), de
kandidaat-mappings en de dynamiek-maat.
"""
from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timedelta, timezone

from shared_const import TZ

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "gardena_sensor_eval", os.path.join(_ROOT, "tools", "gardena_sensor_eval.py"))
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

FC, WP = 0.20, 0.09


def _row(t: datetime, hum=70, temp=20):
    return {"t": t.astimezone(TZ).isoformat(), "soil_hum": hum, "soil_temp": temp}


def _hourly(day: str, hum=70, temp=20, hours=24):
    """Uurlijkse rijen over één lokale dag."""
    start = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=TZ)
    return [_row(start + timedelta(hours=h), hum, temp) for h in range(hours)]


def _theta_for(aw_pct: float) -> float:
    """De θ die hoort bij een gegeven % plantbeschikbaar water."""
    return WP + aw_pct / 100.0 * (FC - WP)


def _day(date: str, aw_lawn: float, aw_shrubs: float, de=1.0, forecast=False):
    return {"date": date, "forecast": forecast, "precip": 0.0, "ET0": 3.0,
            "lawn_theta": _theta_for(aw_lawn), "lawn_De": de,
            "shrubs_theta": _theta_for(aw_shrubs), "shrubs_De": de,
            "Tsoil_shallow": 20.0, "Tsoil_root": 19.0}


# ── inregel-filter ──────────────────────────────────────────────────────────

def test_inregel_rijen_worden_gemarkeerd_niet_verwijderd():
    """De filter mag rijen markeren, nooit stilletjes weggooien — het rapport
    drukt ze af zodat de lezer de keuze zelf kan wegen."""
    base = datetime(2026, 8, 14, 21, 0, tzinfo=TZ)
    rows = [_row(base), _row(base + timedelta(hours=1)), _row(base + timedelta(hours=3))]
    marked = ev.mark_settling(rows, settle_h=2.0)
    assert len(marked) == 3
    assert [r["settling"] for r in marked] == [True, True, False]


def test_settle_venster_nul_laat_alles_staan():
    base = datetime(2026, 8, 14, 21, 0, tzinfo=TZ)
    marked = ev.mark_settling([_row(base), _row(base + timedelta(hours=1))], settle_h=0.0)
    assert not any(r["settling"] for r in marked)


def test_lege_invoer_geeft_lege_lijst():
    assert ev.mark_settling([], settle_h=2.0) == []


# ── resolutie ───────────────────────────────────────────────────────────────

def test_resolutie_schat_de_stapgrootte_uit_de_verschillen():
    """Stappen van 5 betekent dat een modeldrift van 3 %/dag onmeetbaar is —
    dit getal bepaalt of 'de sensor stond stil' iets bevestigt of niets zegt."""
    res = ev.resolution([65, 70, 75, 70, 65])
    assert res["step"] == 5
    assert res["distinct"] == [65, 70, 75]
    assert res["span"] == 10


def test_resolutie_met_een_enkele_waarde_doet_geen_uitspraak():
    res = ev.resolution([70, 70, 70])
    assert res["step"] is None
    assert res["n_distinct"] == 1


def test_resolutie_telt_de_inregel_waarde_mee():
    """De stapgrootte is een eigenschap van het apparaat, niet van de bodem: de
    afwijkende eerste meting levert juist het eerste bruikbare verschil."""
    rows = ev.mark_settling(_hourly("2026-08-14", hum=65)[:1] + _hourly("2026-08-15"),
                            settle_h=2.0)
    res = ev.resolution([r.get("soil_hum") for r in rows])
    assert res["distinct"] == [65, 70]


# ── mappings ────────────────────────────────────────────────────────────────

def test_available_water_is_het_spiegelbeeld_van_depletie():
    assert ev.available_water(FC, FC, WP) == 100.0
    assert ev.available_water(WP, FC, WP) == 0.0
    assert abs(ev.available_water(_theta_for(73.5), FC, WP) - 73.5) < 1e-9


def test_surface_available_loopt_van_vol_naar_leeg():
    assert ev.surface_available(0.0, 18.0) == 100.0
    assert ev.surface_available(18.0, 18.0) == 0.0
    assert ev.surface_available(None, 18.0) is None


def test_alle_kandidaat_mappings_worden_doorgerekend():
    """Bewust geen enkele mapping vooraf kiezen — welke standhoudt is een
    empirische vraag voor de groeiende reeks."""
    m = ev.candidate_mappings(_day("2026-08-15", 63.2, 73.5, de=1.4), "shrubs", FC, WP)
    assert set(m) == {"theta_x100", "available_water", "saturation", "surface_layer"}
    assert abs(m["available_water"] - 73.5) < 1e-6
    # θ×100 kan per constructie nooit bij een sensorwaarde van 70 in de buurt
    # komen: voor zand ligt θ rond 0.10–0.20.
    assert m["theta_x100"] < 25


def test_mapping_zonder_theta_geeft_niets():
    assert ev.candidate_mappings({"date": "x"}, "lawn", FC, WP) == {}


# ── dagaggregatie ───────────────────────────────────────────────────────────

def test_daily_sensor_groepeert_op_lokale_datum():
    rows = ev.mark_settling(_hourly("2026-08-16"), settle_h=0.0)
    days = ev.daily_sensor(rows)
    assert set(days) == {"2026-08-16"}
    assert days["2026-08-16"]["n"] == 24
    assert days["2026-08-16"]["coverage_h"] == 23.0


def test_daily_sensor_laat_inregel_rijen_buiten_de_statistiek():
    rows = ev.mark_settling(_hourly("2026-08-16", hum=10, hours=2)
                            + _hourly("2026-08-17", hum=70), settle_h=2.0)
    days = ev.daily_sensor(rows)
    assert "2026-08-16" not in days
    assert days["2026-08-17"]["mean"] == 70


# ── dynamiek ────────────────────────────────────────────────────────────────

def test_dynamiek_zwijgt_bij_te_weinig_dagen():
    """Liever geen uitspraak dan een correlatie over twee punten."""
    rows = ev.mark_settling(_hourly("2026-08-16"), settle_h=0.0)
    out = ev.dynamics([_day("2026-08-16", 60, 70)], ev.daily_sensor(rows), FC, WP)
    assert out["status"] == "insufficient"
    assert out["n_days"] == 1


def test_dynamiek_herkent_een_perfect_meelopende_sensor():
    """Als de sensor exact het beschikbare water rapporteert, hoort de helling
    1.0 te zijn en de correlatie 1.0 — ongeacht welk niveau-offset er zit."""
    aw = [80.0, 70.0, 60.0, 90.0]
    dates = ["2026-08-16", "2026-08-17", "2026-08-18", "2026-08-19"]
    rows = []
    for d, a in zip(dates, aw):
        rows += _hourly(d, hum=a)
    sensor = ev.daily_sensor(ev.mark_settling(rows, settle_h=0.0))
    days = [_day(d, a, a) for d, a in zip(dates, aw)]
    out = ev.dynamics(days, sensor, FC, WP)
    assert out["status"] == "ok" and out["n_days"] == 4
    st = out["zones"]["lawn"]["available_water"]
    assert abs(st["corr"] - 1.0) < 1e-6
    assert abs(st["slope"] - 1.0) < 1e-6


def test_dynamiek_ziet_een_sensor_die_de_verkeerde_kant_op_loopt():
    aw = [80.0, 70.0, 60.0, 90.0]
    dates = ["2026-08-16", "2026-08-17", "2026-08-18", "2026-08-19"]
    rows = []
    for d, a in zip(dates, aw):
        rows += _hourly(d, hum=100 - a)          # gespiegeld
    sensor = ev.daily_sensor(ev.mark_settling(rows, settle_h=0.0))
    days = [_day(d, a, a) for d, a in zip(dates, aw)]
    out = ev.dynamics(days, sensor, FC, WP)
    st = out["zones"]["lawn"]["available_water"]
    assert abs(st["corr"] + 1.0) < 1e-6
    assert st["slope"] < 0


def test_dynamiek_negeert_dagen_met_te_weinig_dekking():
    """Een halve dag heeft geen dagmiddel dat tegen een 24-uurs modelwaarde mag."""
    dates = ["2026-08-16", "2026-08-17", "2026-08-18"]
    rows = []
    for d in dates:
        rows += _hourly(d, hum=70, hours=4)      # 3 u dekking, ruim onder de eis
    sensor = ev.daily_sensor(ev.mark_settling(rows, settle_h=0.0))
    out = ev.dynamics([_day(d, 60, 70) for d in dates], sensor, FC, WP)
    assert out["status"] == "insufficient"
    assert out["n_days"] == 0


def test_dynamiek_slaat_forecast_dagen_over():
    """Een voorspelde dag is geen meting om tegen af te rekenen."""
    dates = ["2026-08-16", "2026-08-17", "2026-08-18"]
    rows = []
    for d in dates:
        rows += _hourly(d)
    sensor = ev.daily_sensor(ev.mark_settling(rows, settle_h=0.0))
    days = [_day(dates[0], 60, 70), _day(dates[1], 55, 65),
            _day(dates[2], 50, 60, forecast=True)]
    out = ev.dynamics(days, sensor, FC, WP)
    assert out["days"] == dates[:2]


# ── bodemtemperatuur ────────────────────────────────────────────────────────

def test_temp_table_markeert_een_halve_dag_als_niet_vol():
    """Een nachtmiddel tegen een 24-uurs modelmiddel meet het etmaal, niet de
    modelfout — het rapport moet dat zichtbaar maken."""
    rows = ev.mark_settling(_hourly("2026-08-15", temp=20, hours=9), settle_h=0.0)
    out = ev.temp_table(rows, [_day("2026-08-15", 60, 70)], {})
    day = out["days"][0]
    assert day["full_day"] is False
    assert day["sensor_mean"] == 20
    assert day["damping"] is None          # geen luchtreeks meegegeven


def test_temp_table_rekent_de_demping_tegen_de_lucht():
    """De dempingsverhouding is de sanity-check op de diepte van de prikker."""
    start = datetime(2026, 8, 15, 0, 0, tzinfo=TZ)
    rows, air = [], {}
    for h in range(24):
        t = start + timedelta(hours=h)
        rows.append(_row(t, temp=20 + (2 if h >= 12 else 0)))
        air[t.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)] = \
            15.0 + (10.0 if h >= 12 else 0.0)
    out = ev.temp_table(ev.mark_settling(rows, settle_h=0.0),
                        [_day("2026-08-15", 60, 70)], air)
    day = out["days"][0]
    assert day["full_day"] is True
    assert abs(day["sensor_amp"] - 2.0) < 1e-9
    assert abs(day["air_amp"] - 10.0) < 1e-9
    assert abs(day["damping"] - 0.2) < 1e-9


# ── bijvul-tekort per bak (de dieptetoets bij regen) ────────────────────────

def test_refill_mm_scheidt_de_twee_bakken():
    """De oppervlaktelaag staat bij een dichte canopy bijna vol en zit dus na een
    paar millimeter aan zijn plafond; de wortelzone moet het hele tekort t.o.v.
    veldcapaciteit goedmaken. Dat verschil is de dieptetoets bij regen."""
    day = _day("2026-08-17", aw_lawn=40.5, aw_shrubs=64.5, de=2.06)
    shrubs = ev.refill_mm(day, "shrubs", FC, WP)
    assert abs(shrubs["surface_mm"] - 2.06) < 1e-9
    assert abs(shrubs["awc_mm"] - 55.0) < 1e-9
    # 64,5 % beschikbaar → 35,5 % van 55 mm nog bij te vullen.
    assert abs(shrubs["rootzone_mm"] - 0.355 * 55.0) < 1e-6
    # De wortelzone heeft een veelvoud van de oppervlaktelaag nodig — anders
    # zou een regenbui de twee hypotheses niet kunnen scheiden.
    assert shrubs["rootzone_mm"] > 5 * shrubs["surface_mm"]


def test_refill_mm_is_nul_op_veldcapaciteit():
    day = _day("2026-08-19", aw_lawn=100.0, aw_shrubs=100.0, de=0.0)
    assert ev.refill_mm(day, "shrubs", FC, WP)["rootzone_mm"] == 0.0


def test_refill_mm_zonder_theta_geeft_none():
    out = ev.refill_mm({"date": "x"}, "lawn", FC, WP)
    assert out["rootzone_mm"] is None and out["surface_mm"] is None


# ── vooraf vastgelegde voorspelling ─────────────────────────────────────────

def test_pending_test_begint_bij_vandaag():
    days = [_day("2026-08-14", 70, 80), _day("2026-08-15", 63, 73),
            _day("2026-08-16", 50, 68, forecast=True)]
    out = ev.pending_test(days, FC, WP, today="2026-08-15")
    assert [r["date"] for r in out] == ["2026-08-15", "2026-08-16"]
    assert out[1]["forecast"] is True
    assert abs(out[1]["zones"]["lawn"]["available_water"] - 50) < 1e-6
    assert out[1]["refill"]["shrubs"]["rootzone_mm"] > 0


def test_de_prikker_zit_in_de_struiken():
    """Bewonersopgave (aug 2026) — bepaalt welke modelkolom de vergelijking
    draagt. `gardena_config.json` leeft in de Gist en draagt geen zoneveld, dus
    dit is opgegeven kennis en geen afleiding uit de data."""
    assert ev.SENSOR_ZONE == "shrubs"
