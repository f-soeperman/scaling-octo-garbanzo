"""Tests voor gardena_control.py — beslisvensters, sessie-machine, opentijd-
meter, registratieregels en de privacy-invarianten (vormvaste logs, geen
verboden vocabulaire, sensor-shard-whitelist)."""

import json
import pathlib
import re
from datetime import datetime, timedelta, timezone

import pytest

import gardena_control as gc

REPO = pathlib.Path(__file__).resolve().parent.parent


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def local(*args):
    return datetime(*args, tzinfo=gc.TZ)


def _soil(priority="high", proposal=30, tmin=12.0, age=0.5):
    st = {"priority": priority, "proposal_min": proposal}
    return {"age_h": age, "tmin": tmin,
            "status": {"lawn": dict(st), "shrubs": dict(st)}}


CLOSED = {"activity": "CLOSED"}
OPEN_V = {"activity": "MANUAL_WATERING"}


def _state(**kw):
    return {**gc.ensure_state(None), **kw}


# ── Beslisvensters + slot-semantiek ──────────────────────────────────────────

def test_gras_start_op_eerste_run_in_venster():
    now = local(2026, 8, 14, 5, 10)
    got = gc.decide_zone("lawn", now, _state(), {"auto_lawn": True}, _soil(),
                         CLOSED, None)
    assert got == ("start", 30)


def test_gras_venster_grenzen():
    flags = {"auto_lawn": True}
    assert gc.decide_zone("lawn", local(2026, 8, 14, 4, 50), _state(), flags,
                          _soil(), CLOSED, None) is None
    assert gc.decide_zone("lawn", local(2026, 8, 14, 9, 5), _state(), flags,
                          _soil(), CLOSED, None) is None


def test_gras_nee_is_een_beslissing():
    now = local(2026, 8, 14, 5, 10)
    assert gc.decide_zone("lawn", now, _state(), {"auto_lawn": False},
                          _soil(), CLOSED, None) == ("no", "automaat uit")
    assert gc.decide_zone("lawn", now, _state(), {"auto_lawn": True},
                          _soil(priority="low"), CLOSED, None) \
        == ("no", "bodem vochtig genoeg")
    assert gc.decide_zone("lawn", now, _state(), {"auto_lawn": True, "paused": True},
                          _soil(), CLOSED, None) == ("no", "gepauzeerd")


def test_defer_bij_bezette_kraan_oude_data_of_sessie():
    now = local(2026, 8, 14, 5, 10)
    flags = {"auto_lawn": True}
    # Een openstaande kraan (speelbadje!) wordt nooit gekaapt.
    assert gc.decide_zone("lawn", now, _state(), flags, _soil(), OPEN_V, None) \
        == ("defer", "kraan niet dicht")
    assert gc.decide_zone("lawn", now, _state(), flags, _soil(age=7.0),
                          CLOSED, None) == ("defer", "bodemdata veroudert")
    assert gc.decide_zone("lawn", now, _state(), flags, None, CLOSED, None) \
        == ("defer", "bodemdata veroudert")
    assert gc.decide_zone("lawn", now, _state(), flags, _soil(), CLOSED,
                          {"zone": "shrubs"}) == ("defer", "sessie actief")


def test_slot_al_verbruikt_vandaag():
    now = local(2026, 8, 14, 6, 10)
    state = _state(day={"lawn": "2026-08-14"})
    assert gc.decide_zone("lawn", now, state, {"auto_lawn": True}, _soil(),
                          CLOSED, None) is None


def test_struiken_venster_en_geen_herbeslissing_na_middernacht():
    assert gc.decide_zone("shrubs", local(2026, 8, 14, 22, 10), _state(), {},
                          _soil(proposal=60), CLOSED, None) == ("start", 60)
    # Ná middernacht is het venster vanzelf dicht — de chunker van een lopende
    # nachtsessie kan dus nooit een tweede beslissing uitlokken.
    assert gc.decide_zone("shrubs", local(2026, 8, 15, 0, 30), _state(), {},
                          _soil(proposal=60), CLOSED, None) is None


