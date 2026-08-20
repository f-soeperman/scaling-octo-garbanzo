"""Tests voor camping_forecast.py — zuivere scoringslogica, geen netwerk.

Asserties pinnen op de module-constanten (PEN/CAT_*/MIN_NIGHTS/…), niet op
losse getallen: een bewuste her-tuning verandert dan de test mee, een
onbedoelde regressie niet. Zelfde stijl als test_mowing_advisor.
"""

import json
import pathlib
from datetime import date, datetime, timedelta

import pytest

import camping_forecast as cf
from shared_const import TZ, local_today

D0 = date(2026, 8, 10)


# ── hulpjes ──────────────────────────────────────────────────────────────────

def _reeks(d0=D0, n_uur=72, *, temp=20.0, dew=12.0, rain=0.0, pop=10, gust=15.0):
    """Uurrijen vanaf d0 00:00 lokaal; scalars of functies van het uurindex."""
    basis = datetime(d0.year, d0.month, d0.day, tzinfo=TZ)

    def val(x, h):
        return x(h) if callable(x) else x

    return [{"dt": basis + timedelta(hours=h), "temp": val(temp, h), "dew": val(dew, h),
             "rain": val(rain, h), "pop": val(pop, h), "gust": val(gust, h)}
            for h in range(n_uur)]


def _dag_m(tmax=24.0, rain=0.0, pop=10, gust=15.0):
    return {"tmax": tmax, "rain_mm": rain, "pop_max": pop, "gust_max": gust}


def _nacht_m(tmin=13.0, marge=3.0, rain=0.0, partial=False, pop=None):
    return {"tmin": tmin, "dew_margin": marge, "rain_mm": rain, "pop_max": pop, "partial": partial}


def _dagdict(d, cat="goed", partial=False, tmin=12.0, tmax=24.0, rd=0.0, rn=0.0, conf="hoog",
             score=0):
    return {"date": d.isoformat(), "cat": cat, "night_partial": partial,
            "tmin_night": tmin, "tmax": tmax, "rain_day_mm": rd, "rain_night_mm": rn,
            "conf": conf,
            # de velden die build_super_region daarbovenop van een subregio-dag kopieert
            "score": score, "dew_margin_night": 3.0, "red_flags": [], "main_reason": None}


