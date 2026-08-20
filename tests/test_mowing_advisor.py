"""Tests voor de pure groei-/advieslogica van de grasmaai-adviseur (Project 5).

Geen netwerk of state: heat_derate, daily_growth_unit, build_growth_series,
effective_threshold, is_dormant, recommend_length, predict_ready_date.
Asserties tegen de moduleconstanten, niet tegen hardcoded tuningwaarden.
"""

from datetime import date, datetime, timedelta

import pytest

import mowing_advisor as ma
import shared_const
from mowing_advisor import (build_growth_series, build_message,
                            daily_growth_unit, effective_threshold, heat_derate,
                            is_dormant, predict_ready_date, recommend_length)


# ── heat_derate ────────────────────────────────────────────────────────────────

def test_heat_derate_stuksgewijs():
    assert heat_derate(None) == 1.0
    assert heat_derate(ma.HEAT_OPT_C) == 1.0
    assert heat_derate(ma.HEAT_OPT_C - 5) == 1.0
    assert heat_derate(ma.HEAT_MAX_C) == ma.HEAT_FLOOR
    assert heat_derate(ma.HEAT_MAX_C + 5) == ma.HEAT_FLOOR
    midden = (ma.HEAT_OPT_C + ma.HEAT_MAX_C) / 2
    assert heat_derate(midden) == pytest.approx((1.0 + ma.HEAT_FLOOR) / 2)


def test_heat_derate_monotoon_dalend():
    waarden = [heat_derate(t) for t in range(int(ma.HEAT_OPT_C), int(ma.HEAT_MAX_C) + 1)]
    assert waarden == sorted(waarden, reverse=True)


# ── daily_growth_unit ──────────────────────────────────────────────────────────

def test_gu_soil_volgt_lawn_t_met_hittedemping():
    assert daily_growth_unit({"lawn_T": 2.0, "Tmax": ma.HEAT_OPT_C}, "soil") == pytest.approx(2.0)
    assert daily_growth_unit({"lawn_T": 2.0, "Tmax": ma.HEAT_MAX_C}, "soil") == pytest.approx(2.0 * ma.HEAT_FLOOR)
    assert daily_growth_unit({"lawn_T": None}, "soil") == 0.0
    assert daily_growth_unit({"lawn_T": -0.5, "Tmax": 20}, "soil") == 0.0  # nooit negatief


def test_gu_gdd_fallback():
    assert daily_growth_unit({"Tmean": ma.GDD_BASE + 10}, "gdd") == pytest.approx(10.0)
    assert daily_growth_unit({"Tmean": ma.GDD_BASE - 2}, "gdd") == 0.0
    # Geen Tmean → (Tmax+Tmin)/2.
    assert daily_growth_unit({"Tmax": 20.0, "Tmin": 10.0}, "gdd") == pytest.approx(15.0 - ma.GDD_BASE)


# ── zaadpluim-seizoen: hitte-demping vervalt ────────────────────────────────────

def test_bolt_seizoen_schakelt_hittedemping_uit():
    # Hete dag (Tmax ≥ HEAT_MAX_C) in een zaadpluim-maand: zaadpluim-groei loopt
    # door ondanks de hitte → factor 1.0, volledige lawn_T telt mee.
    bolt_maand = next(m for m in ma.BOLT_MONTHS)
    hete_bolt_dag = {"date": f"2026-{bolt_maand:02d}-15", "lawn_T": 4.0, "Tmax": ma.HEAT_MAX_C + 3}
    assert daily_growth_unit(hete_bolt_dag, "soil") == pytest.approx(4.0)
    assert ma.growth_heat_factor(hete_bolt_dag) == 1.0
    assert ma._in_bolt_season(hete_bolt_dag) is True


def test_buiten_bolt_seizoen_blijft_hittedemping():
    # Zelfde hete dag buiten het zaadpluim-seizoen: demping blijft normaal.
    niet_bolt = next(m for m in range(1, 13) if m not in ma.BOLT_MONTHS)
    hete_dag = {"date": f"2026-{niet_bolt:02d}-15", "lawn_T": 4.0, "Tmax": ma.HEAT_MAX_C + 3}
    assert daily_growth_unit(hete_dag, "soil") == pytest.approx(4.0 * ma.HEAT_FLOOR)
    assert ma._in_bolt_season(hete_dag) is False