def test_plan_minutes_kapt_op_de_eerstvolgende_0500():
    # 23:30 → 05:00 is 330 min; een diepe aanvulling spreidt over nachten.
    assert gc.plan_minutes("shrubs", 400, local(2026, 8, 13, 23, 30)) == 330
    # DST-nachten: klok terug (25 okt 2026) → 8 echte uren, vooruit
    # (28 mrt 2027) → 6 echte uren.
    assert gc.minutes_until_local(5, local(2026, 10, 24, 22, 0)) == 480
    assert gc.minutes_until_local(5, local(2027, 3, 27, 22, 0)) == 360
    assert gc.plan_minutes("lawn", 120, local(2026, 8, 14, 5, 0)) == gc.LAWN_MAX_MIN


def test_vorstgrens_en_weeklimiet():
    now = local(2026, 8, 14, 22, 10)
    assert gc.decide_zone("shrubs", now, _state(), {}, _soil(tmin=0.5),
                          CLOSED, None) == ("no", "vorstgrens")
    state = _state(recent={"shrubs": [{"date": "2026-08-13", "mm": 39.0}]})
    got = gc.decide_zone("shrubs", now, state, {}, _soil(proposal=60),
                         CLOSED, None)
    assert got == ("no", "weeklimiet")  # 39 + 2.0 > 40


def test_weekly_mm_telt_alleen_de_lopende_week():
    recent = [{"date": "2026-08-14", "mm": 10.0},
              {"date": "2026-08-08", "mm": 5.0},   # dag 6 terug → telt mee
              {"date": "2026-08-07", "mm": 99.0}]  # dag 7 terug → niet
    assert gc.weekly_mm(recent, local(2026, 8, 14, 12).date()) == 15.0


# ── Opentijd-meter ───────────────────────────────────────────────────────────

def _iso(dt):
    return dt.isoformat()


def test_meter_init_en_exact_interval():
    now = utc(2026, 8, 14, 12, 0)
    entry, done = gc.meter_step(None, False, utc(2026, 8, 13, 9, 0), None, now)
    assert entry["open"] is False and done == []

    t0 = utc(2026, 8, 14, 10, 12)
    prev = {"open": True, "since": _iso(t0), "cmd_s": 3600, "ts": _iso(t0),
            "checked": _iso(utc(2026, 8, 14, 11, 0))}
    tc = utc(2026, 8, 14, 11, 12)
    entry, done = gc.meter_step(prev, False, tc, None, now)
    assert entry["open"] is False
    assert done == [(t0, tc)]


def test_meter_heroverride_sluit_naadloos_aan():
    # Onze eigen chunk-verlenging ververst de activity-ts vóór het verlopen:
    # het oude interval sluit exact op het her-override-moment → som blijft
    # continu, geen dubbeltelling en geen gat.
    now = utc(2026, 8, 14, 23, 5)
    t0 = utc(2026, 8, 14, 22, 0)
    t1 = utc(2026, 8, 14, 23, 0)
    prev = {"open": True, "since": _iso(t0), "cmd_s": 5400, "ts": _iso(t0),
            "checked": _iso(utc(2026, 8, 14, 22, 5))}
    entry, done = gc.meter_step(prev, True, t1, 5400, now)
    assert done == [(t0, t1)]
    assert entry["open"] is True and gc.parse_ts(entry["since"]) == t1


