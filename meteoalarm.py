#!/usr/bin/env python3
"""meteoalarm.py — MeteoAlarm-waarschuwingen (CAP-in-ATOM) voor het Kampeerkompas.

Leest de publieke legacy-ATOM-feeds van MeteoAlarm (de EU-aggregator van de
nationale weerdiensten — KNMI, GeoSphere/ZAMG, Météo-France) en maakt er platte
waarschuwings-dicts van: {"area", "event", "level", "onset", "expires"}.
Level is "yellow" / "orange" / "red"; groen/Minor wordt weggelaten (geen signaal).

Bewust defensief geparst: de CAP-namespace verschilt per land (1.1 vs 1.2) en de
veldenset varieert, dus alle element-toegang loopt via de lokale tagnaam
(`_local`) i.p.v. een vaste namespace-map. Het `awareness_level`-veld
("2; yellow; Moderate") wint van de kale CAP-`severity`, want dat is de kleur
die MeteoAlarm zelf publiceert. Franse feeds dragen fr+en-duplicaten van
dezelfde waarschuwing — die worden ontdubbeld.

Fetch-fouten en kapotte XML raisen naar de aanroeper: die beslist of dat fataal
is (camping_forecast degradeert per land naar warnings_status="failed" — het
artefact onderscheidt "geen waarschuwingen" altijd van "feed onbereikbaar").
Geen secrets: de feeds zijn publiek en key-loos.
"""

import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

from notify import sanitize_error

FEED_URL = "https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-{feed}"
COUNTRY_FEEDS = {"NL": "netherlands", "AT": "austria", "FR": "france"}

# CAP-severity → MeteoAlarm-kleur (fallback wanneer awareness_level ontbreekt).
CAP_SEVERITY_TO_LEVEL = {"moderate": "yellow", "severe": "orange", "extreme": "red"}
LEVEL_RANK = {"yellow": 1, "orange": 2, "red": 3}

# Ontbrekende expires → onset + dit aantal uren (defensief: liever een dag te
# lang rood dan een waarschuwing die meteen "verlopen" is).
DEFAULT_DURATION_H = 24

FETCH_ATTEMPTS = 3
FETCH_DELAYS = (3, 10)  # zelfde trap als http_util, korter: 3 feeds per run


def _fetch_text(url: str, *, timeout: int = 20) -> str:
    """GET → tekst, met dezelfde retry-stijl als http_util.get_json.

    get_json is bewust JSON-only transport (het roept r.json() aan), dus XML
    krijgt hier zijn eigen mini-loop i.p.v. de gedeelde module op te rekken.
    """
    last: Exception | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last = e
            print(f"[meteoalarm] poging {attempt}/{FETCH_ATTEMPTS} mislukt: {sanitize_error(e)}")
            if attempt < FETCH_ATTEMPTS:
                time.sleep(FETCH_DELAYS[min(attempt - 1, len(FETCH_DELAYS) - 1)])
    raise last  # type: ignore[misc]


def _local(tag: str) -> str:
    """'{urn:...:cap:1.2}severity' → 'severity' (namespace-tolerant)."""
    return tag.rsplit("}", 1)[-1]


def _parse_dt(s: str | None) -> datetime | None:
    """CAP-timestamp → aware datetime; naïef → UTC aannemen; onparsbaar → None."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_awareness_level(s: str | None) -> str | None:
    """'2; yellow; Moderate' → 'yellow'. Elke token die een bekende kleur is telt."""
    if not s:
        return None
    for token in s.split(";"):
        t = token.strip().lower()
        if t in LEVEL_RANK:
            return t
    return None


def _parse_entry(entry) -> dict | None:
    """Eén ATOM-entry → waarschuwings-dict, of None (groen/onbruikbaar valt af)."""
    fields: dict[str, str] = {}
    geocodes: list[str] = []
    for el in entry.iter():
        name = _local(el.tag)
        text = (el.text or "").strip()
        if not text:
            continue
        if name == "value":
            geocodes.append(text)
        elif name not in fields:  # eerste waarneming wint (fr/en-duplicaten binnen één entry)
            fields[name] = text

    level = parse_awareness_level(fields.get("awareness_level"))
    if level is None:
        level = CAP_SEVERITY_TO_LEVEL.get(fields.get("severity", "").lower())
    if level is None:
        return None  # groen/Minor/onbekend: geen rode vlag waard

    onset = _parse_dt(fields.get("onset") or fields.get("effective"))
    if onset is None:
        return None
    expires = _parse_dt(fields.get("expires"))
    if expires is None:
        expires = onset + timedelta(hours=DEFAULT_DURATION_H)

    # Event: expliciet CAP-event, anders het type uit awareness_type
    # ("3; Thunderstorm"), anders de entry-titel.
    event = fields.get("event")
    if not event and fields.get("awareness_type"):
        parts = [p.strip() for p in fields["awareness_type"].split(";") if p.strip()]
        event = parts[-1] if parts else None
    if not event:
        event = fields.get("title", "onbekend")

    return {
        "area": fields.get("areaDesc", ""),
        "geocodes": geocodes,
        "event": event,
        "level": level,
        "onset": onset,
        "expires": expires,
    }


def parse_feed(xml_text: str) -> list[dict]:
    """ATOM-feed → lijst waarschuwingen. ET.ParseError propageert (aanroeper kiest)."""
    root = ET.fromstring(xml_text)
    warnings: list[dict] = []
    seen: set[tuple] = set()
    for el in root.iter():
        if _local(el.tag) != "entry":
            continue
        w = _parse_entry(el)
        if w is None:
            continue
        key = (w["area"].casefold(), w["event"].casefold(), w["onset"], w["level"])
        if key in seen:  # fr/en-taalduplicaten in de Franse feed
            continue
        seen.add(key)
        warnings.append(w)
    return warnings


def match_region(warning: dict, area_patterns: tuple[str, ...]) -> bool:
    """Case-insensitieve substring-match op areaDesc én geocodes."""
    haystacks = [warning.get("area", "")] + list(warning.get("geocodes", []))
    for pattern in area_patterns:
        p = pattern.casefold()
        if any(p in h.casefold() for h in haystacks):
            return True
    return False


def active_in(warning: dict, start_dt: datetime, end_dt: datetime) -> bool:
    """Halfopen overlap [onset, expires) × [start_dt, end_dt), vergeleken absoluut."""
    return warning["onset"] < end_dt and warning["expires"] > start_dt


def fetch_country_warnings(country: str) -> list[dict]:
    """Feed van één land ophalen + parsen. Raist bij fetch-/parse-fouten."""
    url = FEED_URL.format(feed=COUNTRY_FEEDS[country])
    warnings = parse_feed(_fetch_text(url))
    print(f"[meteoalarm] {country}: {len(warnings)} waarschuwing(en) in de feed")
    # Eerste-run-ijking: de areaDesc-granulariteit verschilt per land (AT per
    # district, FR per departement) — log een steekproef zodat de
    # area_patterns in camping_forecast.REGIONS tegen de echte namen te
    # controleren zijn.
    for w in warnings[:10]:
        print(f"[meteoalarm]   {w['level']:>6} · {w['event']} · {w['area']}")
    return warnings
