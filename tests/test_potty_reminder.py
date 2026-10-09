"""Tests voor de potje-herinnering (Project 17)."""

import json
import os
import re
from datetime import datetime, timedelta

import pytest

import potty_reminder as pr
from shared_const import TZ

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def at(h, m=0, day=2):
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


def ev(dt, where="potje", kind="plas", id_=None):
    return {"id": id_ or f"e{dt:%d%H%M}{where}{kind}", "t": dt.isoformat(),
            "kind": kind, "where": where}


def events(*evs):
    return pr.parse_events({"events": list(evs)})


# ── Beslissing ───────────────────────────────────────────────────────────────

def test_herinnering_90_min_na_een_plasje():
    es = events(ev(at(10, 0)))
    assert pr.decide(es, {}, at(11, 25)) is None
    d = pr.decide(es, {}, at(11, 30))
    assert d and d["kind"] == "plas"


def test_zelf_aangegeven_veld_verandert_de_herinnering_niet():
    """Het dashboard zet `self: true` op een registratie (okt 2026); dat is
    alleen analyse-informatie en moet het anker en het interval laten staan."""
    e = ev(at(10, 0))
    e["self"] = True
    d = pr.decide(events(e), {}, at(11, 30))
    assert d and d["kind"] == "plas"
    assert pr.decide(events(e), {}, at(11, 25)) is None


@pytest.mark.parametrize("where", ["wc", "potje", "ongeluk"])
def test_elk_echt_plasje_zet_de_klok(where):
    d = pr.decide(events(ev(at(10, 0), where)), {}, at(11, 30))
    assert d and d["kind"] == "plas"


def test_poging_geeft_herinnering_na_30_min():
    es = events(ev(at(10, 0)), ev(at(10, 40), "geprobeerd"))
    assert pr.decide(es, {}, at(11, 5)) is None
    d = pr.decide(es, {}, at(11, 10))
    assert d and d["kind"] == "poging"


def test_poep_telt_niet_mee():
    es = events(ev(at(10, 0)), ev(at(11, 0), kind="poep"))
    d = pr.decide(es, {}, at(11, 30))
    assert d and d["anchor"]["kind"] == "plas"


def test_één_herhaling_dan_stil():
    es = events(ev(at(10, 0)))
    s = pr.record_reminder({}, pr.decide(es, {}, at(11, 30)), at(11, 30))
    assert pr.decide(es, s, at(11, 30)) is None          # niet dubbel
    assert pr.decide(es, s, at(11, 55)) is None
    d = pr.decide(es, s, at(12, 0))
    assert d and d["kind"] == "herhaal"
    s = pr.record_reminder(s, d, at(12, 0))
    assert pr.decide(es, s, at(12, 30)) is None
    assert pr.decide(es, s, at(14, 0)) is None


def test_nieuwe_registratie_reset_de_herinneringen():
    es = events(ev(at(10, 0)))
    s = pr.record_reminder({}, pr.decide(es, {}, at(11, 30)), at(11, 30))
    es = events(ev(at(10, 0)), ev(at(11, 40), "wc"))
    assert pr.decide(es, s, at(12, 0)) is None
    d = pr.decide(es, s, at(13, 10))
    assert d and d["kind"] == "plas"


def test_geen_herinnering_na_19_uur():
    es = events(ev(at(17, 45)))
    assert pr.decide(es, {}, at(19, 15)) is None


def test_ochtend_pas_na_de_eerste_registratie():
    # Laatste plasje gisteravond → vanochtend niets.
    es = events(ev(at(18, 30, day=1)))
    assert pr.decide(es, {}, at(7, 0)) is None
    assert pr.decide(es, {}, at(9, 0)) is None


def test_vroege_registratie_herinnert_om_zeven_uur():
    es = events(ev(at(5, 15)))   # moment 06:45 valt in de nacht → om 07:00
    assert pr.decide(es, {}, at(6, 55)) is None          # slaapt nog
    d = pr.decide(es, {}, at(7, 0))
    assert d and d["kind"] == "plas"


