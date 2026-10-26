"""Tests voor heating_experiment_notify — de wekelijkse nachtsetpoint-arm + het logboek.

Alles wat ertoe doet is puur (datum in, arm/venster/logboek uit), dus de hele
alternatie is zonder Telegram of netwerk door te rekenen. De twee eigenschappen
die het experiment maken-of-breken staan bovenaan: strikte alternatie (anders
correleert de arm met het seizoen i.p.v. met de instelling) en het laten
vallen van de eerste dag na de omschakeling.
"""

import json
from datetime import date, timedelta

import pytest

import heating_experiment_notify as hx
from heating_experiment_notify import (analysis_window, arm_for_week, build_message,
                                       load_state, main, monday_of, previous_arm,
                                       record_week, save_state, week_entry, week_label)

MON = date(2026, 11, 2)  # een maandag


# ── Armkeuze ─────────────────────────────────────────────────────────────────

def test_arm_is_constant_binnen_de_week():
    armen = {arm_for_week(MON + timedelta(days=i)) for i in range(7)}
    assert len(armen) == 1


def test_arm_alterneert_strikt_over_twee_jaar():
    """Nooit twee gelijke armen achter elkaar — ook niet op de jaargrens.

    Dít is de hele reden voor wekelijks alterneren: als twee opeenvolgende
    weken dezelfde arm draaien schuift het experiment richting blokken, en dan
    meet je seizoen i.p.v. instelling. Een pariteit op het ISO-weeknummer zou
    hier struikelen over een jaar met 53 weken.
    """
    reeks = [arm_for_week(MON + timedelta(weeks=w)) for w in range(104)]
    assert all(a != b for a, b in zip(reeks, reeks[1:]))
    # en beide armen komen even vaak voor
    assert reeks.count("afkoelen") == reeks.count("warm") == 52


def test_arm_hangt_niet_af_van_de_state():
    """Een gemiste maandag verschuift de alternatie niet.

    De armkeuze is datum-afgeleid, dus een overgeslagen week (uitgevallen
    orchestrator, zomerstop) laat de weken erna gewoon op hun plek staan.
    """
    assert arm_for_week(MON) == arm_for_week(MON + timedelta(weeks=2))
    assert arm_for_week(MON) != arm_for_week(MON + timedelta(weeks=1))


def test_monday_of():
    assert monday_of(date(2026, 11, 8)) == MON      # zondag → dezelfde maandag
    assert monday_of(MON) == MON


# ── Meetvenster ──────────────────────────────────────────────────────────────

def test_meetvenster_laat_de_dinsdag_vallen():
    """Omschakeling maandagavond → dinsdagochtend valt af, woensdag telt.

    Met tau ~ 23 u settelt het huis pas ~65% in de eerste 24 u; de ochtend
    daarna is dus nog voor een derde de vorige arm.
    """
    start, end = analysis_window(MON)
    assert start == date(2026, 11, 4)               # woensdag
    assert end == date(2026, 11, 9)                 # volgende maandag telt nog mee
    assert start.weekday() == 2 and end.weekday() == 0


def test_week_entry_is_volledig_datum_afgeleid():
    entry = week_entry(MON, "afkoelen")
    assert entry == {
        "week": "2026-W45",
        "experiment": "night_setpoint",
        "arm": "afkoelen",
        "night_setpoint": 16.0,
        "switched_at": "2026-11-02",
        "analyse_from": "2026-11-04",
        "analyse_through": "2026-11-09",
    }
    assert week_label(MON) == "2026-W45"


# ── Logboek ──────────────────────────────────────────────────────────────────

def test_record_week_upsert_geen_dubbele_regels():
    """Een tweede dispatch in dezelfde week overschrijft, stapelt niet."""
    state = {"experiment": "night_setpoint", "weeks": []}
    state = record_week(state, week_entry(MON, "afkoelen"))
    state = record_week(state, week_entry(MON, "afkoelen"))
    state = record_week(state, week_entry(MON + timedelta(weeks=1), "warm"))
    assert [w["week"] for w in state["weeks"]] == ["2026-W45", "2026-W46"]


def test_record_week_sorteert_en_kapt_af(monkeypatch):
    monkeypatch.setattr(hx, "MAX_WEEKS", 3)
    state = {"weeks": []}
    for w in range(5):
        mon = MON + timedelta(weeks=w)
        state = record_week(state, week_entry(mon, arm_for_week(mon)))
    assert [w["week"] for w in state["weeks"]] == ["2026-W47", "2026-W48", "2026-W49"]


def test_load_state_op_ontbrekend_bestand(tmp_path, monkeypatch):
    monkeypatch.setenv("HEATING_STATE_FILE", str(tmp_path / "nog-niets.json"))
    assert load_state() == {"experiment": "night_setpoint", "weeks": []}


def test_save_en_load_rondrit(tmp_path, monkeypatch):
    monkeypatch.setenv("HEATING_STATE_FILE", str(tmp_path / "state.json"))
    save_state(record_week(load_state(), week_entry(MON, "afkoelen")))
    state = load_state()
    assert state["weeks"][0]["arm"] == "afkoelen"
    assert state["last_updated"]


# ── Bericht ──────────────────────────────────────────────────────────────────

def test_bericht_noemt_arm_setpoint_en_meetvenster():
    msg = build_message(MON, "afkoelen", "warm")
    assert "2026-W45" in msg
    assert "laten afkoelen" in msg and "16 °C" in msg   # deze week
    assert "warm houden (19 °C)" in msg                 # vorige week
    assert "woensdag 4 nov" in msg and "maandag 9 nov" in msg
    assert "dinsdag 3 nov" in msg                       # de dag die afvalt


