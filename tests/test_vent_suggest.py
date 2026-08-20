"""Tests voor het avond-koelplan (Project 14: `vent_suggest.py` + `cooldown_notify.py`).

Zuivere-functie-tests op een mini-huis (grammatica, filterlaag, score, zendpoort,
berichttekst) plus één contract-test op het échte house_model.json — de grammatica is
gecureerd, dus de concrete scenario-verzameling voor dít huis is een afspraak die niet
stilletjes mag verschuiven."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import vent_io as vio
import vent_suggest as vs
from shared_const import TZ

NOW = datetime(2026, 7, 2, 21, 15, tzinfo=TZ)

HOUSE = {
    "rooms": {
        "nursery": {"from_window_data": "Nursery", "label": "Nursery"},
        "living": {"from_window_data": "Living room", "label": "Woonkamer"},
        "stair": {},
    },
    "windows": {
        "nursery_small_window": {"room": "nursery", "max_open_area_m2": 0.16, "tilt_frac": 0.25,
                             "advice": {"naam": "het kinderkamerraampje", "rain_ok": False}},
        "nursery_window": {"room": "nursery", "max_open_area_m2": 0.0},        # vast glas
        "living_french": {"room": "living", "max_open_area_m2": 1.5, "tilt_frac": 0.2,
                          "advice": {"naam": "tuindeuren", "night_ok": False}},
        "kitchen_door": {"room": "living", "max_open_area_m2": 1.4,
                         "advice": {"naam": "keukendeur", "night_ok": False,
                                    "rain_ok": True}},
        "stair_skylight": {"room": "stair", "max_open_area_m2": 0.025, "tilt_frac": 1.0,
                           "advice": {"naam": "daklicht", "rain_ok": False,
                                      "tilt_ok": False}},
    },
    "doors": {
        "nursery_stair": {"area_m2": 1.8, "advice": {"naam": "deur kinderkamer↔trap"}},
        "hall_stair": {"area_m2": 2.2, "fixed": True},
        "living_hall": {"area_m2": 2.0, "advice": {"naam": "deur woonkamer↔hal"}},
    },
}

BANDS = {"nursery": (17.0, 18.0), "living": (19.5, 22.0)}


def _series(rid_temps: dict, n: int = 44) -> dict:
    """Vlakke kwartier-series per kamer van NOW tot ruim voorbij 07:00 morgen."""
    return {rid: [(NOW + timedelta(minutes=15 * i), t) for i in range(n)]
            for rid, t in rid_temps.items()}


# ── grammatica ─────────────────────────────────────────────────────────────────────────

def test_grammatica_slaat_vast_glas_en_vaste_deuren_over():
    scen = vs.scenario_set(HOUSE)
    ids = {s["id"] for s in scen}
    alle_states = [s["states"] for s in scen if not s["ceiling"]]
    assert not any("nursery_window" in st for st in alle_states)      # vast glas nooit
    assert not any("hall_stair" in st for st in alle_states)      # open doorgang geen actie
    assert "stapel:nursery" in ids and "solo:nursery_small_window" in ids
    stapel = next(s for s in scen if s["id"] == "stapel:nursery")
    assert stapel["states"] == {"nursery_small_window": "open", "nursery_stair": "open",
                                "stair_skylight": "open"}
    plafond = [s for s in scen if s["ceiling"]]
    assert len(plafond) == 1 and plafond[0]["id"] == "alles_open"


def test_grammatica_op_het_echte_huis_is_een_contract():
    """De gecureerde verzameling voor dít huis: verschuift die, dan hoort dat een
    bewuste wijziging te zijn — niet bijvangst van een geometrie-edit."""
    house = vio.load_house()
    ids = sorted(s["id"] for s in vs.scenario_set(house))
    assert ids == ["alles_open", "dwars:living",
                   "solo:bedroom_window", "solo:kitchen_door", "solo:kitchen_top_tilt",
                   "solo:living_french", "solo:nursery_small_window", "solo:office_window",
                   "stapel:bedroom", "stapel:huis", "stapel:living", "stapel:nursery",
                   "stapel:office"]


# ── praktische filterlaag ─────────────────────────────────────────────────────────────

def test_filter_regen_kiept_en_laat_het_daklicht_vallen():
    scen = [{"id": "stapel:nursery", "ceiling": False,
             "states": {"nursery_small_window": "open", "nursery_stair": "open",
                        "stair_skylight": "open"}}]
    out = vs.practical_filter(scen, HOUSE, wet=True, gusty=False)
    assert len(out) == 1
    st = out[0]["states"]
    assert st["nursery_small_window"] == "tilt"        # rain_ok False + kiepbaar → kiep
    assert "stair_skylight" not in st              # tilt_ok False → vervalt
    assert st["nursery_stair"] == "open"               # deur is binnenshuis, geen restrictie
    assert out[0]["beperkt"] is True


def test_filter_nacht_veiligheid_en_dedup():
    """'s Nachts nooit een vol open buitendeur: tuindeuren kieppen, de keukendeur (geen
    kiepstand) vervalt — waarna dwars:living samenvalt met solo:living_french en er
    één overblijft. Een scenario zonder enig open raam vervalt helemaal."""
    scen = vs.scenario_set(HOUSE)
    out = vs.practical_filter(scen, HOUSE, wet=False, gusty=False)
    ids = [s["id"] for s in out]
    assert "solo:kitchen_door" not in ids
    solo_fr = next(s for s in out if s["id"] == "solo:living_french")
    assert solo_fr["states"]["living_french"] == "tilt"
    assert "dwars:living" not in ids               # reduceert tot dezelfde standen → dedup
    plafond = next(s for s in out if s["ceiling"])
    assert plafond["states"]["kitchen_door"] == "open"   # plafond nooit gesnoeid


def test_filter_vlagen_kiept_klapramen():
    scen = [{"id": "solo:nursery_small_window", "ceiling": False,
             "states": {"nursery_small_window": "open"}}]
    out = vs.practical_filter(scen, HOUSE, wet=False, gusty=True)
    assert out[0]["states"]["nursery_small_window"] == "tilt"


# ── score ─────────────────────────────────────────────────────────────────────────────

def test_score_negeert_kamers_die_al_koel_zijn():
    base = _series({"nursery": 17.5, "living": 25.0})       # nursery binnen de band
    scen = _series({"nursery": 16.0, "living": 23.0})
    res = vs.score_plan(base, scen, BANDS, NOW, n_actions=2)
    assert res["rooms"]["nursery"]["needs"] is False
    assert res["rooms"]["nursery"]["benefit"] == 0.0
    assert res["rooms"]["living"]["benefit"] == pytest.approx(2.0)


def test_score_klemt_het_voordeel_op_comfort_low():
    """Koelen tot ónder de band telt niet mee: van 23° naar 15° is maar 3.5° waard
    (tot living's low 19.5), niet 8."""
    base = _series({"living": 23.0})
    scen = _series({"living": 15.0})
    res = vs.score_plan(base, scen, {"living": BANDS["living"]}, NOW, n_actions=1)
    assert res["rooms"]["living"]["benefit"] == pytest.approx(23.0 - 19.5)
    assert res["rooms"]["living"]["overcool_ch"] > 0    # en de onderkoeling telt als straf


def test_score_onderkoeling_kan_een_plan_de_kop_kosten():
    base = _series({"nursery": 19.0})
    scen = _series({"nursery": 14.0})                        # 2.5° onder nursery's low − 0.5
    res = vs.score_plan(base, scen, {"nursery": BANDS["nursery"]}, NOW, n_actions=1)
    assert res["score"] < 0                              # straf > geklemd voordeel


def test_score_actiekost_breekt_de_gelijke_stand():
    base = _series({"living": 23.0})
    scen = _series({"living": 21.0})
    klein = vs.score_plan(base, scen, {"living": BANDS["living"]}, NOW, n_actions=1)
    groot = vs.score_plan(base, scen, {"living": BANDS["living"]}, NOW, n_actions=6)
    assert klein["benefit"] == groot["benefit"]
    assert klein["score"] > groot["score"]


# ── zendpoort ─────────────────────────────────────────────────────────────────────────

def _plan(score=1.5, needs=True, benefit=1.5):
    return {"id": "x", "states": {}, "score": score, "benefit": benefit, "overcool": 0.0,
            "rooms": {"nursery": {"b07": 22.0, "s07": 20.5, "needs": needs,
                              "benefit": benefit, "overcool_ch": 0.0}}}


def test_zendpoort_seizoen_koelte_en_ondergrens():
    assert vs.should_send(NOW, [_plan()]) is True
    winter = NOW.replace(month=1)
    assert vs.should_send(winter, [_plan()]) is False           # buiten het seizoen
    assert vs.should_send(NOW, []) is False                     # niets scoorbaars
    assert vs.should_send(NOW, [_plan(needs=False)]) is False   # geen kamer te warm
    assert vs.should_send(NOW, [_plan(score=0.4)]) is False     # onder DELTA_MIN_C


# ── bericht ───────────────────────────────────────────────────────────────────────────

def test_bericht_noemt_acties_kamers_plafond_en_regen():
    best = {"id": "stapel:nursery", "score": 1.4, "benefit": 1.5, "overcool": 0.0,
            "states": {"nursery_small_window": "open", "nursery_stair": "open"},
            "rooms": {"nursery": {"b07": 22.0, "s07": 20.5, "needs": True, "benefit": 1.5,
                              "overcool_ch": 0.0},
                      "living": {"b07": 25.0, "s07": 25.0, "needs": True, "benefit": 0.0,
                                 "overcool_ch": 0.0}}}
    ceiling = {"id": "alles_open", "ceiling": True, "benefit": 3.2, "score": 3.0,
               "overcool": 0.0, "states": {}, "rooms": {}}
    msg = vs.build_message(NOW, [best], ceiling, HOUSE, 14.2, wet=True,
                           band_line="(typisch 19.9–21.1°)")
    assert "het kinderkamerraampje open" in msg and "deur kinderkamer↔trap open" in msg
    assert "20.5°" in msg and "dicht: 22.0°" in msg
    assert "helpt hier niet" in msg                       # living: te warm, plan doet niets
    assert "~1.5° koeler" in msg
    assert "Alles open zou ~3.0°" in msg and "geen advies" in msg
    assert "Regen verwacht" in msg
    assert "typisch 19.9–21.1" in msg
    assert "Buiten koelt naar 14°" in msg


def test_bericht_zwijgt_over_een_zwakke_runner_up():
    best, zwak = _plan(score=1.5), _plan(score=0.3)
    msg = vs.build_message(NOW, [best, zwak], None, HOUSE, None, wet=False)
    assert "Ook goed" not in msg


# ── timeline-helpers ──────────────────────────────────────────────────────────────────

def test_apply_scenario_laat_het_verleden_met_rust():
    tl = [{"t": NOW + timedelta(minutes=15 * i - 60), "states": {"a": "open"}}
          for i in range(8)]
    out = vs.apply_scenario(tl, NOW, {"b": "dicht"})
    for orig, step in zip(tl, out):
        if step["t"] >= NOW:
            assert step["states"]["b"] == "dicht" and step is not orig
        else:
            assert step is orig
    assert "b" not in tl[-1]["states"]                    # origineel niet gemuteerd


def test_hours_until_morning():
    assert vs.hours_until_morning(NOW) == pytest.approx(10.75)


def test_baseline_sluit_alle_ramen_en_de_kinderkamerdeur():
    st = vs.baseline_states(vio.load_house())
    assert st["nursery_small_window"] == "dicht" and st["living_french"] == "dicht"
    assert st["nursery_stair"] == "dicht"
    assert "bedroom_stair" not in st                      # overige deuren volgen de log


def test_workflow_checkout_hoeft_geen_pin_maar_bestaat(assert_checkout_pinned):
    """cooldown-notify.yml commit niets (contents: read) — de pin-regel geldt niet,
    maar de workflow + orchestrator-regel moeten wel bestaan en kloppen."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    wf = (root / ".github" / "workflows" / "cooldown-notify.yml").read_text(encoding="utf-8")
    assert "cooldown_notify.py" in wf
    assert "contents: read" in wf
    orch = (root / ".github" / "workflows" / "orchestrator.yml").read_text(encoding="utf-8")
    assert "dispatch cooldown-notify.yml" in orch