def test_bolt_seizoen_geen_datum_valt_terug_op_demping():
    # Zonder date-veld is er geen seizoenscontext → demping blijft van kracht.
    assert ma._in_bolt_season({"Tmax": 30}) is False
    assert ma._in_bolt_season({"date": "kapot", "Tmax": 30}) is False


# ── build_growth_series ────────────────────────────────────────────────────────

def _dagen(n, start=date(2026, 6, 1), lawn_t=1.0):
    return [{"date": (start + timedelta(days=i)).isoformat(),
             "lawn_T": lawn_t, "Tmax": 20.0, "forecast": False}
            for i in range(n)]


def test_accumulator_reset_op_maaidag():
    days = _dagen(5)
    maaidag = days[2]["date"]
    mowings = {maaidag: {"length_mm": 40}}
    serie = build_growth_series(days, mowings, "soil", reset_dates={maaidag})
    assert [s["accum"] for s in serie] == [1.0, 2.0, 0.0, 1.0, 2.0]
    assert serie[2]["is_mow"] is True
    assert serie[2]["length_mm"] == 40
    assert serie[3]["is_mow"] is False


# ── effective_threshold (zelfkalibratie) ───────────────────────────────────────

def test_drempel_default_bij_te_weinig_maaibeurten():
    days = _dagen(30)
    mowings = {days[0]["date"]: {"length_mm": 40}}
    assert effective_threshold(mowings, days, "soil") == (ma.READY_GU, False)


def _mows_elke(interval, aantal, days):
    return {days[i * interval]["date"]: {"length_mm": 40}
            for i in range(aantal)}


def test_drempel_leert_mediaan_van_intervallen():
    # gu=1.0/dag, maaibeurt elke 12 dagen → intervaltotalen ≈ 12 → geleerde drempel 12.
    days = _dagen(70)
    mowings = _mows_elke(12, ma.CALIBRATE_MIN_MOWS + 1, days)
    geleerd, gekalibreerd = effective_threshold(mowings, days, "soil")
    assert gekalibreerd is True
    assert geleerd == pytest.approx(12.0)


def test_drempel_clamp():
    lo, hi = ma.CALIBRATE_CLAMP
    # Heel lange intervallen (30 GU) → geklemd op de bovengrens.
    days = _dagen(160)
    mowings = _mows_elke(30, ma.CALIBRATE_MIN_MOWS + 1, days)
    geleerd, gekalibreerd = effective_threshold(mowings, days, "soil")
    assert gekalibreerd is True
    assert geleerd == hi


# ── is_dormant ─────────────────────────────────────────────────────────────────

def test_dormancy_op_7daags_gemiddelde():
    laag = [{"gu": ma.DORMANT_GU_PER_DAY / 2} for _ in range(10)]
    hoog = [{"gu": ma.DORMANT_GU_PER_DAY * 3} for _ in range(10)]
    assert is_dormant(laag, today_idx=9) is True
    assert is_dormant(hoog, today_idx=9) is False
    assert is_dormant([], today_idx=0) is False


# ── recommend_length ───────────────────────────────────────────────────────────

def _weerdagen(tmax, depletion, n=None):
    n = n or ma.LENGTH_WINDOW_DAYS
    return [{"Tmax": tmax, "lawn_depletion": depletion} for _ in range(n)]


def test_hoogte_hitte_op_komst():
    days = _weerdagen(ma.HOT_TMAX_C + 1, 20.0)
    advies = recommend_length(days, 0, date(2026, 6, 15))
    assert advies["length_mm"] == ma.LEN_TALL


def test_hoogte_droogte_op_komst():
    days = _weerdagen(ma.HOT_TMAX_C - 5, ma.DROUGHT_DEPLETION_PCT + 5)
    advies = recommend_length(days, 0, date(2026, 6, 15))
    assert advies["length_mm"] == ma.LEN_TALL