def test_early_start_staat_in_beide_armen_aan():
    """Alleen het nachtsetpoint wisselt; early start is geen tweede factor.

    Zou early start per arm verschillen, dan valt een gasverschil niet meer
    aan het setpoint toe te schrijven.
    """
    for arm in hx.ARMS:
        msg = build_message(MON, arm, None)
        assert "Early start (voorverwarmen) blijft in béíde weken aan" in msg


def test_armen_verschillen_alleen_in_setpoint():
    assert hx.ARMS["afkoelen"]["setpoint"] == 16.0
    assert hx.ARMS["warm"]["setpoint"] > hx.ARMS["afkoelen"]["setpoint"]


def test_bericht_verzint_geen_vorige_week_bij_koude_start():
    """Zonder logboekregel voor vorige week geen bewering over vorige week."""
    msg = build_message(MON, "afkoelen", None)
    assert "Vorige week" not in msg
    assert "Eerste week van het experiment" in msg


def test_previous_arm_leest_uit_het_logboek():
    state = record_week({"weeks": []}, week_entry(MON - timedelta(weeks=1), "warm"))
    assert previous_arm(state, MON) == "warm"
    assert previous_arm(state, MON + timedelta(weeks=1)) is None   # gat in het log


# ── main() ───────────────────────────────────────────────────────────────────

def _run_main(monkeypatch, tmp_path, today, **env):
    sent = []
    monkeypatch.setattr(hx, "local_today", lambda: today)
    monkeypatch.setattr(hx, "send_telegram", lambda msg, **kw: sent.append(msg) or True)
    monkeypatch.setenv("HEATING_STATE_FILE", str(tmp_path / "state.json"))
    for k in ("DRY_RUN", "FORCE_SEND"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    main()
    path = tmp_path / "state.json"
    return sent, (json.loads(path.read_text()) if path.exists() else None)


def test_main_verstuurt_en_registreert(monkeypatch, tmp_path):
    sent, state = _run_main(monkeypatch, tmp_path, MON)
    assert len(sent) == 1 and "2026-W45" in sent[0]
    assert state["weeks"][0]["arm"] == arm_for_week(MON)


def test_main_zwijgt_buiten_het_stookseizoen(monkeypatch, tmp_path):
    sent, state = _run_main(monkeypatch, tmp_path, date(2027, 8, 2))
    assert sent == [] and state is None


def test_main_force_send_negeert_het_seizoen(monkeypatch, tmp_path):
    sent, _ = _run_main(monkeypatch, tmp_path, date(2027, 8, 2), FORCE_SEND="1")
    assert len(sent) == 1


def test_dry_run_stuurt_niets_en_vervuilt_het_logboek_niet(monkeypatch, tmp_path):
    """Een testdispatch mag geen weekregel achterlaten — de armkeuze is toch
    datum-afgeleid, dus er valt niets te bewaren."""
    sent, state = _run_main(monkeypatch, tmp_path, MON, DRY_RUN="1")
    assert sent == [] and state is None


# ── Overgang vanaf het ochtend-opstookexperiment ─────────────────────────────

OUD_LOG = {
    "experiment": "morning_recovery",
    "weeks": [
        {"week": "2026-W43", "arm": "hard", "switched_at": "2026-10-19",
         "analyse_from": "2026-10-21", "analyse_through": "2026-10-26"},
        {"week": "2026-W44", "arm": "early", "switched_at": "2026-10-26",
         "analyse_from": "2026-10-28", "analyse_through": "2026-11-02"},
    ],
}


def test_eerste_maandag_is_de_start():
    assert hx.EXPERIMENT_START.weekday() == 0
    assert arm_for_week(hx.EXPERIMENT_START) == "afkoelen"


def test_oude_weken_blijven_staan_en_houden_hun_experiment(tmp_path, monkeypatch):
    """De oude weekregels zijn de enige historie van het vorige experiment.

    Ze krijgen bij het laden hun eigen experiment-tag, vóórdat de kop van het
    bestand naar het nieuwe experiment omgaat — anders lezen ze daarna als
    nachtsetpoint-weken.
    """
    path = tmp_path / "state.json"
    path.write_text(json.dumps(OUD_LOG))
    monkeypatch.setenv("HEATING_STATE_FILE", str(path))
    state = record_week(load_state(), week_entry(MON, "afkoelen"))
    save_state(state)
    weeks = load_state()["weeks"]
    assert [(w["week"], w["experiment"]) for w in weeks] == [
        ("2026-W43", "morning_recovery"),
        ("2026-W44", "morning_recovery"),
        ("2026-W45", "night_setpoint"),
    ]


def test_eerste_week_noemt_geen_ochtend_arm_als_vorige(tmp_path, monkeypatch):
    """W44 draaide `early` — dat is geen arm van dít experiment (en geen sleutel
    in ARMS), dus het eerste bericht zegt "eerste week"."""
    path = tmp_path / "state.json"
    path.write_text(json.dumps(OUD_LOG))
    monkeypatch.setenv("HEATING_STATE_FILE", str(path))
    assert previous_arm(load_state(), MON) is None


def test_dispatch_vóór_de_start_overschrijft_de_oude_week_niet(monkeypatch, tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(OUD_LOG))
    monkeypatch.setattr(hx, "local_today", lambda: date(2026, 10, 27))
    monkeypatch.setattr(hx, "send_telegram", lambda msg, **kw: pytest.fail("verstuurd"))
    monkeypatch.setenv("HEATING_STATE_FILE", str(path))
    monkeypatch.setenv("FORCE_SEND", "1")
    main()
    assert json.loads(path.read_text()) == OUD_LOG