def test_meter_verlopen_en_heropend_binnen_het_gat():
    # Chunk verliep (autoclose) en de kraan ging later opnieuw open: het oude
    # interval sluit op de gecommandeerde eindtijd, niet op het heropen-moment.
    now = utc(2026, 8, 14, 14, 0)
    t0 = utc(2026, 8, 14, 11, 0)
    reopen = utc(2026, 8, 14, 13, 30)
    prev = {"open": True, "since": _iso(t0), "cmd_s": 3600, "ts": _iso(t0),
            "checked": _iso(utc(2026, 8, 14, 13, 0))}
    entry, done = gc.meter_step(prev, True, reopen, 1800, now)
    assert done == [(t0, utc(2026, 8, 14, 12, 0))]
    assert gc.parse_ts(entry["since"]) == reopen


def test_meter_volledig_gemiste_beurt_krijgt_halve_venster_schatting():
    now = utc(2026, 8, 14, 12, 0)
    c1 = utc(2026, 8, 14, 11, 0)
    close = utc(2026, 8, 14, 11, 40)
    prev = {"open": False, "since": None, "cmd_s": None,
            "ts": _iso(utc(2026, 8, 14, 9, 0)), "checked": _iso(c1)}
    entry, done = gc.meter_step(prev, False, close, None, now)
    assert len(done) == 1
    start, end = done[0]
    assert end == close
    assert start == c1 + (close - c1) / 2  # helft van het mogelijke venster


def test_meter_onzin_timestamp_valt_terug_op_commando_eindtijd_of_ondertelling():
    now = utc(2026, 8, 14, 12, 0)
    t0 = utc(2026, 8, 14, 10, 0)
    prev = {"open": True, "since": _iso(t0), "cmd_s": 3600, "ts": _iso(t0),
            "checked": _iso(utc(2026, 8, 14, 11, 0))}
    # Geen bruikbare sluit-ts → de gecommandeerde eindtijd (10:00 + 1u).
    entry, done = gc.meter_step(prev, False, None, None, now)
    assert done == [(t0, utc(2026, 8, 14, 11, 0))]
    # Ook geen commando-duur → de vorige check (bewuste ondertelling).
    prev = {"open": True, "since": _iso(t0), "cmd_s": None, "ts": _iso(t0),
            "checked": _iso(utc(2026, 8, 14, 11, 0))}
    entry, done = gc.meter_step(prev, False, utc(2026, 9, 1, 0, 0), None, now)
    assert done == [(t0, utc(2026, 8, 14, 11, 0))]


# ── Registratie + irrigations-merge ──────────────────────────────────────────

def test_registratieregels_kraan1_alleen_met_automaat_aan():
    start, end = utc(2026, 8, 14, 3, 10), utc(2026, 8, 14, 3, 40)
    # Speelbadje: automaat uit → kraan 1 volledig genegeerd.
    assert gc.register_intervals("lawn", [(start, end)], auto_lawn=False) == []
    got = gc.register_intervals("lawn", [(start, end)], auto_lawn=True)
    assert got[0]["min"] == 30 and got[0]["mm"] == 10.0
    assert got[0]["date"] == "2026-08-14"
    # Druppelslang: altijd registreren, ook zonder vlag.
    got = gc.register_intervals("shrubs", [(start, end)], auto_lawn=False)
    assert got[0]["mm"] == 1.0
    # Mini-intervallen (< 1 min) zijn ruis.
    assert gc.register_intervals("shrubs", [(start, start + timedelta(seconds=30))],
                                 auto_lawn=False) == []


def test_merge_irrigation_is_browser_compatibel():
    irr = {"2026-08-14_shrubs": 2.0,
           "_meta": {"2026-08-14": {"minLawn": 0, "mmLawn": 0,
                                    "minShrubs": 60, "mmShrubs": 2.0}}}
    gc.merge_irrigation(irr, "shrubs", {"date": "2026-08-14", "min": 120, "mm": 4.0})
    # Additief, en exact de sleutelvorm die soil_model.py opzoekt.
    assert irr.get("2026-08-14_shrubs", irr.get("2026-08-14", 0)) == 6.0
    meta = irr["_meta"]["2026-08-14"]
    assert meta["minShrubs"] == 180 and meta["mmShrubs"] == 6.0
    assert meta["minLawn"] == 0 and meta["mmLawn"] == 0
    # Nieuwe datum zonder bestaande meta.
    gc.merge_irrigation(irr, "lawn", {"date": "2026-08-15", "min": 34, "mm": 11.3})
    assert irr["2026-08-15_lawn"] == 11.3
    assert irr["_meta"]["2026-08-15"]["minLawn"] == 34