def test_hoogte_koel_vochtig_buiten_bolt_mag_kort():
    days = _weerdagen(ma.COOL_TMAX_C - 1, ma.TIDY_DEPLETION_PCT - 10)
    # September: groeiseizoen, maar geen zaadpluim-seizoen → kort mag.
    assert recommend_length(days, 0, date(2026, 9, 15))["length_mm"] == ma.LEN_SHORT
    # Zelfde weer buiten het groeiseizoen → niet kort.
    assert recommend_length(days, 0, date(2026, 1, 15))["length_mm"] == ma.LEN_MID


def test_hoogte_default_midden():
    days = _weerdagen((ma.COOL_TMAX_C + ma.HOT_TMAX_C) / 2, ma.TIDY_DEPLETION_PCT + 5)
    # Buiten zaadpluim-seizoen om de default (niet de P2-tier) te raken.
    assert recommend_length(days, 0, date(2026, 9, 15))["length_mm"] == ma.LEN_MID


def test_hoogte_zaadpluim_seizoen_blokkeert_kort():
    # Koel/vochtig in mei–juni: zaadpluim-preventie (P2) wint van strak gazon (P3).
    days = _weerdagen(ma.COOL_TMAX_C - 1, ma.TIDY_DEPLETION_PCT - 10)
    assert recommend_length(days, 0, date(2026, 6, 15))["length_mm"] == ma.LEN_MID


def test_hoogte_overgroei_nooit_korter_dan_vorige():
    # Lang gras, koel/vochtig (P3-weer) buiten bolt-seizoen: ⅓-regel (P1b) verbiedt
    # scalperen → minstens de vorige hoogte, en nooit onder de middenstand.
    days = _weerdagen(ma.COOL_TMAX_C - 1, ma.TIDY_DEPLETION_PCT - 10)
    hoog = recommend_length(days, 0, date(2026, 9, 15),
                            overgrown=True, last_length_mm=ma.LEN_TALL)
    assert hoog["length_mm"] == ma.LEN_TALL
    laag_vorige = recommend_length(days, 0, date(2026, 9, 15),
                                   overgrown=True, last_length_mm=ma.LEN_SHORT)
    assert laag_vorige["length_mm"] == ma.LEN_MID


def test_hoogte_hitte_wint_van_overgroei():
    # Stress-hoog (P1a) gaat vóór de anti-scalp-vloer (P1b).
    days = _weerdagen(ma.HOT_TMAX_C + 1, 20.0)
    advies = recommend_length(days, 0, date(2026, 6, 15),
                              overgrown=True, last_length_mm=ma.LEN_SHORT)
    assert advies["length_mm"] == ma.LEN_TALL


# ── predict_ready_date ─────────────────────────────────────────────────────────

def test_predict_ready_date():
    serie = [{"date": f"2026-06-{10 + i:02d}", "accum": float(i)} for i in range(6)]
    assert predict_ready_date(serie, 0, threshold=3.0) == "2026-06-13"
    assert predict_ready_date(serie, 0, threshold=99.0) is None


# ── "bijna maairijp" voorsprong (LEAD_GU) ───────────────────────────────────────

def test_lead_gu_is_zinvolle_voorsprong():
    # Een positieve voorsprong, kleiner dan de drempel zelf, anders heeft het
    # "bijna"-seintje geen betekenis.
    assert 0 < ma.LEAD_GU < ma.READY_GU


def test_soon_bericht_noemt_beste_dag_en_hoogte():
    optimal = {"date": "2026-06-22", "reason": "droog, 21°C",
               "overgrown": False, "is_today": False}
    length = {"length_mm": ma.LEN_MID, "reason": "veilige middenstand"}
    msg = build_message("soon", date(2026, 6, 14), date(2026, 6, 20),
                        {"precip": 0.0, "Tmax": 21.0}, optimal, length, "soil",
                        predicted="2026-06-23")
    assert "bijna maairijp" in msg.lower()
    assert "22 jun" in msg                    # eerstvolgende goede maaidag
    assert f"{ma.LEN_MID}mm" in msg           # hoogte-advies blijft meegestuurd


