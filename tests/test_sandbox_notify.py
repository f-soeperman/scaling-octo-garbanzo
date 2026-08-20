"""Tests voor sandbox_notify — de open/dicht/afgedekt-toestandsmachine.

De ochtend- en avondlogica zijn pure functies (state + forecast in, bericht +
nieuwe state uit) en worden hier zonder netwerk of Telegram doorgetest.
"""

import json
import sys

import sandbox_notify
from sandbox_notify import (evening_check, first_dry_day, is_rain_expected,
                            morning_check)


def _day(date="2026-07-01", prob=0, mm=0.0, tmin=10.0, tmax=20.0):
    return {"date": date, "precip_prob_max": prob, "precip_mm": mm,
            "tmin": tmin, "tmax": tmax}


def _state(status):
    return {"status": status, "last_updated": None}


# ── is_rain_expected / first_dry_day ─────────────────────────────────────────

def test_regen_verwacht_op_kans_of_mm():
    assert is_rain_expected(_day(prob=30))          # drempel: >= 30%
    assert is_rain_expected(_day(mm=1.0))           # drempel: >= 1.0 mm
    assert not is_rain_expected(_day(prob=29, mm=0.9))


def test_first_dry_day_slaat_vandaag_over():
    fc = [_day("2026-07-01", prob=80), _day("2026-07-02", prob=80),
          _day("2026-07-03", prob=5)]
    assert first_dry_day(fc) == "2026-07-03"
    assert first_dry_day([_day(prob=80)] * 3) is None


# ── Ochtendlogica ────────────────────────────────────────────────────────────

def test_ochtend_open_en_droog_geen_bericht():
    msg, state = morning_check(_state("open"), [_day()])
    assert msg is None and state["status"] == "open"


def test_ochtend_afgedekt_en_regen_geen_bericht():
    msg, state = morning_check(_state("afgedekt"), [_day(prob=80, mm=4.0)])
    assert msg is None and state["status"] == "afgedekt"


def test_ochtend_dicht_droog_warm_wordt_open():
    msg, state = morning_check(_state("dicht"), [_day(tmax=18.0)])
    assert msg is not None and "gelucht" in msg
    assert state["status"] == "open"


def test_ochtend_afgedekt_droog_warm_wordt_open():
    msg, state = morning_check(_state("afgedekt"), [_day(tmax=18.0)])
    assert msg is not None and "Dekzeil eraf" in msg
    assert state["status"] == "open"


def test_ochtend_open_met_regen_waarschuwt_zonder_statewissel():
    msg, state = morning_check(_state("open"), [_day(prob=80, mm=5.0)])
    assert msg is not None and "Afdekken" in msg
    assert state["status"] == "open"


def test_ochtend_dicht_met_regen_waarschuwt():
    msg, state = morning_check(_state("dicht"), [_day(prob=80, mm=5.0)])
    assert msg is not None and "niet afgedekt" in msg
    assert state["status"] == "dicht"


def test_ochtend_afgedekt_droog_maar_koud_geen_bericht():
    msg, state = morning_check(_state("afgedekt"), [_day(tmax=4.0)])
    assert msg is None and state["status"] == "afgedekt"


# ── Avondlogica ──────────────────────────────────────────────────────────────

def test_avond_open_regen_morgen_wordt_afgedekt():
    fc = [_day("2026-07-01"), _day("2026-07-02", prob=80, mm=6.0)]
    msg, state = evening_check(_state("open"), fc)
    assert msg is not None and "afdekken" in msg.lower()
    assert state["status"] == "afgedekt"


def test_avond_open_droog_morgen_wordt_dicht():
    fc = [_day("2026-07-01"), _day("2026-07-02")]
    msg, state = evening_check(_state("open"), fc)
    assert msg is not None and "sluiten" in msg.lower()
    assert state["status"] == "dicht"


def test_avond_dicht_regen_morgen_wordt_afgedekt():
    fc = [_day("2026-07-01"), _day("2026-07-02", prob=80, mm=6.0)]
    msg, state = evening_check(_state("dicht"), fc)
    assert msg is not None and state["status"] == "afgedekt"


def test_avond_dicht_droog_morgen_geen_bericht():
    fc = [_day("2026-07-01"), _day("2026-07-02")]
    msg, state = evening_check(_state("dicht"), fc)
    assert msg is None and state["status"] == "dicht"


def test_avond_afgedekt_regen_nabij_geen_bericht():
    # Regen pas overmorgen telt ook als "nabij" → afgedekt laten.
    fc = [_day("2026-07-01"), _day("2026-07-02"),
          _day("2026-07-03", prob=90, mm=8.0)]
    msg, state = evening_check(_state("afgedekt"), fc)
    assert msg is None and state["status"] == "afgedekt"


def test_avond_afgedekt_droog_kondigt_aan_zonder_statewissel():
    # State blijft afgedekt — de ochtendrun zet 'm pas op open.
    fc = [_day("2026-07-01"), _day("2026-07-02"), _day("2026-07-03")]
    msg, state = evening_check(_state("afgedekt"), fc)
    assert msg is not None and "morgenochtend" in msg
    assert state["status"] == "afgedekt"