def test_te_late_herinnering_vervalt():
    es = events(ev(at(10, 0)))
    assert pr.decide(es, {}, at(12, 31)) is None


def test_toekomstige_registratie_is_geen_anker():
    es = events(ev(at(10, 0)), ev(at(13, 0), "wc"))
    d = pr.decide(es, {}, at(11, 30))
    assert d and d["anchor"]["dt"] == at(10, 0)


def test_kapotte_regels_vallen_weg():
    es = pr.parse_events({"events": [
        {"t": "geen-datum", "kind": "plas", "where": "wc"},
        {"t": at(10).isoformat(), "kind": "plas", "where": "bad"},
        "rommel",
        ev(at(10, 0)),
    ]})
    assert len(es) == 1


def test_dst_herfst_rekent_in_echte_minuten():
    # Op de wisseldag (25 okt 2026) blijft het interval 90 echte minuten.
    anchor = datetime(2026, 10, 25, 9, 0, tzinfo=TZ)
    es = events(ev(anchor))
    d = pr.next_reminder(es, {}, anchor + timedelta(minutes=100))
    assert d["due"] - anchor == timedelta(minutes=90)


def test_bericht_noemt_geen_naam_en_wel_het_tijdstip():
    es = events(ev(at(10, 0), "wc"))
    d = pr.decide(es, {}, at(11, 30))
    msg = pr.build_message(d, {}, at(11, 30))
    assert "10:00" in msg and "90 min" in msg


# ── Runner: vormvaste stdout + volgorde state → bericht ──────────────────────

