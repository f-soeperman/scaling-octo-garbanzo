"""Gedeelde locatie-constanten (Utrecht Oost) — één bron voor alle pipelines.

Alleen stdlib. De per-project modules her-binden deze namen aan hun eigen
lokale aliassen (UTRECHT_LAT, _LAT, …) zodat call-sites en tests ongewijzigd
blijven; dit bestand is uitsluitend de bron van de getallen.
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

# Bewust afgerond op 2 decimalen (~1 km): dit is een publieke repo en de
# artefacten onder docs/ worden via GitHub Pages geserveerd. 4 decimalen
# resolven een individueel adres (~11 m) — precies wat het WU_STATION_ID-
# secret moest voorkomen. Voor alle consumenten (Open-Meteo ~1-10 km-grids,
# FAO-56 ET0, zonnestand) is het verschil verwaarloosbaar.
LATITUDE = 52.09
LONGITUDE = 5.12
TZ = ZoneInfo("Europe/Amsterdam")

# Nederlandse dag-/maandnamen voor Telegram-berichten. De runner heeft geen
# nl_NL-locale, dus strftime('%A %B') zou Engelse namen geven — vandaar met
# de hand. Maanden zijn 1-gebaseerd (index 0 is bewust leeg).
NL_DAYS = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
NL_MONTHS = ["", "jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def utc_now_iso() -> str:
    """Huidige UTC-tijd als ISO-string met `+00:00`-offset (aware).

    Identiek aan `datetime.now(timezone.utc).isoformat()` — puur om de
    boilerplate op de vele `generated_at`/`last_updated`-sites te bundelen.
    De Z-gesuffixte dashboard-varianten blijven bewust hun eigen vorm houden.
    """
    return datetime.now(timezone.utc).isoformat()


def local_today() -> date:
    """Vandaag in Europe/Amsterdam (`datetime.now(TZ).date()`)."""
    return datetime.now(TZ).date()


def parse_date(s: str) -> date:
    """Parse een `YYYY-MM-DD`-string naar een `date` (`strptime(...).date()`)."""
    return datetime.strptime(s, "%Y-%m-%d").date()


def past_local_time(hour: int, minute: int = 0, now: datetime | None = None) -> bool:
    """True zodra de lokale klok vandaag `hour:minute` gepasseerd is.

    Gedeeld door de pijplijnen die vaker *draaien* dan ze *melden*: de data
    ververst elk uur, maar het dagbericht hoort op één moment te vallen. De
    aanroeper combineert dit met zijn eigen dag-state (heb ik vandaag al
    gemeld?), zodat een gemiste run op het doeluur de melding niet laat
    vervallen maar hooguit een uur verschuift — zelfde semantiek als
    `PLAN_HOUR` in de raam-adviseur.

    `now` is injecteerbaar voor tests; standaard `datetime.now(TZ)`.
    """
    now = now or datetime.now(TZ)
    return (now.hour, now.minute) >= (hour, minute)


def format_date_nl(d: date) -> str:
    """`date` → 'maandag 6 jul' — de gedeelde Nederlandse datumweergave."""
    return f"{NL_DAYS[d.weekday()]} {d.day} {NL_MONTHS[d.month]}"