# ── meldslot (uurlijkse cadans) ────────────────────────────────────────────────
# De workflow draait elk uur, het advies valt één keer per dag (NOTIFY_AT).

def _now(h, m=0):
    return datetime(2026, 6, 1, h, m, tzinfo=shared_const.TZ)


def test_meldslot_dicht_vóór_het_doeluur():
    uur, minuut = ma.NOTIFY_AT
    assert ma.advice_slot_open({}, date(2026, 6, 1), now=_now(uur - 1, minuut)) is False


def test_meldslot_open_op_en_na_het_doeluur():
    uur, minuut = ma.NOTIFY_AT
    today = date(2026, 6, 1)
    assert ma.advice_slot_open({}, today, now=_now(uur, minuut)) is True
    # "Op of ná", niet "om precies": een gemiste run schuift het advies een uur
    # op i.p.v. de dag over te slaan.
    assert ma.advice_slot_open({}, today, now=_now(uur + 3, minuut)) is True


def test_meldslot_maar_één_keer_per_dag():
    """De verversingsruns ná het advies mogen er niets meer uit persen."""
    uur, minuut = ma.NOTIFY_AT
    today = date(2026, 6, 1)
    state = {"last_advice_date": today.isoformat()}
    assert ma.advice_slot_open(state, today, now=_now(uur, minuut)) is False
    assert ma.advice_slot_open(state, today, now=_now(23, 45)) is False
    # Morgen weer open.
    assert ma.advice_slot_open(state, date(2026, 6, 2), now=_now(uur, minuut)) is True


def test_maai_advies_valt_ná_het_bodemadvies():
    """De twee ochtendberichten horen in vaste volgorde binnen te komen."""
    import check_and_notify as cn
    assert ma.NOTIFY_AT > cn.NOTIFY_AT


# ── series-velden die de grafiek haar vlakke stukken laten uitleggen ───────────

def test_partial_dag_wordt_gemarkeerd():
    """`partial_factor` < 1 = de dag is nog niet om; de punt is geen volle dag."""
    days = _dagen(3)
    days[2]["partial_factor"] = 0.004   # ochtendrun: nog vrijwel niets verdampt
    days[2]["lawn_T"] = 0.01
    serie = build_growth_series(days, {}, "soil", reset_dates=set())
    assert [s["partial"] for s in serie] == [False, False, True]
    # De vlakke stap is echt: de groei-eenheid van die dag is bijna nul.
    assert serie[2]["gu"] < 0.05


def test_uitputting_reist_mee_de_serie_in():
    days = _dagen(2)
    days[0]["lawn_depletion"] = 12.34
    serie = build_growth_series(days, {}, "soil", reset_dates=set())
    assert serie[0]["depletion"] == 12.3
    assert serie[1]["depletion"] is None   # ontbrekend veld → geen verzonnen 0


# ── workflow-contract (uurlijkse cadans) ──────────────────────────────────────

def _workflow(name):
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"
            / name).read_text(encoding="utf-8")


def test_checkout_gepind_op_de_branch_tip(assert_checkout_pinned):
    """Maaien leest de data.json die de bodem-run een paar minuten eerder
    committe; op `github.sha` zou het de vorige kunnen pakken."""
    assert_checkout_pinned("mowing-notify.yml")
    assert_checkout_pinned("daily-check.yml")


def test_fallback_guard_kijkt_vanaf_het_meldmoment():
    """Niet vanaf middernacht: met de uurlijkse cadans staan de nachtruns er
    altijd al, dus een middernacht-venster zou de fallback áltijd skippen."""
    for wf, (uur, minuut) in (("daily-check.yml", __import__("check_and_notify").NOTIFY_AT),
                              ("mowing-notify.yml", ma.NOTIFY_AT)):
        tekst = _workflow(wf)
        assert f'date -d "today {uur:02d}:{minuut:02d}"' in tekst, wf
        assert 'date -d "today 00:00"' not in tekst, wf


