"""Dunne, gedeelde transport-helper: GET → JSON met retry/backoff.

Eén implementatie voor de zes Open-Meteo-fetchplekken (soil, briefing,
zandbak, maaien, window, airflow). Incidentele 5xx-hiccups kostten gemeten
~17% van de loop-iteraties zonder retry (zie window_advisor); dit is dat
bewezen retry-gedrag, met gesanitizede foutlogs. Het retry-venster is
verbreed van ~11s naar ~100s (5 pogingen, backoff tot 60s): korte
TLS-reset/timeout-bursts van Open-Meteo worden zo uitgezeten in plaats van
een hele run te laten crashen (en alerten).

Bewust alleen transport: parameter-sets, parsing en fallback-gedrag blijven
bij de aanroepers — de helper abstraheert het hoe, niet het wat. Excepties
propageren na de laatste poging, zodat bestaande fallback-paden (WU-merge,
loop-workflows, run_guarded) blijven werken. WU-fetches blijven bewust
buiten deze helper (apiKey in de URL-string + eigen partial-failure-logica).
"""

import time

import requests

from notify import sanitize_error

# Open-Meteo's free tier telt per IP-adres, en GitHub-runners delen hun uitgaande IP
# met veel andere gebruikers. Gemeten nov 2026: één runner kreeg op álle pogingen
# 429, ook na 25 min wachten, terwijl runs op andere runners in hetzelfde uur
# gewoon slaagden. Een uur- of daglimiet van een gedeeld IP wacht je binnen één job
# niet uit; alleen de minuutlimiet loopt binnen het retry-venster af.
RATE_LIMIT_MINUTE_WAIT = 65  # s — de minuutlimiet loopt binnen een minuut af


class RateLimited(requests.HTTPError):
    """HTTP 429 dat binnen deze job niet meer overgaat (uur-/daglimiet van het
    runner-IP). `run_guarded` behandelt dit als 'probeer het op een andere runner',
    niet als crash. `rate_limited` is het merkteken (notify importeert dit niet)."""

    rate_limited = True

    def __init__(self, reason: str, *, response=None):
        super().__init__(f"429 Too Many Requests — {reason}", response=response)
        self.reason = reason


def _rate_limit_reason(r) -> str:
    """De 'reason' uit Open-Meteo's 429-body ('Hourly API request limit exceeded…').
    Openbare servertekst, geen credential — veilig om te loggen."""
    try:
        reason = (r.json() or {}).get("reason")
    except ValueError:
        reason = None
    return str(reason or "rate limit").strip()[:200]


def get_json(url: str, params: dict | None = None, *, timeout: int = 20,
             attempts: int = 5, delays: tuple[float, ...] = (3, 8, 30, 60),
             label: str = "http") -> dict:
    """GET de URL en geef de JSON-body terug; retry met backoff bij falen.

    `delays[i]` is de wachttijd vóór poging i+2 (de laatste delay herhaalt als
    er meer pogingen dan delays zijn). Na de laatste mislukte poging raist de
    onderliggende requests-exceptie.

    HTTP 429 krijgt een eigen pad: een minuutlimiet wacht ~1 min en probeert
    opnieuw; elke andere limiet (uur, dag, onbekend) raist meteen `RateLimited`,
    want herhalen vanaf hetzelfde runner-IP lukt binnen deze job niet."""
    wait = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            time.sleep(wait if wait is not None
                       else delays[min(attempt - 2, len(delays) - 1)])
            wait = None
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if getattr(r, "status_code", None) == 429:
                reason = _rate_limit_reason(r)
                print(f"[{label}] poging {attempt}/{attempts}: 429 — {reason}")
                if "minute" in reason.lower() and attempt < attempts:
                    wait = RATE_LIMIT_MINUTE_WAIT
                    continue
                raise RateLimited(reason, response=r)
            r.raise_for_status()
            return r.json()
        except RateLimited:
            raise
        except requests.RequestException as e:
            print(f"[{label}] poging {attempt}/{attempts} mislukt: {sanitize_error(e)}")
            if attempt == attempts:
                raise