# ── Sessie-machine ───────────────────────────────────────────────────────────

def _session(now, *, started=-60, target=300, chunk=30, zone="shrubs",
             planned_min=360):
    return {"zone": zone, "date": now.astimezone(gc.TZ).date().isoformat(),
            "started_utc": _iso(now + timedelta(minutes=started)),
            "target_end_utc": _iso(now + timedelta(minutes=target)),
            "chunk_end_utc": _iso(now + timedelta(minutes=chunk)),
            "planned_min": planned_min,
            "planned_mm": round(planned_min * gc.RATES[zone], 1),
            "chunks": 1, "forced": False}


def test_sessie_chunk_verlenging_voor_het_verlopen():
    now = utc(2026, 8, 14, 23, 0)
    action, end, s2 = gc.advance_session(_session(now), True, False, now, False)
    assert action == ("start", gc.MAX_CMD_SECONDS)  # 5u resterend → cap 5400
    assert end is None and s2["chunks"] == 2
    assert gc.parse_ts(s2["chunk_end_utc"]) == now + timedelta(seconds=gc.MAX_CMD_SECONDS)


def test_sessie_laatste_chunk_geen_overbodig_commando():
    now = utc(2026, 8, 14, 4, 0)
    session = _session(now, target=30, chunk=30)
    action, end, s2 = gc.advance_session(session, True, False, now, False)
    assert action is None and end is None and s2 == session


def test_sessie_normale_voltooiing_en_gemiste_run():
    now = utc(2026, 8, 14, 5, 10)
    done = _session(now, target=-5, chunk=-5)
    action, end, s2 = gc.advance_session(done, False, False, now, False)
    assert (action, s2) == (None, None) and end["reason"] == "voltooid"
    missed = _session(now, target=60, chunk=-120)
    action, end, s2 = gc.advance_session(missed, False, False, now, False)
    assert end["reason"] == "eerder afgesloten (run gemist)" and s2 is None


def test_sessie_externe_stop_via_de_app():
    now = utc(2026, 8, 14, 23, 30)
    action, end, s2 = gc.advance_session(_session(now, chunk=40), False, False,
                                         now, False)
    assert action is None and end["reason"] == "eerder gestopt (via de app)"


def test_sessie_stuck_open_stuurt_stop_en_alert():
    now = utc(2026, 8, 15, 5, 10)
    stuck = _session(now, target=-5, chunk=-5)
    action, end, s2 = gc.advance_session(stuck, True, False, now, False)
    assert action == ("stop",) and end["alert"] == "stuck_open" and s2 is None


def test_sessie_pauze_en_app_schema():
    now = utc(2026, 8, 14, 23, 0)
    action, end, _ = gc.advance_session(_session(now), True, False, now, True)
    assert action == ("stop",) and end["reason"] == "gepauzeerd"
    action, end, _ = gc.advance_session(_session(now), True, True, now, False)
    assert action is None and end["alert"] == "schedule_active"


def test_new_session_getallen():
    now = utc(2026, 8, 13, 20, 10)
    session, chunk_s = gc.new_session("shrubs", 400, now)
    assert chunk_s == gc.MAX_CMD_SECONDS
    assert session["planned_mm"] == 13.3
    assert gc.parse_ts(session["target_end_utc"]) == now + timedelta(minutes=400)
    session, chunk_s = gc.new_session("lawn", 34, now)
    assert chunk_s == 34 * 60 and session["planned_mm"] == 11.3


