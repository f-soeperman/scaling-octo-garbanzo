"""Tests voor check_and_notify — de beslis-/berichtlaag van het bodemproject.

Gericht op de tot dusver ongeteste stukken: de θ-seed-clamp uit een (mogelijk
corrupte) docs/data.json en de opbouw van het Telegram-bericht. Geen netwerk.
"""

import json
from datetime import date, datetime

import check_and_notify
import shared_const
from check_and_notify import (advice_slot_open, format_telegram, load_previous_data,
                              load_state, save_state)
from check_and_notify import load_previous_theta as _theta_from
from shared_const import NL_DAYS
from soil_model import SOIL_FC, SOIL_WP


# ── load_previous_theta ──────────────────────────────────────────────────────

def load_previous_theta():
    """De productieketen: één read van de vorige data.json → de θ-seed eruit."""
    return _theta_from(load_previous_data())


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
    msg = format_telegram(_status(), _status())
    # De runner heeft geen nl_NL-locale — de dagnaam moet uit NL_DAYS komen.
    assert any(dag in msg for dag in NL_DAYS)
    assert "Pineapple Under The Sea · dagcheck" in msg


def test_bericht_zonder_advies_geen_minutenregel():
    msg = format_telegram(_status(), _status())
    assert "⏱" not in msg
    assert "Beschikbaar water: <code>70%</code>" in msg


def test_bericht_met_beide_adviezen_toont_gecombineerde_regel():
    lawn = _status(priority="high", depletion=80.0, rec="Nu water geven",
                   prop_mm=16.7, prop_min=50)
    shrubs = _status(priority="medium", depletion=60.0, rec="Binnenkort water",
                     prop_mm=10.4, prop_min=312)
    msg = format_telegram(lawn, shrubs)
    assert "🚨" in msg and "💧" in msg
    assert "Gras: <b>50 min</b> · Struiken: <b>312 min</b>" in msg


def test_bericht_dashboard_link_alleen_met_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_URL", "https://example.test/dash")
    msg = format_telegram(_status(), _status())
    assert "https://example.test/dash" in msg
    monkeypatch.delenv("DASHBOARD_URL")
    assert "example.test" not in format_telegram(_status(), _status())


def test_effectieve_regen_alleen_bij_wezenlijk_verschil():
    # Onderschepping < 1 mm verschil → geen effectief-regel (ruisonderdrukking).
    lawn = _status(rain7=10.0, eff_rain_7d_mm=9.5, eff_rain_3d_mm=4.0)
    shrubs = _status(rain7=10.0, eff_rain_7d_mm=9.4, eff_rain_3d_mm=3.9)
    assert "Effectief" not in format_telegram(lawn, shrubs)

    lawn = _status(rain7=10.0, eff_rain_7d_mm=7.0, eff_rain_3d_mm=3.0)
    msg = format_telegram(lawn, shrubs)
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
    save_state({"last_advice_date": "2026-06-01"})
    again = load_state()
    assert again["last_advice_date"] == "2026-06-01"
    assert again["last_updated"]                          # stempel gezet


def test_oude_prioriteit_verdwijnt_uit_bestaande_state(tmp_path, monkeypatch):
    """`last_advice_priority` stond publiek gecommit en werd nergens gelezen —
    een dagelijkse afgeleide van het irrigatie-logboek. Een bestaande state
    verliest het veld bij de eerstvolgende slot-run."""
    pad = tmp_path / "soil_state.json"
    pad.write_text(json.dumps({"last_advice_date": "2026-06-01",
                               "last_advice_priority": "high"}))
    monkeypatch.setattr(check_and_notify, "STATE_FILE", str(pad))
    state = load_state()
    assert "last_advice_priority" not in state
    save_state(state)
    assert "last_advice_priority" not in json.loads(pad.read_text())


def test_leesfout_op_de_vorige_data_is_geen_lege_start(monkeypatch):
    """Een haperende gist-read mag niet als "geen koude opslag" doorgaan: dan
    start de 13-maands bootstrap en overschrijft die de maandtotalen."""
    import pytest
    import requests

    monkeypatch.setenv("ARTEFACT_GIST_ID", "abc123")
    monkeypatch.setenv("GIST_TOKEN", "tok")

    def kapot(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(check_and_notify.artefact_io.gist_io.requests, "get", kapot)
    with pytest.raises(requests.ConnectionError):
        load_previous_data()


def _run_main(monkeypatch, tmp_path, capsys, priority):
    """Draai main() op een nagebootste slot-run met de gegeven prioriteit."""
    status = _status(priority=priority, prop_min=20 if priority != "none" else 0,
                     state="dry", deficit_mm=4.0, days_to_stress=1,
                     eff_rain_3d_mm=0.0, eff_rain_7d_mm=5.0,
                     eff_rain_intercepted_7d_mm=0.0)
    tmp_path.mkdir()
    monkeypatch.chdir(tmp_path)
    for k in ("ARTEFACT_GIST_ID", "GIST_ID", "FORCE_NOTIFY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(check_and_notify, "STATE_FILE", str(tmp_path / "soil_state.json"))
    monkeypatch.setattr(check_and_notify, "build_full_dataset",
                        lambda *a, **k: {"days": [], "generated_at": "x"})
    monkeypatch.setattr(check_and_notify, "bootstrap_monthly_totals", lambda irr: {})
    monkeypatch.setattr(check_and_notify, "assess_status", lambda data, zone: status)
    monkeypatch.setattr(check_and_notify, "advice_slot_open", lambda state, today: True)
    sent = []

    def fake_send(text, **k):
        print("[telegram] ✓ verzonden")
        sent.append(text)
        return True

    monkeypatch.setattr(check_and_notify, "send_telegram", fake_send)
    check_and_notify.main()
    return capsys.readouterr().out, sent


def test_publieke_log_is_gelijk_met_en_zonder_advies(monkeypatch, tmp_path, capsys):
    """De run is publiek en draait elk uur. Of er in het slot iets te melden
    viel volgt uit de waterbalans — en die kantelt zodra er een beurt gelogd
    is. De log mag dat verschil dus niet tonen (ook de prioriteit zelf niet)."""
    stil, sent_stil = _run_main(monkeypatch, tmp_path / "a", capsys, "none")
    luid, sent_luid = _run_main(monkeypatch, tmp_path / "b", capsys, "high")
    assert sent_stil == [] and len(sent_luid) == 1
    assert stil == luid
    assert "high" not in luid and "verzonden" not in luid
