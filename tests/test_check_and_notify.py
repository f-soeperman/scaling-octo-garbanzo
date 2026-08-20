"""Tests voor check_and_notify — de beslis-/berichtlaag van het bodemproject.

Gericht op de tot dusver ongeteste stukken: de θ-seed-clamp uit een (mogelijk
corrupte) docs/data.json en de opbouw van het Telegram-bericht. Geen netwerk.
"""

import json
from datetime import date, datetime

import check_and_notify
import shared_const
from check_and_notify import (advice_slot_open, format_telegram, load_previous_theta,
                              load_state, save_state)
from shared_const import NL_DAYS
from soil_model import SOIL_FC, SOIL_WP


# ── load_previous_theta ──────────────────────────────────────────────────────

def _write_data_json(tmp_path, payload):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "data.json").write_text(json.dumps(payload))


def test_seed_ontbrekend_bestand_geeft_leeg(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_previous_theta() == {}


def test_seed_corrupte_json_geeft_leeg(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "data.json").write_text("{niet json")
    assert load_previous_theta() == {}


def test_seed_geldige_theta_komt_terug(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_data_json(tmp_path, {"theta_end": {"as_of": "2026-06-30",
                                              "lawn": 0.14, "shrubs": 0.16}})
    assert load_previous_theta() == {"lawn": 0.14, "shrubs": 0.16}


def test_seed_buiten_fysiek_bereik_wordt_geklemd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_data_json(tmp_path, {"theta_end": {"lawn": 0.90, "shrubs": 0.01}})
    seed = load_previous_theta()
    assert seed["lawn"] == SOIL_FC   # boven veldcapaciteit → FC
    assert seed["shrubs"] == SOIL_WP  # onder verwelkingspunt → WP


def test_seed_niet_numeriek_wordt_genegeerd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_data_json(tmp_path, {"theta_end": {"lawn": "kapot", "shrubs": 0.15}})
    assert load_previous_theta() == {"shrubs": 0.15}


# ── format_telegram ──────────────────────────────────────────────────────────

def _status(priority="none", depletion=30.0, rec="Geen actie nodig",
            prop_mm=0.0, prop_min=0, rain7=5.0, **extra):
    return {"priority": priority, "depletion_pct": depletion,
            "recommendation": rec, "proposal_mm": prop_mm,
            "proposal_min": prop_min, "rain7_mm": rain7, **extra}


def test_bericht_bevat_nederlandse_datum(monkeypatch):
    monkeypatch.delenv("DASHBOARD_URL", raising=False)
    msg = format_telegram(_status(), _status(), "2026-07-01T06:00:00+00:00")
    # De runner heeft geen nl_NL-locale — de dagnaam moet uit NL_DAYS komen.
    assert any(dag in msg for dag in NL_DAYS)
    assert "Pineapple Under The Sea · dagcheck" in msg


def test_bericht_zonder_advies_geen_minutenregel():
    msg = format_telegram(_status(), _status(), "x")
    assert "⏱" not in msg
    assert "Beschikbaar water: <code>70%</code>" in msg


def test_bericht_met_beide_adviezen_toont_gecombineerde_regel():
    lawn = _status(priority="high", depletion=80.0, rec="Nu water geven",
                   prop_mm=16.7, prop_min=50)
    shrubs = _status(priority="medium", depletion=60.0, rec="Binnenkort water",
                     prop_mm=10.4, prop_min=312)
    msg = format_telegram(lawn, shrubs, "x")
    assert "🚨" in msg and "💧" in msg
    assert "Gras: <b>50 min</b> · Struiken: <b>312 min</b>" in msg


def test_bericht_dashboard_link_alleen_met_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_URL", "https://example.test/dash")
    msg = format_telegram(_status(), _status(), "x")
    assert "https://example.test/dash" in msg
    monkeypatch.delenv("DASHBOARD_URL")
    assert "example.test" not in format_telegram(_status(), _status(), "x")


def test_effectieve_regen_alleen_bij_wezenlijk_verschil():
    # Onderschepping < 1 mm verschil → geen effectief-regel (ruisonderdrukking).
    lawn = _status(rain7=10.0, eff_rain_7d_mm=9.5, eff_rain_3d_mm=4.0)
    shrubs = _status(rain7=10.0, eff_rain_7d_mm=9.4, eff_rain_3d_mm=3.9)
    assert "Effectief" not in format_telegram(lawn, shrubs, "x")

    lawn = _status(rain7=10.0, eff_rain_7d_mm=7.0, eff_rain_3d_mm=3.0)
    msg = format_telegram(lawn, shrubs, "x")
    assert "Effectief (7d): gras 7.0 mm" in msg


# ── meldslot (uurlijkse cadans) ──────────────────────────────────────────────
# De workflow ververst docs/data.json elk uur; het advies-bericht valt één
# keer per dag, op de eerste run op of ná NOTIFY_AT.

def _now(h, m=0):
    return datetime(2026, 6, 1, h, m, tzinfo=shared_const.TZ)


def test_meldslot_dicht_vóór_het_doeluur():
    uur, minuut = check_and_notify.NOTIFY_AT
    assert advice_slot_open({}, date(2026, 6, 1), now=_now(uur - 1, minuut)) is False


def test_meldslot_open_op_en_na_het_doeluur():
    uur, minuut = check_and_notify.NOTIFY_AT
    today = date(2026, 6, 1)
    assert advice_slot_open({}, today, now=_now(uur, minuut)) is True
    # Valt de run van het doeluur uit, dan meldt die van een uur later alsnog.
    assert advice_slot_open({}, today, now=_now(uur + 1, minuut)) is True


def test_meldslot_maar_één_keer_per_dag():
    uur, minuut = check_and_notify.NOTIFY_AT
    today = date(2026, 6, 1)
    state = {"last_advice_date": today.isoformat()}
    assert advice_slot_open(state, today, now=_now(uur, minuut)) is False
    assert advice_slot_open(state, today, now=_now(20, 0)) is False
    assert advice_slot_open(state, date(2026, 6, 2), now=_now(uur, minuut)) is True


def test_state_roundtrip_en_lege_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(check_and_notify, "STATE_FILE", str(tmp_path / "soil_state.json"))
    assert load_state()["last_advice_date"] is None      # ontbrekend bestand
    save_state({"last_advice_date": "2026-06-01", "last_advice_priority": "high"})
    again = load_state()
    assert again["last_advice_date"] == "2026-06-01"
    assert again["last_advice_priority"] == "high"
    assert again["last_updated"]                          # stempel gezet