# ── Sensor-shards ────────────────────────────────────────────────────────────

@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "HISTORY_DIR", str(tmp_path))
    return tmp_path


def _row(t="2026-08-14T04:30:00+00:00", hum=31):
    return {"t": t, "soil_hum": hum, "soil_temp": 18.4, "amb_temp": None,
            "battery": 92, "battery_state": "OK", "rf": "ONLINE"}


def test_shard_idempotent_op_sensor_timestamp(archive):
    assert gc.append_sensor_rows([_row()]) == (1, 0)
    assert gc.append_sensor_rows([_row()]) == (0, 0)
    assert gc.append_sensor_rows([_row(hum=33)]) == (0, 1)
    shard = json.loads((archive / "2026-08.json").read_text())
    assert len(shard["rows"]) == 1 and shard["rows"][0]["soil_hum"] == 33
    gc.append_sensor_rows([_row(t="2026-08-14T03:30:00+00:00")])
    shard = json.loads((archive / "2026-08.json").read_text())
    assert [r["t"] for r in shard["rows"]] == sorted(r["t"] for r in shard["rows"])


def test_shard_whitelist_alleen_sensorvelden(archive):
    # Privacy-whitelist: nooit kraandata, ids of vlagstanden in het publieke
    # archief — alleen t + de sensorvelden.
    gc.append_sensor_rows([{**_row(), "kraan": "x", "extra": 1}])
    shard = json.loads((archive / "2026-08.json").read_text())
    assert set(shard["rows"][0]) == {"t", *gc.SENSOR_FIELDS}


def test_sensor_row_whitelist():
    snap = {"sensors": {"sens": {"soil_hum": 31, "soil_hum_ts": "2026-08-14T04:30:00Z",
                                 "soil_temp": 18.4, "soil_temp_ts": None,
                                 "amb_temp": None, "device": "d"}},
            "common": {"d": {"battery": 92, "battery_state": "OK", "rf": "ONLINE"}},
            "valves": {}}
    row = gc.sensor_row(snap, {"sensor_id": "sens"})
    assert set(row) == {"t", *gc.SENSOR_FIELDS}
    assert gc.sensor_row(snap, {"sensor_id": "anders"}) is None


# ── Hoofdflow-scenario's (main() met fakes) ──────────────────────────────────

def _snap(lawn="CLOSED", shrubs="CLOSED", lawn_ts=None, shrubs_ts=None,
          lawn_dur=None, shrubs_dur=None):
    def v(act, ts, dur):
        return {"activity": act, "activity_ts": ts, "duration_s": dur,
                "device": "d1", "state": "OK", "name": None}
    return {"valves": {"v-lawn": v(lawn, lawn_ts, lawn_dur),
                       "v-shrubs": v(shrubs, shrubs_ts, shrubs_dur)},
            "sensors": {}, "common": {}}


