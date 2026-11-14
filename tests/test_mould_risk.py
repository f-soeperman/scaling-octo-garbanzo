"""Schimmelrisico-index: zuivere functies over kamertemp, kamer-RH en buitentemp."""
from datetime import datetime, timedelta

import pytest

import mould_risk as mr
from shared_const import TZ

NOW = datetime(2026, 1, 10, 12, 0, tzinfo=TZ)


def test_koude_plek_ligt_tussen_binnen_en_buiten():
    assert mr.surface_temp(16.0, 0.0, 0.65) == pytest.approx(10.4)
    # Buiten warmer dan binnen → geen koude plek.
    assert mr.surface_temp(18.0, 25.0, 0.65) == 18.0


def test_toegestane_rh_zakt_met_de_buitentemperatuur():
    koud = mr.allowed_rh(16.0, mr.surface_temp(16.0, 0.0))
    zacht = mr.allowed_rh(16.0, mr.surface_temp(16.0, 10.0))
    assert 53 < koud < 58          # ~55 % bij vorst
    assert 67 < zacht < 72         # ruimer op een zachte dag
    assert mr.allowed_rh(16.0, 16.0) == 80.0


def test_warmer_stoken_geeft_marge():
    op16 = mr.assess("x", 16.0, 60.0, 0.0)
    # Zelfde dampinhoud, kamer 2° warmer: de koude plek warmt mee op.
    rh18 = 60.0 * mr._es(16.0) / mr._es(18.0)
    op18 = mr.assess("x", 18.0, rh18, 0.0)
    assert op18["surface_rh"] < op16["surface_rh"]


def test_oordeel_en_marge_zijn_consistent():
    a = mr.assess("x", 16.0, 65.0, 0.0)
    assert a["level"] == "risico" and a["headroom"] < 0
    b = mr.assess("x", 19.5, 45.0, 8.0)
    assert b["level"] == "ok" and b["headroom"] > 0
    assert mr.assess("x", None, 50.0, 5.0) is None
    assert mr.assess("x", 18.0, 50.0, None) is None


def test_oppervlakte_rh_is_geklemd_op_condens():
    assert mr.surface_rh(20.0, 95.0, 5.0) == 100.0


def test_buitengemiddelde_over_het_laatste_etmaal():
    hist = [{"t": (NOW - timedelta(hours=h)).isoformat(), "temp": t}
            for h, t in [(30, 20.0), (20, 2.0), (1, 6.0)]] + [{"t": "kapot", "temp": 99}]
    assert mr.outside_mean(hist, NOW, None) == pytest.approx(4.0)
    assert mr.outside_mean([], NOW, 7.5) == 7.5


def test_logboek_telt_uren_per_dag_en_begrenst_gaten():
    risk = {"surface_rh": 85}
    t = mr.update_tally(None, NOW, {"a": risk, "b": {"surface_rh": 72}, "c": None})
    day = t["days"][NOW.date().isoformat()]
    assert day["a"] == {"h": 0.25, "watch_h": 0.25, "risk_h": 0.25, "max": 85}
    assert day["b"]["risk_h"] == 0 and day["b"]["watch_h"] == 0.25
    assert "c" not in day
    # Een gat van 6 uur (uitval) telt hooguit een halfuur mee.
    t2 = mr.update_tally(t, NOW + timedelta(hours=6), {"a": risk})
    assert t2["days"][NOW.date().isoformat()]["a"]["risk_h"] == 0.75
    assert t["days"][NOW.date().isoformat()]["a"]["risk_h"] == 0.25   # origineel ongemoeid


def test_logboek_houdt_twee_weken_en_weeksom_zeven_dagen():
    t = None
    for d in range(20):
        t = mr.update_tally(t, NOW + timedelta(days=d), {"a": {"surface_rh": 85}})
    assert len(t["days"]) == mr.TALLY_KEEP_D
    wk = mr.week_summary(t, NOW + timedelta(days=19), "a")
    assert wk["risk_h"] == pytest.approx(7 * 0.5) and wk["max"] == 85
    assert mr.week_summary(t, NOW, "onbekend")["h"] == 0