def _om_payload(n_dagen=3, *, temp=20.0, dew=12.0, rain=0.0):
    """Minimaal Open-Meteo-antwoord, geankerd op local_today() (build_region
    itereert vanaf vandaag). Tijden naïef-lokaal, zoals Open-Meteo ze levert.
    `temp` mag een functie van het uurindex zijn (zelfde patroon als _reeks)."""
    vandaag = local_today()
    basis = datetime(vandaag.year, vandaag.month, vandaag.day)
    n = n_dagen * 24
    times = [(basis + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(n)]
    temps = [temp(h) if callable(temp) else temp for h in range(n)]
    return {"elevation": 5.0, "hourly": {
        "time": times,
        "temperature_2m": temps, "dew_point_2m": [dew] * n,
        "precipitation": [rain] * n, "precipitation_probability": [10] * n,
        "wind_gusts_10m": [15.0] * n,
    }}


def _ens_payload(n_dagen=3, *, temps=(12.0, 9.0), rain_per_uur=(0.0, 0.5)):
    """Ensemble-antwoord met twee leden (basis + member01)."""
    vandaag = local_today()
    basis = datetime(vandaag.year, vandaag.month, vandaag.day)
    n = n_dagen * 24
    times = [(basis + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(n)]
    return {"hourly": {
        "time": times,
        "temperature_2m": [temps[0]] * n,
        "temperature_2m_member01": [temps[1]] * n,
        "precipitation": [rain_per_uur[0]] * n,
        "precipitation_member01": [rain_per_uur[1]] * n,
    }}


# ── snedes en metriek ────────────────────────────────────────────────────────

def test_nachtvenster_loopt_van_21_tot_09_volgende_dag():
    # Dieptepunt om 08:00 de volgende ochtend (uur 32) hoort bij de nacht van D0;
    # een nóg lager punt om 12:00 (uur 36) valt erbuiten.
    rows = _reeks(n_uur=48, temp=lambda h: {32: 8.0, 36: 5.0}.get(h, 15.0))
    m = cf.night_metrics(rows, D0)
    assert m["tmin"] == 8.0
    assert m["partial"] is False


def test_nacht_zonder_volledige_dekking_is_partial():
    rows = _reeks(n_uur=28)  # loopt tot D0+1 03:00 — de ochtend wordt niet gehaald
    assert cf.night_metrics(rows, D0)["partial"] is True
    assert cf.night_metrics(_reeks(n_uur=12), D0) is None  # niets ná 21:00


def test_dauwmarge_is_de_minimale_t_min_td_van_de_nacht():
    rows = _reeks(n_uur=48, temp=15.0, dew=lambda h: 13.8 if h == 23 else 10.0)
    assert cf.night_metrics(rows, D0)["dew_margin"] == pytest.approx(1.2)


def test_dagvenster_pakt_tmax_regen_en_windstoten():
    # Regen om 10:00 telt mee; om 22:00 niet (dat is de nacht).
    rows = _reeks(n_uur=48, temp=lambda h: 26.0 if h == 14 else 20.0,
                  rain=lambda h: {10: 2.0, 22: 4.0}.get(h, 0.0),
                  gust=lambda h: 40.0 if h == 12 else 15.0)
    m = cf.day_metrics(rows, D0)
    assert m["tmax"] == 26.0
    assert m["rain_mm"] == pytest.approx(2.0)
    assert m["gust_max"] == 40.0
    assert cf.night_metrics(rows, D0)["rain_mm"] == pytest.approx(4.0)


def test_nachtvenster_pakt_ook_de_regenkans():
    # night_metrics droeg tot aug 2026 geen pop_max — de nacht had daardoor
    # geen enkel kans-signaal, alleen de gemeten hoeveelheid regen.
    rows = _reeks(n_uur=48, pop=lambda h: 80 if h == 26 else 10)  # uur 26 valt in de nacht van D0
    assert cf.night_metrics(rows, D0)["pop_max"] == 80


# ── score en categorie ───────────────────────────────────────────────────────

def test_perfecte_dag_scoort_top():
    score, redenen = cf.score_day(_dag_m(), _nacht_m())
    assert score == 0 and redenen == []
    assert cf.category(score, []) == "top"


def test_hittegrens_kost_punten():
    score_warm, r_warm = cf.score_day(_dag_m(tmax=cf.DAY_TMAX_WARM), _nacht_m())
    assert r_warm == ["hitte_naderend"] and score_warm == cf.PEN["hitte_naderend"]
    score_heet, r_heet = cf.score_day(_dag_m(tmax=cf.DAY_TMAX_HOT), _nacht_m())
    assert r_heet == ["hitte"] and score_heet == cf.PEN["hitte"]


def test_koude_nacht_alleen_valt_nooit_binnen_cat_goed():
    # Hard criterium: een nacht onder de 10° mag nooit in een venster vallen.
    # Dit moet blijven gelden ongeacht latere her-tuning van CAT_GOED/PEN.
    assert cf.PEN["koude_nacht"] > cf.CAT_GOED
    score, redenen = cf.score_day(_dag_m(), _nacht_m(tmin=cf.NIGHT_TMIN_COLD - 0.1))
    assert redenen == ["koude_nacht"]
    assert cf.category(score, []) not in cf.NIGHT_OK_CATS


def test_koude_nachtbanden_pinnen_op_de_constanten():
    for tmin, reden in ((cf.NIGHT_TMIN_COOL - 0.1, "koele_nacht"),
                        (cf.NIGHT_TMIN_COLD - 0.1, "koude_nacht"),
                        (cf.NIGHT_TMIN_HARD - 0.1, "te_koude_nacht")):
        score, redenen = cf.score_day(_dag_m(), _nacht_m(tmin=tmin))
        assert redenen == [reden] and score == cf.PEN[reden], tmin


def test_dagregen_weegt_zwaarder_dan_evenveel_nachtregen():
    mm = 4.0  # zelfde hoeveelheid, ander dagdeel
    overdag, _ = cf.score_day(_dag_m(rain=mm), _nacht_m())
    s_nachts, _ = cf.score_day(_dag_m(), _nacht_m(rain=mm))
    assert overdag > s_nachts


def test_krappe_dauwmarge_kost_punten():
    _, redenen = cf.score_day(_dag_m(), _nacht_m(marge=cf.DEW_MARGIN_GOOD - 0.1))
    assert redenen == ["dauw_krap"]
    _, redenen = cf.score_day(_dag_m(), _nacht_m(marge=cf.DEW_MARGIN_POOR - 0.1))
    assert redenen == ["dauw_nat"]


def test_wisselvallig_alleen_bij_droge_som_met_hoge_kans():
    _, redenen = cf.score_day(_dag_m(pop=cf.POP_DAY_UNSETTLED), _nacht_m())
    assert redenen == ["wisselvallig"]
    _, redenen = cf.score_day(_dag_m(rain=cf.DAY_RAIN_SOME_MM, pop=cf.POP_DAY_UNSETTLED), _nacht_m())
    assert "wisselvallig" not in redenen  # echte regen wint van de kans


def test_nachtregen_wisselvallig_alleen_bij_droge_som_met_hoge_kans():
    # Nachtelijk spiegelbeeld van de vorige test — tot aug 2026 bestond dit
    # signaal niet: een droge modeluitkomst met een hoge ensemble-regenkans
    # 's nachts bleef volledig onopgemerkt (gemeld door de gebruiker).
    _, redenen = cf.score_day(_dag_m(), _nacht_m(pop=cf.POP_NIGHT_UNSETTLED))
    assert redenen == ["nachtregen_wisselvallig"]
    _, redenen = cf.score_day(_dag_m(), _nacht_m(rain=cf.NIGHT_RAIN_SOME_MM, pop=cf.POP_NIGHT_UNSETTLED))
    assert "nachtregen_wisselvallig" not in redenen  # echte regen wint van de kans, net als overdag


def test_meerdere_lichte_dagproblemen_stapelen_niet_op_elkaar():
    # Drie lichte dagongemakken (elk uit MINOR_REASONS, alle in DAY_REASONS)
    # mogen samen niet zwaarder wegen dan het zwaarste ervan — alleen "echte"
    # problemen tellen vol mee. Een prima nacht laat het nachtdeel op 0.
    score, redenen = cf.score_day(
        _dag_m(tmax=cf.DAY_TMAX_WARM, pop=cf.POP_DAY_UNSETTLED, gust=cf.GUST_BREEZY_KMH),
        _nacht_m())
    assert set(redenen) == {"hitte_naderend", "wisselvallig", "wind_fris"}
    assert score == max(cf.PEN[r] for r in redenen)


def test_gecombineerde_score_is_het_zwaarste_van_de_twee_helften():
    # Eén echt probleem overdag (dagregen_matig) plus een licht ongemak
    # 's nachts (dauw_krap): de celscore is de zwaarste helft (dagdeel: 20),
    # niet de som van beide helften (30). Zie de docstring van score_day()
    # voor waarom — sommeren over dag/nacht gaf precies het "overzicht rood,
    # tegels groen"-effect dat de nieuwe MINOR_REASONS-demping juist moest
    # voorkomen.
    score, redenen = cf.score_day(_dag_m(rain=cf.DAY_RAIN_SOME_MM),
                                  _nacht_m(marge=cf.DEW_MARGIN_GOOD - 0.1))
    assert set(redenen) == {"dagregen_matig", "dauw_krap"}
    assert score == cf.PEN["dagregen_matig"]


def test_twee_zware_problemen_in_dezelfde_helft_stapelen_wel():
    # Het dempen (max i.p.v. som) geldt alleen tussen de twee helften. Binnen
    # één helft (hier: de nacht) tellen twee echte problemen nog altijd vol
    # samen op.
    score, redenen = cf.score_day(
        _dag_m(), _nacht_m(marge=cf.DEW_MARGIN_POOR - 0.1, rain=cf.NIGHT_RAIN_BAD_MM))
    assert set(redenen) == {"dauw_nat", "nachtregen_zwaar"}
    assert score == cf.PEN["dauw_nat"] + cf.PEN["nachtregen_zwaar"]


def test_gecombineerde_cel_is_nooit_slechter_dan_de_slechtste_helft():
    # Regressietoets voor de melding "overzicht toont slecht, beide tegels
    # tonen goed": een dag met twee problemen overdag (samen nog 'goed') en
    # een nacht met twee andere problemen (samen ook nog 'goed') mag
    # gecombineerd niet in 'slecht' vallen alleen omdat je de twee helften bij
    # elkaar optelt — de som (54) zou dat wél doen, het echte model niet.
    day_m = _dag_m(tmax=28.0, rain=cf.DAY_RAIN_SOME_MM)  # hitte_naderend + dagregen_matig → 30
    night_m = _nacht_m(marge=cf.DEW_MARGIN_POOR - 0.1, rain=cf.NIGHT_RAIN_SOME_MM)  # dauw_nat + nachtregen_matig → 24
    score, redenen = cf.score_day(day_m, night_m)
    parts = cf.split_parts(redenen, [], warn_day=False, warn_night=False)
    assert parts["score_day"] + parts["score_night"] > cf.CAT_MATIG  # de (foute) som zou "slecht" zijn
    assert cf.category(parts["score_day"], []) == "goed"
    assert cf.category(parts["score_night"], []) == "goed"
    assert score == max(parts["score_day"], parts["score_night"])
    assert cf.category(score, []) == "goed"


def test_minor_reasons_zijn_de_goedkoopste_trap_en_dekken_pen_niet_leeg():
    assert cf.MINOR_REASONS <= set(cf.PEN)
    assert cf.MINOR_REASONS < set(cf.PEN)  # er zijn ook "echte" problemen
    assert all(cf.PEN[r] <= 10 for r in cf.MINOR_REASONS)
    assert all(cf.PEN[r] >= 12 for r in set(cf.PEN) - cf.MINOR_REASONS)


def test_split_parts_dempt_lichte_redenen_ook_per_deel():
    parts = cf.split_parts(["wind_fris", "wisselvallig"], [], warn_day=False, warn_night=False)
    assert parts["score_day"] == max(cf.PEN["wind_fris"], cf.PEN["wisselvallig"])
    assert parts["score_night"] == 0


def test_categoriegrenzen_liggen_op_de_module_constanten():
    assert cf.category(cf.CAT_TOP, []) == "top"
    assert cf.category(cf.CAT_TOP + 1, []) == "goed"
    assert cf.category(cf.CAT_GOED, []) == "goed"
    assert cf.category(cf.CAT_GOED + 1, []) == "matig"
    assert cf.category(cf.CAT_MATIG, []) == "matig"
    assert cf.category(cf.CAT_MATIG + 1, []) == "slecht"


# ── rode vlaggen en waarschuwingsfilter ──────────────────────────────────────

def test_oranje_waarschuwing_maakt_ook_een_perfecte_dag_rood():
    # red_flags filtert zelf niet op kleur — het geel-filter (severe_warnings)
    # zit stroomopwaarts in build_region; hier komt dus alleen oranje+ binnen.
    flags = cf.red_flags(_dag_m(), _nacht_m(), [{"level": "orange"}])
    assert flags == ["waarschuwing"]
    assert cf.category(0, flags) == "rood"


def test_severe_warnings_filtert_geel_en_houdt_oranje_en_rood():
    import meteoalarm as mal
    ws = [{"level": "yellow"}, {"level": "orange"}, {"level": "red"}]
    over = cf.severe_warnings(ws)
    assert [w["level"] for w in over] == ["orange", "red"]
    assert all(mal.LEVEL_RANK[w["level"]] >= mal.LEVEL_RANK[cf.WARN_MIN_LEVEL] for w in over)


def _waarschuwing(level, start_uur=0, duur_uur=48):
    vandaag = local_today()
    onset = (datetime(vandaag.year, vandaag.month, vandaag.day, tzinfo=TZ)
             + timedelta(hours=start_uur))
    return {"area": "Utrecht", "geocodes": [], "event": "Testwaarschuwing",
            "level": level, "onset": onset, "expires": onset + timedelta(hours=duur_uur)}


def _bouw_regio(warnings, payload=None):
    return cf.build_region(cf.REGIONS[0], payload or _om_payload(), None,
                           warnings, local_today())


def test_gele_waarschuwing_kleurt_niets_meer_rood():
    blok = _bouw_regio([_waarschuwing("yellow")])
    dag0 = blok["days"][0]
    assert dag0["cat"] != "rood"
    assert dag0["warning"] is None
    assert blok["warnings_active"] == []


def test_oranje_waarschuwing_blijft_een_rode_vlag():
    blok = _bouw_regio([_waarschuwing("orange")])
    dag0 = blok["days"][0]
    assert dag0["cat"] == "rood"
    assert "waarschuwing" in dag0["red_flags"]
    assert blok["warnings_active"]


def test_extreme_voorspelling_is_rood_ook_zonder_waarschuwing():
    # Dit dekt de dagen voorbij MeteoAlarms ~2-4-daagse waarschuwingshorizon.
    assert "hitte_extreem" in cf.red_flags(_dag_m(tmax=cf.TMAX_RED), _nacht_m(), [])
    assert "koude_nacht_extreem" in cf.red_flags(_dag_m(), _nacht_m(tmin=cf.TMIN_RED), [])
    assert "storm" in cf.red_flags(_dag_m(gust=cf.GUST_RED_KMH), _nacht_m(), [])
    assert "stortregen" in cf.red_flags(_dag_m(rain=cf.DAY_RAIN_RED_MM), _nacht_m(), [])
    assert "stortregen_nacht" in cf.red_flags(_dag_m(), _nacht_m(rain=cf.NIGHT_RAIN_RED_MM), [])
    assert cf.red_flags(_dag_m(), _nacht_m(), []) == []


def test_zware_nachtregen_boven_de_rode_grens_is_niet_meer_slechts_goed():
    # Regressietoets voor de gebruikersmelding ("de komende 7 dagen overal
    # veel regeniger dan het dashboard toont"): nachtregen_zwaar dekte elke
    # hoeveelheid ≥ NIGHT_RAIN_BAD_MM met precies 30 punten — toevallig exact
    # CAT_GOED — dus zelfs een stortbui (gemeten: 25.2mm, Elzas 24 aug 2026)
    # kon nooit boven "goed" uitkomen. NIGHT_RAIN_RED_MM sluit dat gat, net
    # als DAY_RAIN_RED_MM/"stortregen" dat al deed voor de dag.
    score, redenen = cf.score_day(_dag_m(), _nacht_m(rain=25.2))
    assert redenen == ["nachtregen_zwaar"] and score == cf.PEN["nachtregen_zwaar"]
    flags = cf.red_flags(_dag_m(), _nacht_m(rain=25.2), [])
    assert cf.category(score, flags) == "rood"


# ── dag/nacht-splitsing ──────────────────────────────────────────────────────

def test_reden_partitie_dekt_pen_exact_en_disjunct():
    assert cf.DAY_REASONS | cf.NIGHT_REASONS == set(cf.PEN)
    assert not (cf.DAY_REASONS & cf.NIGHT_REASONS)
    assert not (cf.DAY_FLAGS & cf.NIGHT_FLAGS)


def test_split_parts_verdeelt_score_over_dag_en_nacht():
    parts = cf.split_parts(["hitte", "koude_nacht"], [], warn_day=False, warn_night=False)
    assert parts["score_day"] == cf.PEN["hitte"]
    assert parts["score_night"] == cf.PEN["koude_nacht"]
    assert parts["flags_day"] == [] and parts["flags_night"] == []


def test_split_parts_stuurt_waarschuwing_naar_het_juiste_deel():
    parts = cf.split_parts([], ["hitte_extreem", "koude_nacht_extreem", "storm"],
                           warn_day=False, warn_night=True)
    assert "waarschuwing" in parts["flags_night"]
    assert "waarschuwing" not in parts["flags_day"]
    assert set(parts["flags_day"]) == {"hitte_extreem", "storm"}
    assert set(parts["flags_night"]) == {"waarschuwing", "koude_nacht_extreem"}


def test_cat_dag_en_cat_nacht_zijn_onafhankelijk():
    # Hete dag (boven de daggrens, onder extreem) + prima nacht: het dagdeel
    # zakt naar matig terwijl het nachtdeel top blijft.
    heet = _om_payload(temp=lambda h: 31.0 if 9 <= h % 24 < 21 else 15.0)
    blok = _bouw_regio([], payload=heet)
    dag0 = blok["days"][0]
    assert dag0["cat_day"] == "matig"
    assert dag0["cat_night"] == "top"


def test_nachtwaarschuwing_maakt_alleen_de_nachttegel_rood():
    # Oranje waarschuwing 22:00–05:00: raakt het nachtvenster maar niet het
    # dagdeel — de nachttegel kleurt rood, de dagtegel niet, en de
    # gecombineerde cel (die de hele kampeernacht weegt) wél.
    blok = _bouw_regio([_waarschuwing("orange", start_uur=22, duur_uur=7)])
    dag0 = blok["days"][0]
    assert dag0["cat_night"] == "rood"
    assert dag0["cat_day"] != "rood"
    assert dag0["cat"] == "rood"
    assert "waarschuwing" in dag0["red_flags_night"]
    assert "waarschuwing" not in dag0["red_flags_day"]


# ── main_reason (het "waarom?"-icoon) ────────────────────────────────────────

def test_main_reason_kiest_de_zwaarste_reden_van_de_zwaarste_helft():
    # Dagdeel (dagregen_matig, 20) weegt zwaarder dan het nachtdeel (twee
    # lichte redenen die niet stapelen → 10), ook al heeft de nacht méér
    # redenen — de dominante helft bepaalt de celkleur, dus ook het icoon.
    reden = cf.main_reason(["dagregen_matig", "dauw_krap", "nachtregen_licht"])
    assert reden == "dagregen_matig"
    # En andersom: een zwaar nachtprobleem wint van een licht dagprobleem.
    assert cf.main_reason(["wind_fris", "nachtregen_zwaar"]) == "nachtregen_zwaar"


def test_main_reason_gelijke_helften_kiest_de_dag():
    assert cf.PEN["wind_fris"] == cf.PEN["dauw_krap"]  # premisse van het gelijkspel
    assert cf.main_reason(["wind_fris", "dauw_krap"]) == "wind_fris"


def test_main_reason_leeg_is_none():
    assert cf.main_reason([]) is None


def test_dagdict_draagt_main_reason():
    blok = _bouw_regio([], payload=_om_payload())  # kurkdroog en mild → niets aan de hand
    assert blok["days"][0]["main_reason"] is None
    heet = _bouw_regio([], payload=_om_payload(temp=lambda h: 31.0 if 9 <= h % 24 < 21 else 15.0))
    assert heet["days"][0]["main_reason"] == "hitte"


def test_dagdict_draagt_pop_night_max():
    # Additief veld (aug 2026) — het nachtelijke spiegelbeeld van pop_day_max,
    # nodig zodra night_metrics zelf een kans-signaal draagt.
    blok = _bouw_regio([], payload=_om_payload())
    assert blok["days"][0]["pop_night_max"] == 10  # _om_payload zet 10% overal


# ── verwachtingstekst ────────────────────────────────────────────────────────

def _vdag(datum, tmax=22.0, tmin=13.0, rd=0.0, rn=0.0, marge=3.0):
    return {"date": datum.isoformat(), "tmax": tmax, "tmin_night": tmin,
            "rain_day_mm": rd, "rain_night_mm": rn, "dew_margin_night": marge}


def test_verwachting_slaapzakladder_pint_op_de_constanten():
    for grens, hint in cf.SLAAPZAK:
        tekst = cf.verwachting_text([_vdag(D0, tmin=grens)])
        assert hint in tekst, grens
    laagste = cf.SLAAPZAK[-1][0]
    assert cf.SLAAPZAK_TE_KOUD in cf.verwachting_text([_vdag(D0, tmin=laagste - 1.0)])


def test_verwachting_dag_en_nachtkarakter_banden():
    for grens, label in cf.VERW_DAG_BANDEN:
        assert label in cf.verwachting_text([_vdag(D0, tmax=grens)]).lower(), label
    onderste = cf.VERW_DAG_BANDEN[-1][0]
    assert cf.VERW_DAG_FRIS in cf.verwachting_text([_vdag(D0, tmax=onderste - 1.0)]).lower()
    for grens, label in cf.VERW_NACHT_BANDEN:
        assert label in cf.verwachting_text([_vdag(D0, tmin=grens)])
    assert cf.VERW_NACHT_KOUD in cf.verwachting_text([_vdag(D0, tmin=8.0)])


def test_verwachting_noemt_regendagen_bij_naam():
    dagen = [_vdag(D0), _vdag(D0 + timedelta(days=1), rd=4.0), _vdag(D0 + timedelta(days=2))]
    tekst = cf.verwachting_text(dagen)
    assert cf._daglabel((D0 + timedelta(days=1)).isoformat()) in tekst
    assert "droog" in cf.verwachting_text([_vdag(D0), _vdag(D0 + timedelta(days=1))]).lower()
    nachtnat = cf.verwachting_text([_vdag(D0, rn=2.0)])
    assert "'s nachts" in nachtnat


def test_verwachting_noemt_dauw_bij_krappe_marge():
    assert "nat van de dauw" in cf.verwachting_text([_vdag(D0, marge=cf.DEW_MARGIN_POOR - 0.5)])
    assert "bij het inpakken" in cf.verwachting_text([_vdag(D0, marge=cf.DEW_MARGIN_GOOD - 0.5)])
    assert "dauw" not in cf.verwachting_text([_vdag(D0, marge=cf.DEW_MARGIN_GOOD + 1.0)])


def test_verwachting_hangt_aan_venster_en_regio():
    assert cf.verwachting_text([]) is None
    blok = _bouw_regio([], payload=_om_payload(n_dagen=6))
    assert isinstance(blok["verwachting"], str)
    assert blok["windows"], "venster verwacht bij 6 droge, milde dagen"
    assert isinstance(blok["windows"][0]["verwachting"], str)


# ── vensters en vertrek ──────────────────────────────────────────────────────

def test_venster_vereist_min_nights_goede_nachten():
    dagen = [_dagdict(D0 + timedelta(days=i)) for i in range(cf.MIN_NIGHTS)]
    ws = cf.detect_windows(dagen)
    assert len(ws) == 1
    w = ws[0]
    assert w["nights"] == cf.MIN_NIGHTS
    assert w["start"] == D0.isoformat()
    assert w["vertrek"] == (D0 + timedelta(days=cf.MIN_NIGHTS)).isoformat()
    assert cf.detect_windows(dagen[:-1]) == []  # één nacht te kort


def test_matige_dag_breekt_het_venster():
    dagen = ([_dagdict(D0 + timedelta(days=i)) for i in range(2)]
             + [_dagdict(D0 + timedelta(days=2), cat="matig")]
             + [_dagdict(D0 + timedelta(days=3 + i)) for i in range(cf.MIN_NIGHTS)])
    ws = cf.detect_windows(dagen)
    assert len(ws) == 1
    assert ws[0]["start"] == (D0 + timedelta(days=3)).isoformat()


def test_afgekapte_nacht_telt_niet_mee():
    dagen = [_dagdict(D0 + timedelta(days=i)) for i in range(cf.MIN_NIGHTS - 1)]
    dagen.append(_dagdict(D0 + timedelta(days=cf.MIN_NIGHTS - 1), partial=True))
    assert cf.detect_windows(dagen) == []


def test_venster_draagt_de_zwakste_zekerheid():
    dagen = [_dagdict(D0 + timedelta(days=i), conf=c)
             for i, c in enumerate(("hoog", "middel", "hoog"))]
    assert cf.detect_windows(dagen)[0]["conf"] == "middel"


def test_droog_vertrek_vereist_droge_nacht_en_droge_ochtend():
    n = cf.MIN_NIGHTS + 1
    dagen = [_dagdict(D0 + timedelta(days=i)) for i in range(n)]
    per_datum = {d["date"]: d for d in dagen}
    w = cf.detect_windows(dagen)[0]
    rows = _reeks(n_uur=(n + 2) * 24)  # kurkdroog
    assert cf.departure_advice(w, per_datum, rows) == {"droog_vertrek": True, "beste_vertrek": None}


def test_natte_vertrekochtend_maakt_het_vertrek_niet_droog():
    n = cf.MIN_NIGHTS + 1
    dagen = [_dagdict(D0 + timedelta(days=i)) for i in range(n)]
    per_datum = {d["date"]: d for d in dagen}
    w = cf.detect_windows(dagen)[0]
    # Regen om 07:00 op de vertrekochtend (dag n), verder droog: het vertrek
    # schuift naar de laatste droge ochtend die ≥ MIN_NIGHTS nachten overlaat.
    natte_uur = n * 24 + 7
    rows = _reeks(n_uur=(n + 2) * 24, rain=lambda h: 1.0 if h == natte_uur else 0.0)
    advies = cf.departure_advice(w, per_datum, rows)
    assert advies["droog_vertrek"] is False
    assert advies["beste_vertrek"] == (D0 + timedelta(days=n - 1)).isoformat()


def test_natte_laatste_nacht_suggereert_eerdere_vertrekochtend():
    n = cf.MIN_NIGHTS + 1
    dagen = [_dagdict(D0 + timedelta(days=i)) for i in range(n)]
    dagen[-1]["rain_night_mm"] = 2.0  # laatste nacht nat, de rest droog
    per_datum = {d["date"]: d for d in dagen}
    w = cf.detect_windows(dagen)[0]
    advies = cf.departure_advice(w, per_datum, _reeks(n_uur=(n + 2) * 24))
    assert advies["droog_vertrek"] is False
    assert advies["beste_vertrek"] == (D0 + timedelta(days=n - 1)).isoformat()


def test_geen_droge_ochtend_geeft_geen_beste_vertrek():
    dagen = [_dagdict(D0 + timedelta(days=i), rn=2.0) for i in range(cf.MIN_NIGHTS)]
    per_datum = {d["date"]: d for d in dagen}
    w = cf.detect_windows(dagen)[0]
    advies = cf.departure_advice(w, per_datum, _reeks(n_uur=6 * 24))
    assert advies == {"droog_vertrek": False, "beste_vertrek": None}


# ── ensemble en zekerheid ────────────────────────────────────────────────────

def test_member_series_leest_member_kolommen_op_prefix():
    ms = cf.member_series(_ens_payload())
    assert len(ms["temperature_2m"]) == 2
    assert len(ms["precipitation"]) == 2
    assert cf.member_series(None) is None
    assert cf.member_series({"hourly": {"time": []}}) is None


def test_ensemble_fracties_per_criterium():
    # Lid 0: 12° en droog; lid 1: 9° en 0.5 mm/u → helft van de leden haalt
    # nacht- en droogte-criteria, allebei blijven onder de daggrens.
    vandaag = local_today()
    probs = cf.day_probs(cf.member_series(_ens_payload()), vandaag)
    assert probs == {"tmin_ok": 0.5, "tmax_ok": 1.0, "dry_day": 0.5, "dry_night": 0.5}


def test_dag_voorbij_de_ensemble_horizon_geeft_geen_probs():
    ms = cf.member_series(_ens_payload(n_dagen=2))
    assert cf.day_probs(ms, local_today() + timedelta(days=5)) is None


def test_ensemble_fracties_bepalen_de_tier():
    hoog = {"tmin_ok": cf.CONF_HOOG, "tmax_ok": 1.0, "dry_day": 1.0, "dry_night": 1.0}
    assert cf.confidence(0, hoog) == "hoog"
    middel = dict(hoog, dry_day=cf.CONF_MIDDEL)
    assert cf.confidence(0, middel) == "middel"  # zwakste schakel telt
    laag = dict(hoog, tmin_ok=cf.CONF_MIDDEL - 0.01)
    assert cf.confidence(0, laag) == "laag"


def test_eensgezind_slecht_is_hoge_zekerheid_niet_lage():
    # tmax_ok=0.0: geen enkel lid voorspelt een dag onder de hittegrens — het
    # ensemble is het roerend eens, alleen over een ongunstige uitkomst. Vóór
    # deze fix pakte confidence() de rauwe fractie (0.0) als "agreement" en
    # merkte zo'n dag als "laag" — het omgekeerde van wat het ensemble zegt.
    eensgezind_heet = {"tmin_ok": 1.0, "tmax_ok": 0.0, "dry_day": 1.0, "dry_night": 1.0}
    assert cf.confidence(0, eensgezind_heet) == "hoog"
    # Écht verdeeld (fractie rond 0.5) blijft "laag" — dat is de reden dat de
    # arcering bestaat.
    verdeeld = {"tmin_ok": 1.0, "tmax_ok": 1.0, "dry_day": 0.5, "dry_night": 1.0}
    assert cf.confidence(0, verdeeld) == "laag"


def test_horizon_topt_de_tier_af():
    perfect = {"tmin_ok": 1.0, "tmax_ok": 1.0, "dry_day": 1.0, "dry_night": 1.0}
    assert cf.confidence(cf.CONF_HORIZON_CAP_MIDDEL, perfect) == "middel"
    assert cf.confidence(cf.CONF_HORIZON_CAP_LAAG, perfect) == "laag"


def test_zonder_ensemble_valt_de_tier_terug_op_de_horizon_ladder():
    (h_grens, _), (m_grens, _) = cf.CONF_FALLBACK
    assert cf.confidence(0, None) == "hoog"
    assert cf.confidence(h_grens, None) == "middel"
    assert cf.confidence(m_grens, None) == "laag"


# ── fetch-vorm en main-orkestratie ───────────────────────────────────────────

def test_forecast_fetch_vraagt_dauwpunt_16_dagen_en_timezone(monkeypatch):
    gezien = {}

    def fake(url, params=None, **kw):
        gezien.update(params)
        return _om_payload()

    monkeypatch.setattr(cf, "get_json", fake)
    cf.fetch_region_forecast(cf.REGIONS[0])
    assert gezien["forecast_days"] == cf.FORECAST_DAYS
    assert "dew_point_2m" in gezien["hourly"]
    assert gezien["timezone"] == cf.OM_TIMEZONE


def test_ensemble_uitval_is_niet_fataal(monkeypatch):
    def kapot(url, params=None, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(cf, "get_json", kapot)
    assert cf.fetch_region_ensemble(cf.REGIONS[0]) is None


def test_resilient_fetch_slaagt_meteen_zonder_pauze(monkeypatch):
    monkeypatch.setattr(cf, "fetch_region_forecast", lambda r: _om_payload())
    slaap = []
    monkeypatch.setattr(cf.time, "sleep", slaap.append)
    assert cf.fetch_region_forecast_resilient(cf.REGIONS[0]) == _om_payload()
    assert slaap == []


def test_resilient_fetch_herkanst_één_keer_na_een_pauze(monkeypatch):
    pogingen = []

    def fake(region):
        pogingen.append(1)
        if len(pogingen) == 1:
            raise RuntimeError("boom")
        return _om_payload()

    monkeypatch.setattr(cf, "fetch_region_forecast", fake)
    slaap = []
    monkeypatch.setattr(cf.time, "sleep", slaap.append)
    assert cf.fetch_region_forecast_resilient(cf.REGIONS[0]) == _om_payload()
    assert len(pogingen) == 2
    assert slaap == [cf.REGION_RETRY_DELAY_S]


def test_resilient_fetch_geeft_de_tweede_fout_door_als_beide_pogingen_falen(monkeypatch):
    def kapot(region):
        raise RuntimeError("boom")

    monkeypatch.setattr(cf, "fetch_region_forecast", kapot)
    monkeypatch.setattr(cf.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="boom"):
        cf.fetch_region_forecast_resilient(cf.REGIONS[0])


def test_een_kapotte_regio_laat_de_rest_doorgaan(monkeypatch, tmp_path):
    monkeypatch.delenv("DRY_RUN", raising=False)
    pad = tmp_path / "camping.json"
    monkeypatch.setattr(cf, "DATA_PATH", str(pad))
    monkeypatch.setattr(cf.meteoalarm, "fetch_country_warnings", lambda c: [])
    monkeypatch.setattr(cf, "fetch_region_ensemble", lambda r: None)
    monkeypatch.setattr(cf.time, "sleep", lambda s: None)

    def fake_forecast(region):
        if region["id"] == "tirol":
            raise RuntimeError("boom")
        return _om_payload()

    monkeypatch.setattr(cf, "fetch_region_forecast", fake_forecast)
    cf.main()
    data = json.loads(pad.read_text(encoding="utf-8"))
    per_id = {r["id"]: r for r in data["regions"]}
    assert len(data["regions"]) == len(cf.REGIONS)
    assert per_id["tirol"]["status"] == "unavailable"
    assert per_id["utrecht"]["status"] == "ok"


def test_een_regio_die_alleen_de_herkansing_haalt_blijft_ok(monkeypatch, tmp_path):
    """De regio-brede herkansing (aug 2026): eerste poging mislukt, tweede lukt."""
    monkeypatch.delenv("DRY_RUN", raising=False)
    pad = tmp_path / "camping.json"
    monkeypatch.setattr(cf, "DATA_PATH", str(pad))
    monkeypatch.setattr(cf.meteoalarm, "fetch_country_warnings", lambda c: [])
    monkeypatch.setattr(cf, "fetch_region_ensemble", lambda r: None)
    slaap = []
    monkeypatch.setattr(cf.time, "sleep", slaap.append)

    pogingen = {"tirol": 0}

    def fake_forecast(region):
        if region["id"] == "tirol":
            pogingen["tirol"] += 1
            if pogingen["tirol"] == 1:
                raise RuntimeError("boom")
        return _om_payload()

    monkeypatch.setattr(cf, "fetch_region_forecast", fake_forecast)
    cf.main()
    data = json.loads(pad.read_text(encoding="utf-8"))
    per_id = {r["id"]: r for r in data["regions"]}
    assert per_id["tirol"]["status"] == "ok"
    assert pogingen["tirol"] == 2
    assert slaap == [cf.REGION_RETRY_DELAY_S]


def test_alle_regios_kapot_raist(monkeypatch):
    monkeypatch.setattr(cf.meteoalarm, "fetch_country_warnings", lambda c: [])
    monkeypatch.setattr(cf.time, "sleep", lambda s: None)

    def kapot(region):
        raise RuntimeError("boom")

    monkeypatch.setattr(cf, "fetch_region_forecast", kapot)
    with pytest.raises(RuntimeError, match="alle regio's"):
        cf.main()


# ── super-regio's en flexroute ───────────────────────────────────────────────

def _flexsub(scores, d0=D0, cats=None):
    """datum→dag-dict met alleen wat _flex_day_cost leest (cat + score)."""
    return {(d0 + timedelta(days=i)).isoformat():
            {"cat": (cats[i] if cats else "goed"), "score": s}
            for i, s in enumerate(scores)}


def _datums(n, d0=D0):
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _subblok(rid, days, status="ok"):
    """Minimaal subregio-blok zoals build_super_region het uit build_region krijgt."""
    blok = {"id": rid, "label": rid.capitalize(), "country": "AT", "status": status}
    if status == "ok":
        blok["days"] = days
    return blok


def test_super_regions_partitioneren_alle_niet_utrecht_regios():
    alle = {r["id"] for r in cf.REGIONS}
    groepen = [set(s["region_ids"]) for s in cf.SUPER_REGIONS]
    unie = set().union(*groepen)
    assert unie == alle - {"utrecht"}
    assert sum(len(g) for g in groepen) == len(unie)  # disjunct


def test_flex_route_verkast_nooit_voor_min_nights():
    # Op dag 2 naar B springen zou het goedkoopst zijn, maar mag pas na
    # MIN_NIGHTS nachten — de route verkast dus exact op index MIN_NIGHTS.
    n = cf.MIN_NIGHTS * 2
    a = _flexsub([0, 0] + [80] * (n - 2))
    b = _flexsub([50, 50] + [0] * (n - 2))
    route = cf.flex_route([a, b], _datums(n))
    assert [moved for _, moved in route].index(True) == cf.MIN_NIGHTS
    assert all(not moved for _, moved in route[:cf.MIN_NIGHTS])
    assert route[cf.MIN_NIGHTS:] == [(1, True)] + [(1, False)] * (n - cf.MIN_NIGHTS - 1)


def test_flex_route_vermijdt_rood_waar_mogelijk():
    # A is bijna perfect maar heeft één rode dag; B is overal "slecht" zonder
    # rood — de route brengt de rode dag in B door, want rood is een blokkade
    # en geen afweging (wat de route vóór of ná die dag doet, mag score-gedreven
    # zijn — vandaar alleen de rood-vrij-invariant).
    n = cf.MIN_NIGHTS + 1
    cats_a = ["goed"] * n
    cats_a[2] = "rood"
    subs = [_flexsub([0] * n, cats=cats_a), _flexsub([40] * n, cats=["slecht"] * n)]
    route = cf.flex_route(subs, _datums(n))
    assert "rood" not in [subs[r][d]["cat"] for (r, _), d in zip(route, _datums(n))]


def test_flex_route_neemt_rood_alleen_als_het_niet_anders_kan():
    # Beide subregio's rood op dag 1 → er bestaat tóch een route, en die dag
    # draagt de echte cat "rood" in het super-blok.
    n = cf.MIN_NIGHTS + 1
    cats = ["goed"] * n
    cats[1] = "rood"
    dagen_a = [_dagdict(D0 + timedelta(days=i), cat=c) for i, c in enumerate(cats)]
    dagen_b = [_dagdict(D0 + timedelta(days=i), cat=c, score=5) for i, c in enumerate(cats)]
    blok = cf.build_super_region(
        {"id": "x", "label": "X", "region_ids": ("a", "b")},
        {"a": _subblok("a", dagen_a), "b": _subblok("b", dagen_b)})
    assert blok["status"] == "ok"
    assert blok["red_days"] == 1
    assert blok["days"][1]["cat"] == "rood"


def test_move_penalty_voorkomt_verkassen_voor_kleine_winst():
    # De winst van verkassen (2 punten/dag over de staart) blijft onder
    # MOVE_PENALTY → blijven staan; wordt de staart duurder dan de straf,
    # dan verkast de route wél.
    n = cf.MIN_NIGHTS * 2
    staart = n - cf.MIN_NIGHTS
    klein = cf.MOVE_PENALTY // staart  # per dag, totaal < MOVE_PENALTY
    assert klein * staart < cf.MOVE_PENALTY
    b = _flexsub([5] * cf.MIN_NIGHTS + [0] * staart)
    a_blijf = _flexsub([0] * cf.MIN_NIGHTS + [klein] * staart)
    route = cf.flex_route([a_blijf, b], _datums(n))
    assert all(not moved for _, moved in route)

    duur = cf.MOVE_PENALTY + 1  # totaal > MOVE_PENALTY
    a_ga = _flexsub([0] * cf.MIN_NIGHTS + [duur] * staart)
    route = cf.flex_route([a_ga, b], _datums(n))
    assert [moved for _, moved in route].count(True) == 1
    assert route[cf.MIN_NIGHTS] == (1, True)


def test_flex_route_gelijkspel_kiest_minste_verkassingen_en_eerste_subregio():
    n = cf.MIN_NIGHTS * 2
    a = _flexsub([10] * n)
    b = _flexsub([10] * n)
    route = cf.flex_route([a, b], _datums(n))
    assert route == [(0, False)] * n  # geen verkassing, deterministisch A


def test_flex_route_ontbrekende_datum_is_onbeschikbaar():
    # B is overal beter maar mist de laatste datum → de route staat daar die
    # dag niet (en de horizonstaart-verkassing naar A mag korter dan
    # MIN_NIGHTS zijn — bewust, zie flex_route's docstring).
    n = cf.MIN_NIGHTS + 2
    a = _flexsub([10] * n)
    b = _flexsub([0] * (n - 1))
    route = cf.flex_route([a, b], _datums(n))
    assert route[-1] == (0, True)
    assert all(r == 1 for r, _ in route[:-1])


def test_red_day_penalty_domineert_elke_gewone_route():
    # Overtellende bovengrens van een niet-rode dagscore: som van álle echte
    # problemen + het zwaarste lichte — ruimer dan max(dag, nacht) ooit wordt.
    zwaarste_dag = (sum(v for k, v in cf.PEN.items() if k not in cf.MINOR_REASONS)
                    + max(cf.PEN[k] for k in cf.MINOR_REASONS))
    assert cf.RED_DAY_PENALTY > cf.FORECAST_DAYS * (zwaarste_dag + cf.MOVE_PENALTY)


def test_build_super_region_zonder_bruikbare_subregios_is_unavailable():
    sup = {"id": "x", "label": "X", "region_ids": ("a", "b")}
    blok = cf.build_super_region(sup, {"a": _subblok("a", [], status="unavailable"),
                                       "b": _subblok("b", [], status="unavailable")})
    assert blok["status"] == "unavailable"
    assert "days" not in blok
    # één werkende subregio is genoeg
    dagen = [_dagdict(D0 + timedelta(days=i)) for i in range(cf.MIN_NIGHTS)]
    blok = cf.build_super_region(sup, {"a": _subblok("a", dagen),
                                       "b": _subblok("b", [], status="unavailable")})
    assert blok["status"] == "ok"
    assert all(x["region"] == "a" for x in blok["days"])


def test_super_dag_draagt_echte_cat_score_en_segmenten_kloppen():
    n = cf.MIN_NIGHTS * 2
    dagen_a = [_dagdict(D0 + timedelta(days=i), score=5) for i in range(cf.MIN_NIGHTS)] + \
              [_dagdict(D0 + timedelta(days=cf.MIN_NIGHTS + i), cat="slecht", score=40)
               for i in range(n - cf.MIN_NIGHTS)]
    dagen_b = [_dagdict(D0 + timedelta(days=i), cat="slecht", score=40) for i in range(cf.MIN_NIGHTS)] + \
              [_dagdict(D0 + timedelta(days=cf.MIN_NIGHTS + i), cat="top", score=0)
               for i in range(n - cf.MIN_NIGHTS)]
    blok = cf.build_super_region(
        {"id": "x", "label": "X", "region_ids": ("a", "b")},
        {"a": _subblok("a", dagen_a), "b": _subblok("b", dagen_b)})

    # eerste helft A, tweede helft B; de verkasdag is exact de segmentstart
    assert [x["region"] for x in blok["days"]] == ["a"] * cf.MIN_NIGHTS + ["b"] * (n - cf.MIN_NIGHTS)
    assert [x["move"] for x in blok["days"]].count(True) == 1
    assert blok["days"][cf.MIN_NIGHTS]["move"] is True
    # echte subregio-waarden, geen stuurgetallen
    assert blok["days"][0]["score"] == 5 and blok["days"][0]["cat"] == "goed"
    assert blok["days"][cf.MIN_NIGHTS]["cat"] == "top"
    assert blok["segments"] == [
        {"region": "a", "region_label": "A", "start": D0.isoformat(),
         "end_night": (D0 + timedelta(days=cf.MIN_NIGHTS - 1)).isoformat()},
        {"region": "b", "region_label": "B", "start": (D0 + timedelta(days=cf.MIN_NIGHTS)).isoformat(),
         "end_night": (D0 + timedelta(days=n - 1)).isoformat()},
    ]
    assert blok["moves"] == len(blok["segments"]) - 1 == 1
    # kopcijfers: goed (A) + top (B) tellen allebei als goede nacht
    assert blok["nights_ok"] == blok["nights_total"] == n
    assert blok["red_days"] == 0
    # en de route-dagen voeden detect_windows ongewijzigd
    assert blok["windows"][0]["nights"] == n


# ── artefact ─────────────────────────────────────────────────────────────────

def _run_main(monkeypatch, tmp_path, *, faal_land=None):
    monkeypatch.delenv("DRY_RUN", raising=False)
    pad = tmp_path / "camping.json"
    monkeypatch.setattr(cf, "DATA_PATH", str(pad))

    def warnings(country):
        if country == faal_land:
            raise RuntimeError("feed kapot")
        return []

    monkeypatch.setattr(cf.meteoalarm, "fetch_country_warnings", warnings)
    monkeypatch.setattr(cf, "fetch_region_forecast", lambda r: _om_payload())
    monkeypatch.setattr(cf, "fetch_region_ensemble", lambda r: _ens_payload())
    cf.main()
    return pad


def test_artefact_bevat_generated_at_params_en_alle_regios(monkeypatch, tmp_path):
    pad = _run_main(monkeypatch, tmp_path)
    data = json.loads(pad.read_text(encoding="utf-8"))
    assert data["generated_at"]
    assert data["params"]["MIN_NIGHTS"] == cf.MIN_NIGHTS
    assert data["horizon_days"] == cf.FORECAST_DAYS
    assert [r["id"] for r in data["regions"]] == [r["id"] for r in cf.REGIONS]
    dag0 = data["regions"][0]["days"][0]
    assert dag0["cat"] in ("top", "goed", "matig", "slecht", "rood")
    assert dag0["conf"] in ("hoog", "middel", "laag")
    assert dag0["cat_day"] in ("top", "goed", "matig", "slecht", "rood")
    assert "cat_night" in dag0 and "red_flags_day" in dag0 and "red_flags_night" in dag0
    assert data["params"]["WARN_MIN_LEVEL"] == cf.WARN_MIN_LEVEL
    assert data["params"]["NIGHT_RAIN_RED_MM"] == cf.NIGHT_RAIN_RED_MM
    assert "verwachting" in data["regions"][0]


def test_artefact_bevat_super_regions_blok(monkeypatch, tmp_path):
    pad = _run_main(monkeypatch, tmp_path)
    data = json.loads(pad.read_text(encoding="utf-8"))
    assert [s["id"] for s in data["super_regions"]] == [s["id"] for s in cf.SUPER_REGIONS]
    assert data["params"]["MOVE_PENALTY"] == cf.MOVE_PENALTY
    blok = data["super_regions"][0]
    assert blok["status"] == "ok"
    assert blok["moves"] == len(blok["segments"]) - 1
    dag0 = blok["days"][0]
    for veld in ("region", "region_label", "move", "cat", "score", "conf", "night_partial"):
        assert veld in dag0
    assert dag0["region"] in blok["region_ids"]


def test_warnings_status_onderscheidt_ok_en_failed(monkeypatch, tmp_path):
    pad = _run_main(monkeypatch, tmp_path, faal_land="FR")
    data = json.loads(pad.read_text(encoding="utf-8"))
    assert data["warnings_status"]["FR"] == "failed"
    assert data["warnings_status"]["NL"] == "ok"
    assert data["warnings_status"]["AT"] == "ok"


def test_dry_run_schrijft_geen_artefact(monkeypatch, tmp_path):
    monkeypatch.setenv("DRY_RUN", "1")
    pad = tmp_path / "camping.json"
    monkeypatch.setattr(cf, "DATA_PATH", str(pad))
    monkeypatch.setattr(cf.meteoalarm, "fetch_country_warnings", lambda c: [])
    monkeypatch.setattr(cf, "fetch_region_forecast", lambda r: _om_payload())
    monkeypatch.setattr(cf, "fetch_region_ensemble", lambda r: None)
    cf.main()
    assert not pad.exists()


# ── workflow-contract ────────────────────────────────────────────────────────

def _workflow(name):
    return (pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"
            / name).read_text(encoding="utf-8")


def test_workflow_checkout_gepind(assert_checkout_pinned):
    assert_checkout_pinned("camping-forecast.yml")


def test_datacommit_start_geen_ci():
    wf = _workflow("camping-forecast.yml")
    for regel in wf.splitlines():
        if "git commit -m" in regel:
            assert "[skip ci]" in regel


def test_fallback_cron_dekt_de_vier_slots_in_lokale_tijd():
    wf = _workflow("camping-forecast.yml")
    assert '"30 0,6,12,18 * * *"' in wf
    assert 'timezone: "Europe/Amsterdam"' in wf
    assert "dry_run:" in wf and "slot:" in wf


def test_fallback_guard_ankert_op_het_slot_niet_op_middernacht():
    # Met 4 runs/dag zou een middernacht-venster de fallback altijd laten
    # skippen (de soil/mowing-les) — de guard moet het lopende 6-uursslot pakken.
    wf = _workflow("camping-forecast.yml")
    assert "slot=$(( (10#$h / 6) * 6 ))" in wf
    assert 'date -d "today 00:00"' not in wf


def test_orchestrator_dispatcht_vier_slots_met_eigen_ankers():
    orch = _workflow("orchestrator.yml")
    assert 'q2=$(TZ=Europe/Amsterdam date -d "today 06:00" +%s)' in orch
    assert 'q3=$(TZ=Europe/Amsterdam date -d "today 12:00" +%s)' in orch
    assert 'q4=$(TZ=Europe/Amsterdam date -d "today 18:00" +%s)' in orch
    assert orch.count("dispatch camping-forecast.yml -f slot=") == 4
    assert 'handled_since camping-forecast.yml "$day_start"' in orch
    for anker in ("$q2", "$q3", "$q4"):
        assert f'handled_since camping-forecast.yml "{anker}"' in orch