def run_main(monkeypatch, capsys, *, now, flags=None, state=None, snapshot=None,
             soil=None, irrigations=None, dry=False, force_zone=None):
    calls = {"commands": [], "telegram": [], "persisted": []}
    for var, val in (("GARDENA_APP_KEY", "k"), ("GARDENA_APP_SECRET", "s"),
                     ("GIST_ID", "g"), ("GH_TOKEN", "t")):
        monkeypatch.setenv(var, val)
    if dry:
        monkeypatch.setenv("DRY_RUN", "1")
    else:
        monkeypatch.delenv("DRY_RUN", raising=False)
    if force_zone:
        monkeypatch.setenv("FORCE_ZONE", force_zone)
    else:
        monkeypatch.delenv("FORCE_ZONE", raising=False)
    monkeypatch.delenv("FORCE_MINUTES", raising=False)

    fixed = now

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed

    monkeypatch.setattr(gc, "datetime", FakeDT)

    config = {"schema": 1, "location_id": "loc",
              "valves": {"lawn": "v-lawn", "shrubs": "v-shrubs"},
              "sensor_id": "sens"}
    files = {gc.CONFIG_FILE: config, gc.FLAGS_FILE: flags or {},
             gc.STATE_FILE: state, gc.IRRIGATIONS_FILE: irrigations or {}}
    monkeypatch.setattr(gc, "read_gist_files",
                        lambda names: {n: files.get(n) for n in names})
    monkeypatch.setattr(gc, "persist_files",
                        lambda f: calls["persisted"].append(f) or True)
    monkeypatch.setattr(gc, "send_telegram",
                        lambda text, **kw: calls["telegram"].append(text) or True)
    monkeypatch.setattr(gc, "load_soil_data", lambda now, path=None: soil)
    monkeypatch.setattr(gc, "append_sensor_rows", lambda rows: (0, 0))
    monkeypatch.setattr(gc.ga, "mint_token", lambda k, s: "tok")
    monkeypatch.setattr(gc.ga, "fetch_location", lambda t, k, loc: {"doc": True})
    monkeypatch.setattr(gc.ga, "parse_snapshot",
                        lambda doc: snapshot if snapshot is not None else _snap())
    monkeypatch.setattr(gc.ga, "start_valve",
                        lambda t, k, sid, sec: calls["commands"].append(("start", sid, sec)))
    monkeypatch.setattr(gc.ga, "stop_valve",
                        lambda t, k, sid: calls["commands"].append(("stop", sid)))
    gc.main()
    calls["stdout"] = capsys.readouterr().out
    return calls


def test_logs_identiek_bij_wateren_en_stilte(monkeypatch, capsys):
    # DE privacy-invariant: de publieke Actions-log van een run die een
    # sproeisessie start is byte-identiek aan die van een stille middag-run.
    quiet = run_main(monkeypatch, capsys, now=local(2026, 8, 14, 12, 0),
                     soil=_soil(proposal=60))
    assert quiet["commands"] == [] and quiet["telegram"] == []
    watering = run_main(monkeypatch, capsys, now=local(2026, 8, 14, 22, 10),
                        soil=_soil(proposal=60))
    assert ("start", "v-shrubs", 3600) in watering["commands"]
    assert any("gestart" in t for t in watering["telegram"])
    assert watering["stdout"] == quiet["stdout"]
    # En de log bevat sowieso niets inhoudelijks.
    for woord in ("sessie", "mm", "kraan", "sproeier", "lawn", "shrubs"):
        assert woord not in quiet["stdout"]


def test_start_verbruikt_dagslot_en_schrijft_state(monkeypatch, capsys):
    got = run_main(monkeypatch, capsys, now=local(2026, 8, 14, 22, 10),
                   soil=_soil(proposal=60))
    persisted = got["persisted"][-1]
    state = json.loads(persisted[gc.STATE_FILE])
    assert state["day"]["shrubs"] == "2026-08-14"
    assert state["session"]["zone"] == "shrubs"
    assert state["next"]["lawn"]["reason"] == "automaat uit"


def test_rustige_beslissing_verbruikt_dagslot_zonder_bericht(monkeypatch, capsys):
    got = run_main(monkeypatch, capsys, now=local(2026, 8, 14, 22, 10),
                   soil=_soil(priority="low"))
    assert got["commands"] == [] and got["telegram"] == []
    state = json.loads(got["persisted"][-1][gc.STATE_FILE])
    assert state["day"]["shrubs"] == "2026-08-14"