class FakeGist:
    def __init__(self, files):
        self.files = dict(files)
        self.writes = []

    def read_files(self, gist_id, token=None):
        return dict(self.files)

    def write_files(self, gist_id, files, token=None):
        self.writes.append(files)
        self.files.update(files)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("GIST_ID", "abc")
    monkeypatch.setenv("GIST_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "priv")
    monkeypatch.setenv("TELEGRAM_CHAT_GROUP_ID", "group")
    monkeypatch.delenv("DRY_RUN", raising=False)
    sent = []

    def fake_send(text, **kw):
        print("[telegram] ✓ verzonden")
        sent.append((text, kw))
        return 4242 + len(sent)   # message_id
    monkeypatch.setattr(pr, "send_telegram_message", fake_send)
    return sent


@pytest.fixture
def edits(monkeypatch):
    calls = []

    def fake_edit(chat_id, message_id, text, **kw):
        print("[telegram] bewerkt")   # moet door de redirect weggevangen worden
        calls.append((chat_id, message_id, text))
        return "ok"
    monkeypatch.setattr(pr, "edit_telegram", fake_edit)
    return calls


def _run(monkeypatch, capsys, gist, now):
    monkeypatch.setattr(pr, "gist_io", gist)
    pr.run(now=now)
    return capsys.readouterr().out


def test_stdout_is_gelijk_met_en_zonder_herinnering(env, monkeypatch, capsys):
    log = json.dumps({"events": [ev(at(10, 0))]})
    out_quiet = _run(monkeypatch, capsys, FakeGist({pr.LOG_FILE: log}), at(10, 30))
    gist = FakeGist({pr.LOG_FILE: log})
    out_send = _run(monkeypatch, capsys, gist, at(11, 30))
    assert len(env) == 1, "er had een herinnering moeten uitgaan"
    assert out_quiet == out_send


def test_herinnering_naar_de_groep_en_muted_in_quiet(env, monkeypatch, capsys):
    gist = FakeGist({pr.LOG_FILE: json.dumps({"events": [ev(at(10, 0))]})})
    _run(monkeypatch, capsys, gist, at(11, 30))
    (text, kw), = env
    assert kw["chat_id"] == "group" and kw["muted_in_quiet"] is True
    state = json.loads(gist.files[pr.STATE_FILE])
    assert state["reminders"][-1]["kind"] == "plas"
    # Volgende iteratie: niets dubbel.
    _run(monkeypatch, capsys, gist, at(11, 35))
    assert len(env) == 1


def test_schrijffout_stuurt_geen_herinnering_en_raist_niet(env, monkeypatch, capsys):
    gist = FakeGist({pr.LOG_FILE: json.dumps({"events": [ev(at(10, 0))]})})

    def boom(*a, **k):
        raise RuntimeError("409")
    gist.write_files = boom
    out = _run(monkeypatch, capsys, gist, at(11, 30))
    assert out == "potje: controle klaar\n"
    (text, kw), = env
    assert kw["chat_id"] is None and "state niet opgeslagen" in text


def test_dry_run_schrijft_niets(env, monkeypatch, capsys):
    monkeypatch.setenv("DRY_RUN", "1")
    gist = FakeGist({pr.LOG_FILE: json.dumps({"events": [ev(at(10, 0))]})})
    _run(monkeypatch, capsys, gist, at(11, 30))
    assert gist.writes == []
    (text, kw), = env
    assert text.startswith("[dry-run]") and kw["chat_id"] is None


def test_zonder_gist_een_noop(env, monkeypatch, capsys):
    monkeypatch.delenv("GIST_ID")
    assert _run(monkeypatch, capsys, FakeGist({}), at(11, 30)) == "potje: controle klaar\n"


# ── Afvinken na een registratie ──────────────────────────────────────────────

def test_registratie_na_herinnering_vinkt_het_bericht_af(env, edits, monkeypatch, capsys):
    log = {"events": [ev(at(10, 0))]}
    gist = FakeGist({pr.LOG_FILE: json.dumps(log)})
    _run(monkeypatch, capsys, gist, at(11, 30))
    rem = json.loads(gist.files[pr.STATE_FILE])["reminders"][-1]
    assert rem["msg_id"] == 4243 and "Tijd om te plassen" in rem["text"]

    # Nog niets geregistreerd → geen edit.
    _run(monkeypatch, capsys, gist, at(11, 35))
    assert edits == []

    log["events"].append(ev(at(11, 40), "potje"))
    gist.files[pr.LOG_FILE] = json.dumps(log)
    out = _run(monkeypatch, capsys, gist, at(11, 45))
    (chat, mid, text), = edits
    assert chat == "group" and mid == 4243
    assert text.startswith("✅ 🚽") and "11:40 (op het potje)" in text
    assert out == "potje: controle klaar\n"
    assert len(env) == 1, "afvinken mag geen nieuw bericht opleveren"
    rem = json.loads(gist.files[pr.STATE_FILE])["reminders"][-1]
    assert rem["acked"].startswith("2026-10-02T11:40") and "text" not in rem

    _run(monkeypatch, capsys, gist, at(11, 50))
    assert len(edits) == 1, "niet dubbel afvinken"


def test_poging_vinkt_herinnering_én_herhaling_af():
    es = events(ev(at(10, 0)))
    s = pr.record_reminder({}, pr.decide(es, {}, at(11, 30)), at(11, 30))
    s = pr.attach_message(s, 1, "eerste")
    s = pr.record_reminder(s, pr.decide(es, s, at(12, 0)), at(12, 0))
    s = pr.attach_message(s, 2, "herhaling")
    es = events(ev(at(10, 0)), ev(at(12, 10), "geprobeerd"))
    todo = pr.pending_acks(es, s, at(12, 15))
    assert [i for i, _ in todo] == [0, 1]
    s = pr.mark_acked(s, todo)
    assert pr.pending_acks(es, s, at(12, 20)) == []


def test_poep_of_registratie_van_vóór_de_herinnering_vinkt_niet_af():
    es = events(ev(at(10, 0)))
    s = pr.attach_message(pr.record_reminder({}, pr.decide(es, {}, at(11, 30)), at(11, 30)),
                          1, "x")
    es = events(ev(at(10, 0)), ev(at(11, 40), kind="poep"))
    assert pr.pending_acks(es, s, at(11, 45)) == []


def test_berichten_van_gisteren_worden_niet_meer_afgevinkt():
    es = events(ev(at(10, 0, day=1)))
    s = pr.record_reminder({}, pr.decide(es, {}, at(11, 30, day=1)), at(11, 30, day=1))
    s = pr.attach_message(s, 1, "x")
    es = events(ev(at(10, 0, day=1)), ev(at(8, 0, day=2)))
    assert pr.pending_acks(es, s, at(8, 5, day=2)) == []
    # …en hun tekst valt bij de volgende herinnering uit de state.
    s = pr.record_reminder(s, pr.decide(es, s, at(9, 30, day=2)), at(9, 30, day=2))
    assert "text" not in s["reminders"][0] and s["reminders"][0]["msg_id"] == 1


def test_mislukte_edit_probeert_later_opnieuw(env, monkeypatch, capsys):
    status = ["retry"]
    calls = []
    monkeypatch.setattr(pr, "edit_telegram",
                        lambda *a, **k: calls.append(a) or status[0])
    log = {"events": [ev(at(10, 0)), ev(at(11, 40))]}
    state = pr.attach_message(
        pr.record_reminder({}, pr.decide(events(ev(at(10, 0))), {}, at(11, 30)), at(11, 30)),
        7, "x")
    gist = FakeGist({pr.LOG_FILE: json.dumps(log), pr.STATE_FILE: json.dumps(state)})
    _run(monkeypatch, capsys, gist, at(11, 45))
    assert gist.writes == []
    status[0] = "ok"
    _run(monkeypatch, capsys, gist, at(11, 50))
    assert len(calls) == 2 and "acked" in json.loads(gist.files[pr.STATE_FILE])["reminders"][0]


def test_afvinkfout_raist_niet_en_print_niets(env, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("stuk")
    monkeypatch.setattr(pr, "edit_telegram", boom)
    state = pr.attach_message(
        pr.record_reminder({}, pr.decide(events(ev(at(10, 0))), {}, at(11, 30)), at(11, 30)),
        7, "x")
    gist = FakeGist({pr.LOG_FILE: json.dumps({"events": [ev(at(10, 0)), ev(at(11, 40))]}),
                     pr.STATE_FILE: json.dumps(state)})
    assert _run(monkeypatch, capsys, gist, at(11, 45)) == "potje: controle klaar\n"


# ── Browser en runner rekenen met dezelfde constanten ────────────────────────

@pytest.mark.parametrize("name", ["INTERVAL_PEE_MIN", "INTERVAL_TRY_MIN",
                                  "INTERVAL_REPEAT_MIN", "MAX_REMINDERS_PER_ANCHOR",
                                  "DAY_START_H", "DAY_END_H", "STALE_MIN"])
def test_js_constanten_spiegelen_python(name):
    js = open(os.path.join(_ROOT, "docs", "js", "potje.js"), encoding="utf-8").read()
    m = re.search(rf"\b{name}\s*[:=]\s*(\d+)", js)
    assert m, f"{name} ontbreekt in potje.js"
    assert int(m.group(1)) == getattr(pr, name)


def test_workflow_pint_de_checkout(assert_checkout_pinned):
    assert_checkout_pinned("potty-reminder.yml")


def test_loop_dispatcht_zijn_opvolger():
    """De cron-kicks vallen overdag tot uren weg; de loop zet zelf zijn opvolger klaar.
    Alleen op main en niet bij een dry-run, anders ketent een testdispatch eindeloos."""
    wf = open(os.path.join(_ROOT, ".github", "workflows", "potty-reminder.yml"),
              encoding="utf-8").read()
    assert re.search(r"^  actions: write$", wf, re.M)
    stap = wf[wf.index("- name: Dispatch successor loop"):]
    guard = re.search(r"if: \$\{\{(.*)\}\}", stap).group(1)
    assert "success()" in guard
    assert "!inputs.dry_run" in guard
    assert "github.ref_name == 'main'" in guard
    assert "gh workflow run potty-reminder.yml --ref main" in stap