def test_avond_beperkte_forecast_krijgt_waarschuwing():
    msg, state = evening_check(_state("open"), [_day("2026-07-01")])
    assert msg is not None and msg.startswith("⚠️")
    assert state["status"] == "dicht"


def test_avond_onbekende_status_geen_actie():
    msg, state = evening_check(_state("garbage"), [_day(), _day("2026-07-02")])
    assert msg is None and state["status"] == "garbage"


# ── main: lege forecast-guard ────────────────────────────────────────────────

def test_main_lege_forecast_laat_state_ongemoeid(monkeypatch, tmp_path):
    state_file = tmp_path / "sandbox_state.json"
    monkeypatch.setattr(sandbox_notify, "STATE_FILE", str(state_file))
    monkeypatch.setattr(sandbox_notify, "fetch_forecast", lambda: [])
    monkeypatch.setattr(sandbox_notify.sys, "argv", ["sandbox_notify.py", "morning"])
    sent = []
    monkeypatch.setattr(sandbox_notify, "send_telegram", lambda *a, **k: sent.append(a))
    sandbox_notify.main()
    assert not sent
    assert not state_file.exists()  # state niet weggeschreven/aangeraakt


# ── Vormvaste stdout (privacy) ────────────────────────────────────────────────

def _run_main(monkeypatch, capsys, tmp_path, status, forecast):
    """Draai main() met alle randen gemockt; geef (verzonden berichten, stdout)."""
    sent = []
    state_file = tmp_path / f"state_{status}.json"
    state_file.write_text(json.dumps({"status": status, "last_updated": None}))
    monkeypatch.setattr(sandbox_notify, "STATE_FILE", str(state_file))
    monkeypatch.setattr(sandbox_notify, "fetch_forecast", lambda: forecast)
    monkeypatch.setattr(sandbox_notify, "send_telegram",
                        lambda text, **kw: sent.append(text) or True)
    monkeypatch.setattr(sandbox_notify, "utc_now_iso",
                        lambda: "2026-08-19T06:00:00+00:00")
    monkeypatch.setattr(sys, "argv", ["sandbox_notify.py", "morning"])
    monkeypatch.delenv("DRY_RUN", raising=False)
    sandbox_notify.main()
    return sent, capsys.readouterr().out


def test_logs_identiek_bij_bericht_en_stilte(monkeypatch, capsys, tmp_path):
    """DE privacy-invariant (het gardena_control-patroon, sinds aug 2026 ook
    hier): de publieke Actions-log van een run die een bericht stuurt is
    byte-identiek aan die van een stille run, en codeert nooit een status,
    beslissing of berichtinhoud. Vóór deze regel printte elke run de status en
    de gekozen tak — een dagritme-spoor in een publiek log."""
    droog = [_day(tmax=20.0)]
    sent_stil, out_stil = _run_main(monkeypatch, capsys, tmp_path, "open", droog)
    assert sent_stil == []
    sent_bericht, out_bericht = _run_main(monkeypatch, capsys, tmp_path, "dicht", droog)
    assert len(sent_bericht) == 1 and "gelucht" in sent_bericht[0]
    assert out_bericht == out_stil
    for woord in ("open", "dicht", "afgedekt", "status=", "regen", "bericht"):
        assert woord not in out_stil


def test_dry_run_toont_alles_maar_schrijft_niets(monkeypatch, capsys, tmp_path):
    """DRY_RUN=1 (handmatige dispatch) is het enige pad dat berichttekst en
    beslissing print — en het mag de gecommitte state-machine niet verzetten."""
    sent = []
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"status": "dicht", "last_updated": None}))
    monkeypatch.setattr(sandbox_notify, "STATE_FILE", str(state_file))
    monkeypatch.setattr(sandbox_notify, "fetch_forecast", lambda: [_day(tmax=20.0)])
    monkeypatch.setattr(sandbox_notify, "send_telegram",
                        lambda text, **kw: sent.append(text) or True)
    monkeypatch.setattr(sys, "argv", ["sandbox_notify.py", "morning"])
    monkeypatch.setenv("DRY_RUN", "1")
    sandbox_notify.main()
    out = capsys.readouterr().out
    assert sent == []
    assert "gelucht" in out and "DRY_RUN=1" in out
    assert json.loads(state_file.read_text())["status"] == "dicht"  # onaangeroerd


def test_state_migreert_last_notification_weg(tmp_path, monkeypatch):
    """Bestaande state met het gedateerde meldspoor-veld verliest het bij de
    eerstvolgende load (privacy-assessment aug 2026)."""
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"status": "open", "last_updated": None,
                                      "last_notification": "2026-08-16T18:00:00+00:00"}))
    monkeypatch.setattr(sandbox_notify, "STATE_FILE", str(state_file))
    assert "last_notification" not in sandbox_notify.load_state()


def test_workflow_checkout_gepind(assert_checkout_pinned):
    # De dedup poort op het gecommitte sandbox_state.json — dezelfde
    # momentopname-klasse als shade-notify (dubbel bericht, 2 aug 2026).
    assert_checkout_pinned("sandbox-notify.yml")