def test_handmatige_druppelbeurt_wordt_geregistreerd(monkeypatch, capsys):
    # Kraan 2 open→dicht zonder eigen sessie (via de app): registratie in
    # irrigations.json + stil "Geregistreerd"-bericht.
    now = local(2026, 8, 14, 14, 0)
    t0 = now.astimezone(timezone.utc) - timedelta(hours=6)
    tc = now.astimezone(timezone.utc) - timedelta(minutes=30)
    state = _state(meter={"shrubs": {"open": True, "since": _iso(t0),
                                     "cmd_s": 21600, "ts": _iso(t0),
                                     "checked": _iso(now - timedelta(hours=1))}})
    got = run_main(monkeypatch, capsys, now=now, state=state,
                   snapshot=_snap(shrubs="CLOSED", shrubs_ts=_iso(tc)),
                   soil=_soil(priority="low"),
                   irrigations={"2026-08-14_shrubs": 1.0})
    assert any("Geregistreerd" in t and "druppelslang" in t for t in got["telegram"])
    irr = json.loads(got["persisted"][-1][gc.IRRIGATIONS_FILE])
    # 5,5 uur → 330 min → 11,0 mm, additief bovenop de bestaande 1,0.
    assert irr["2026-08-14_shrubs"] == 12.0
    assert irr["_meta"]["2026-08-14"]["minShrubs"] == 330
    state_out = json.loads(got["persisted"][-1][gc.STATE_FILE])
    assert state_out["recent"]["shrubs"] == [{"date": "2026-08-14", "mm": 11.0}]


def test_speelbadje_kraan1_blijft_onzichtbaar(monkeypatch, capsys):
    # Zelfde open→dicht op kraan 1 met de automaat uit: geen registratie,
    # geen bericht — het systeem weet van niets.
    now = local(2026, 8, 14, 14, 0)
    t0 = now.astimezone(timezone.utc) - timedelta(hours=2)
    tc = now.astimezone(timezone.utc) - timedelta(minutes=30)

    def make_state():  # main() muteert de state — per run een verse kopie
        return _state(meter={"lawn": {"open": True, "since": _iso(t0),
                                      "cmd_s": 7200, "ts": _iso(t0),
                                      "checked": _iso(now - timedelta(hours=1))}})

    got = run_main(monkeypatch, capsys, now=now, state=make_state(),
                   snapshot=_snap(lawn="CLOSED", lawn_ts=_iso(tc)),
                   soil=_soil(priority="low"))
    assert got["telegram"] == []
    assert gc.IRRIGATIONS_FILE not in got["persisted"][-1]
    # Met de automaat áán telt dezelfde opening wél mee (bewonersregel).
    got = run_main(monkeypatch, capsys, now=now, state=make_state(),
                   flags={"auto_lawn": True},
                   snapshot=_snap(lawn="CLOSED", lawn_ts=_iso(tc)),
                   soil=_soil(priority="low"))
    assert gc.IRRIGATIONS_FILE in got["persisted"][-1]


def test_zero_delivery_alert(monkeypatch, capsys):
    # START geaccepteerd maar de kraan is nooit opengegaan: chunk verlopen,
    # meter zag niets → alert i.p.v. een normaal klaar-bericht.
    now = local(2026, 8, 14, 6, 30)
    old_ts = _iso(now.astimezone(timezone.utc) - timedelta(days=1))
    state = _state(
        session={"zone": "lawn", "date": "2026-08-14",
                 "started_utc": _iso(now - timedelta(minutes=50)),
                 "target_end_utc": _iso(now - timedelta(minutes=15)),
                 "chunk_end_utc": _iso(now - timedelta(minutes=15)),
                 "planned_min": 35, "planned_mm": 11.7, "chunks": 1,
                 "forced": False},
        day={"lawn": "2026-08-14"},
        meter={"lawn": {"open": False, "since": None, "cmd_s": None,
                        "ts": old_ts, "checked": _iso(now - timedelta(hours=1))}})
    got = run_main(monkeypatch, capsys, now=now, state=state,
                   flags={"auto_lawn": True},
                   snapshot=_snap(lawn="CLOSED", lawn_ts=old_ts),
                   soil=_soil(priority="low"))
    assert any("lijkt niet te zijn opengegaan" in t for t in got["telegram"])
    state_out = json.loads(got["persisted"][-1][gc.STATE_FILE])
    assert state_out["session"] is None