def test_orchestrator_dispatcht_bodem_en_maaien_per_uur():
    """Het dedup-venster is het lopende klokuur, en maaien wacht op de
    geslaagde bodem-run van dát uur (het leest zijn data.json)."""
    tekst = _workflow("orchestrator.yml")
    assert "hour_start=$(( now_epoch - now_epoch % 3600 ))" in tekst
    assert 'handled_since daily-check.yml "$hour_start"' in tekst
    assert 'soil_success_since "$hour_start"' in tekst
    assert 'handled_since mowing-notify.yml "$hour_start"' in tekst


def test_data_commits_starten_geen_ci():
    """24 verversingen per dag mogen niet 24× de pytest-suite starten."""
    for wf in ("daily-check.yml", "mowing-notify.yml"):
        for regel in _workflow(wf).splitlines():
            if "git commit -m" in regel:
                assert "[skip ci]" in regel, f"{wf}: {regel.strip()}"


# ── Terugkeer-por na de stille modus ──────────────────────────────────────────────────

def _nu(dag: int, uur: int = 6, minuut: int = 15) -> datetime:
    return datetime(2026, 8, dag, uur, minuut, tzinfo=shared_const.TZ)


def test_return_nudge_vuurt_op_eerste_slot_na_uitzetten():
    # Stil uitgezet gisteravond 21:00; laatste (as-if-sent) stempel eergisteren.
    prefs = {"quiet": False, "cleared_at": "2026-08-14T19:00:00.000Z"}
    assert ma.return_nudge_due(prefs, True, "2026-08-13",
                               date(2026, 8, 15), _nu(15)) is True


def test_return_nudge_zelfde_dag_uitgezet_vuurt_volgende_ochtend():
    # Uitgezet om 15:00; de stempel van die ochtend (06:15, as-if-sent) ligt vóór
    # cleared_at → de volgende ochtend vuurt de por alsnog.
    prefs = {"quiet": False, "cleared_at": "2026-08-15T13:00:00.000Z"}
    assert ma.return_nudge_due(prefs, True, "2026-08-15",
                               date(2026, 8, 15), _nu(15, 16)) is False  # zelfde dag: niet
    assert ma.return_nudge_due(prefs, True, "2026-08-15",
                               date(2026, 8, 16), _nu(16)) is True       # ochtend erna: wel


def test_return_nudge_hervuurt_niet_na_stempel():
    # Na het vuren stempelt de gewone verzendweg last_notified_date = vandaag →
    # today > last is False → geen tweede por.
    prefs = {"quiet": False, "cleared_at": "2026-08-14T19:00:00.000Z"}
    assert ma.return_nudge_due(prefs, True, "2026-08-15",
                               date(2026, 8, 15), _nu(15, 7)) is False


def test_return_nudge_niet_bij_actieve_stilte_of_koude_start():
    prefs_stil = {"quiet": True, "cleared_at": "2026-08-14T19:00:00.000Z"}
    assert ma.return_nudge_due(prefs_stil, True, "2026-08-13",
                               date(2026, 8, 15), _nu(15)) is False
    prefs = {"quiet": False, "cleared_at": "2026-08-14T19:00:00.000Z"}
    assert ma.return_nudge_due(prefs, True, None, date(2026, 8, 15), _nu(15)) is False
    assert ma.return_nudge_due({}, True, "2026-08-13", date(2026, 8, 15), _nu(15)) is False


def test_return_nudge_venster_verloopt_en_eist_maairijp():
    oud = {"quiet": False, "cleared_at": "2026-08-10T19:00:00.000Z"}   # > 48u geleden
    assert ma.return_nudge_due(oud, True, "2026-08-09",
                               date(2026, 8, 15), _nu(15)) is False
    vers = {"quiet": False, "cleared_at": "2026-08-14T19:00:00.000Z"}
    assert ma.return_nudge_due(vers, False, "2026-08-13",
                               date(2026, 8, 15), _nu(15)) is False    # niet maairijp
