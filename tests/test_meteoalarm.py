"""Tests voor meteoalarm.py — zuivere parsefuncties op geconserveerde XML.

Geen netwerk. De feeds zelf zijn pas op de eerste echte Actions-run te zien;
deze tests pinnen het defensieve contract: namespace-tolerantie (CAP 1.1 én
1.2), awareness_level boven severity, groen valt af, taal-duplicaten ontdubbeld,
ontbrekende expires krijgt de default-duur.
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import pytest

import meteoalarm as mal

UTC = timezone.utc


def _feed(entries: str, cap_ns: str = "urn:oasis:names:tc:emergency:cap:1.2") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:cap="{cap_ns}">
  <title>MeteoAlarm testfeed</title>
  {entries}
</feed>"""


ENTRY_PONGAU = """
  <entry>
    <title>Yellow thunderstorm warning</title>
    <cap:event>Thunderstorm</cap:event>
    <cap:severity>Severe</cap:severity>
    <cap:awareness_level>2; yellow; Moderate</cap:awareness_level>
    <cap:awareness_type>3; Thunderstorm</cap:awareness_type>
    <cap:onset>2026-08-14T14:00:00+02:00</cap:onset>
    <cap:expires>2026-08-14T22:00:00+02:00</cap:expires>
    <cap:areaDesc>Pongau</cap:areaDesc>
    <cap:geocode><valueName>EMMA_ID</valueName><value>AT005</value></cap:geocode>
  </entry>"""

ENTRY_HAUT_RHIN = """
  <entry>
    <title>Vigilance orange pluie</title>
    <cap:severity>Severe</cap:severity>
    <cap:awareness_type>10; Rain</cap:awareness_type>
    <cap:onset>2026-08-15T06:00:00+02:00</cap:onset>
    <cap:expires>2026-08-15T20:00:00+02:00</cap:expires>
    <cap:areaDesc>Haut-Rhin</cap:areaDesc>
  </entry>"""

ENTRY_MINOR = """
  <entry>
    <title>Green — no warning</title>
    <cap:severity>Minor</cap:severity>
    <cap:awareness_level>1; green; Minor</cap:awareness_level>
    <cap:onset>2026-08-14T00:00:00+02:00</cap:onset>
    <cap:expires>2026-08-15T00:00:00+02:00</cap:expires>
    <cap:areaDesc>Utrecht</cap:areaDesc>
  </entry>"""

ENTRY_ZONDER_EXPIRES = """
  <entry>
    <title>Yellow wind warning</title>
    <cap:event>Wind</cap:event>
    <cap:awareness_level>2; yellow; Moderate</cap:awareness_level>
    <cap:onset>2026-08-16T00:00:00+02:00</cap:onset>
    <cap:areaDesc>Utrecht</cap:areaDesc>
  </entry>"""


# ── parse_feed ───────────────────────────────────────────────────────────────

def test_parse_feed_leest_event_level_gebied_en_tijden_uit_atom():
    ws = mal.parse_feed(_feed(ENTRY_PONGAU))
    assert len(ws) == 1
    w = ws[0]
    assert w["area"] == "Pongau"
    assert w["event"] == "Thunderstorm"
    assert w["level"] == "yellow"
    assert w["onset"] == datetime(2026, 8, 14, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    assert w["expires"] == datetime(2026, 8, 14, 22, 0, tzinfo=timezone(timedelta(hours=2)))
    assert "AT005" in w["geocodes"]


def test_awareness_level_wint_boven_cap_severity():
    # severity zegt Severe (oranje), awareness_level zegt geel — de kleur die
    # MeteoAlarm zelf publiceert wint.
    ws = mal.parse_feed(_feed(ENTRY_PONGAU))
    assert ws[0]["level"] == "yellow"


def test_cap_severity_fallback_mapt_moderate_severe_extreme():
    for severity, verwacht in (("Moderate", "yellow"), ("Severe", "orange"), ("Extreme", "red")):
        entry = ENTRY_HAUT_RHIN.replace("<cap:severity>Severe</cap:severity>",
                                        f"<cap:severity>{severity}</cap:severity>")
        ws = mal.parse_feed(_feed(entry))
        assert ws[0]["level"] == verwacht, severity


def test_event_valt_terug_op_awareness_type():
    ws = mal.parse_feed(_feed(ENTRY_HAUT_RHIN))
    assert ws[0]["event"] == "Rain"


def test_minor_en_onbekende_severity_vallen_af():
    assert mal.parse_feed(_feed(ENTRY_MINOR)) == []
    onbekend = ENTRY_HAUT_RHIN.replace("<cap:severity>Severe</cap:severity>",
                                       "<cap:severity>Unknown</cap:severity>")
    assert mal.parse_feed(_feed(onbekend)) == []


def test_namespace_variant_1_1_breekt_de_parser_niet():
    ws = mal.parse_feed(_feed(ENTRY_PONGAU, cap_ns="urn:oasis:names:tc:emergency:cap:1.1"))
    assert len(ws) == 1 and ws[0]["level"] == "yellow"


def test_ontbrekende_expires_krijgt_onset_plus_default_uur():
    w = mal.parse_feed(_feed(ENTRY_ZONDER_EXPIRES))[0]
    assert w["expires"] == w["onset"] + timedelta(hours=mal.DEFAULT_DURATION_H)


def test_taal_duplicaten_worden_ontdubbeld():
    # De Franse feed draagt fr+en-versies van dezelfde waarschuwing.
    ws = mal.parse_feed(_feed(ENTRY_HAUT_RHIN + ENTRY_HAUT_RHIN))
    assert len(ws) == 1


def test_kapotte_xml_raist_parse_error():
    # De aanroeper beslist over fataliteit (camping_forecast → warnings_status
    # "failed"); de parser verstopt de fout niet.
    with pytest.raises(ET.ParseError):
        mal.parse_feed("<feed><entry>kapot")


# ── matching en overlap ──────────────────────────────────────────────────────

def test_match_region_is_case_insensitieve_substring():
    w = mal.parse_feed(_feed(ENTRY_PONGAU))[0]
    assert mal.match_region(w, ("salzburg", "pongau"))
    assert mal.match_region(w, ("PONGAU",))
    assert not mal.match_region(w, ("tirol", "innsbruck"))


def test_match_region_matcht_ook_op_geocode():
    w = mal.parse_feed(_feed(ENTRY_PONGAU))[0]
    assert mal.match_region(w, ("at005",))


def test_active_in_overlapt_halfopen():
    w = {"onset": datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
         "expires": datetime(2026, 8, 14, 20, 0, tzinfo=UTC)}
    binnen = (datetime(2026, 8, 14, 0, 0, tzinfo=UTC), datetime(2026, 8, 15, 0, 0, tzinfo=UTC))
    assert mal.active_in(w, *binnen)
    # Randen raken zonder overlap telt niet (halfopen intervallen).
    assert not mal.active_in(w, datetime(2026, 8, 14, 20, 0, tzinfo=UTC),
                             datetime(2026, 8, 15, 0, 0, tzinfo=UTC))
    assert not mal.active_in(w, datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
                             datetime(2026, 8, 14, 12, 0, tzinfo=UTC))


def test_parse_awareness_level_varianten():
    assert mal.parse_awareness_level("2; yellow; Moderate") == "yellow"
    assert mal.parse_awareness_level("4; red; Extreme") == "red"
    assert mal.parse_awareness_level("awt:10 level:orange") is None  # onbekend formaat → fallback
    assert mal.parse_awareness_level(None) is None