def test_dry_run_stuurt_geen_commandos_en_schrijft_niets(monkeypatch, capsys):
    got = run_main(monkeypatch, capsys, now=local(2026, 8, 14, 22, 10),
                   soil=_soil(proposal=60), dry=True)
    assert got["commands"] == [] and got["persisted"] == []
    assert len(got["telegram"]) == 1
    assert "Testrun" in got["telegram"][0] and "gestart" in got["telegram"][0]


def test_ontbrekende_secrets_geen_http_en_exit_0(monkeypatch, capsys):
    for var in ("GARDENA_APP_KEY", "GARDENA_APP_SECRET", "GIST_ID",
                "GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(var, raising=False)

    def boom(*a, **k):
        raise AssertionError("geen HTTP verwacht")

    for mod in (gc.requests, gc.ga.requests):
        for meth in ("get", "post", "put", "patch"):
            monkeypatch.setattr(mod, meth, boom)
    gc.main()  # geen exceptie = exit 0 via run_guarded
    assert "configuratie onvolledig" in capsys.readouterr().out


def test_ontbrekende_gist_config_is_nette_no_op(monkeypatch, capsys):
    # Secrets bestaan al wél, maar de bootstrap draaide nog niet: nette no-op
    # zonder ook maar één GARDENA-API-call (dormant-fase na de merge).
    monkeypatch.setattr(gc.ga, "mint_token",
                        lambda *a: pytest.fail("mag de API niet aanraken"))
    for var, val in (("GARDENA_APP_KEY", "k"), ("GARDENA_APP_SECRET", "s"),
                     ("GIST_ID", "g"), ("GH_TOKEN", "t")):
        monkeypatch.setenv(var, val)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(gc, "read_gist_files",
                        lambda names: {n: None for n in names})
    gc.main()
    assert "configuratie onvolledig" in capsys.readouterr().out


# ── Workflow + orchestrator + vocabulaire ────────────────────────────────────

def test_workflow_vorm(assert_checkout_pinned):
    assert_checkout_pinned("gardena-control.yml")
    wf = (REPO / ".github" / "workflows" / "gardena-control.yml").read_text()
    assert "pull_request" not in wf
    assert "timezone: 'Europe/Amsterdam'" in wf
    assert "group: gardena-control" in wf
    assert "cancel-in-progress: false" in wf
    assert "contents: write" in wf
    # Bewust géén in-job herkansing (API-budget) — afwijking van daily-check.
    assert "sleep 600" not in wf
    assert "git add data/gardena_history" in wf
    assert "git add docs" not in wf


def test_orchestrator_dispatcht_elk_uur():
    orch = (REPO / ".github" / "workflows" / "orchestrator.yml").read_text()
    assert 'handled_since gardena-control.yml "$hour_start"' in orch
    assert "dispatch gardena-control.yml" in orch


def test_geen_verboden_vocabulaire():
    # De reden achter de gazon-automaat-vlag is privé (bewonersbesluit): de
    # code, de workflow, het paneel en het CLAUDE.md-hoofdstuk beschrijven
    # alleen wát er schakelt, nooit waaróm. (De patroon-string is opgeknipt
    # zodat deze test zichzelf niet matcht.)
    pattern = re.compile("|".join(("vaka" "ntie", "holi" "day")), re.IGNORECASE)
    for rel in ("gardena_control.py", "gardena_api.py",
                "tools/gardena_bootstrap.py",
                ".github/workflows/gardena-control.yml",
                "docs/js/index.js", "docs/index.html",
                "tests/test_gardena_control.py", "tests/test_gardena_api.py"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert not pattern.search(text), rel
    claude = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    sectie = claude.split("## Project 16")[1].split("\n## ")[0]
    assert not pattern.search(sectie)
