"""GARDENA smart system API — transport voor Project 16 (bewatering-automaat).

Alleen transport: token minten (client_credentials), één locatie-snapshot
ophalen en parsen, en kraan-commando's sturen. Alle beslissingen horen in
`gardena_control.py`; dit bestand kent geen zones, geen vlaggen en geen state.

Quota-regels (hard, zie CLAUDE.md Project 16): het GARDENA-API-budget is
~3000 calls/maand (≈1 per 15 min gemiddeld; overschrijding = 429 + ~24u
lock-out). Daarom: één `GET /locations/{id}` per run als enige leesactie,
nooit een verificatie-GET na een commando (de volgende uurlijkse snapshot
verifieert), en retries alléén op transiënte netwerkfouten — nooit op een
HTTP-status.

Credentials reizen in headers (Authorization/X-Api-Key), nooit in de URL —
een requests-exceptie kan dus geen secret lekken. Foutmeldingen gaan bij de
aanroeper alsnog door `notify.sanitize_error` (repo-regel).
"""

import time

import requests

AUTH_URL = "https://api.authentication.husqvarnagroup.dev/v1/oauth2/token"
API_BASE = "https://api.smart.gardena.dev/v2"

# Retry-schema voor transiënte netwerkfouten (timeout/verbinding) — kort en
# klein, zelfde afweging als TADO_RETRY_DELAYS in window_advisor.py. Een
# HTTP-foutstatus wordt bewust NIET geretried: 429 is het quotum (elke retry
# maakt het erger) en 4xx/5xx worden niet beter van meteen nóg een poging.
RETRY_DELAYS = (3, 8)

TIMEOUT = 20


class GardenaApiError(Exception):
    """HTTP-fout van de auth- of GARDENA-API, met status voor de aanroeper
    (429 = quotum geraakt → aanroeper pauzeert tot de volgende run)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _request(method, url: str, **kwargs):
    """`method` (requests.get/post/put) met retry op transiënte netwerkfouten
    en een `GardenaApiError` op elke niet-2xx-status."""
    kwargs.setdefault("timeout", TIMEOUT)
    last_err: Exception | None = None
    for delay in (0, *RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            r = method(url, **kwargs)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_err = e
            continue
        if not r.ok:
            raise GardenaApiError(r.status_code, f"HTTP {r.status_code} op {url.split('?')[0]}")
        return r
    raise last_err


def mint_token(app_key: str, app_secret: str) -> str:
    """Client-credentials access token (~24u geldig). Per run vers gemint en
    nooit gepersisteerd — een bearer-token-at-rest is het cachen niet waard."""
    r = _request(
        requests.post,
        AUTH_URL,
        data={"grant_type": "client_credentials",
              "client_id": app_key, "client_secret": app_secret},
        headers={"Accept": "application/json"},
    )
    return r.json()["access_token"]


def _api_headers(token: str, app_key: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Api-Key": app_key,
        "Accept": "application/vnd.api+json",
    }


def list_locations(token: str, app_key: str) -> list:
    """Alleen voor de bootstrap-tool — de runner kent zijn location_id al."""
    r = _request(requests.get, f"{API_BASE}/locations", headers=_api_headers(token, app_key))
    return r.json().get("data", [])


def fetch_location(token: str, app_key: str, location_id: str) -> dict:
    """De ene leesactie per run: het volledige JSON:API-document met alle
    devices + services (VALVE/SENSOR/COMMON/…) van de locatie."""
    r = _request(requests.get, f"{API_BASE}/locations/{location_id}",
                 headers=_api_headers(token, app_key))
    return r.json()


def _attr(svc: dict, name: str):
    """Attribuut-unwrap: GARDENA verpakt elke waarde als {value, timestamp}.
    Defensief — sensor-generaties (19030 vs 19040) en de spec-nesting kunnen
    velden weglaten; ontbrekend = (None, None), nooit een KeyError."""
    a = (svc.get("attributes") or {}).get(name)
    if not isinstance(a, dict):
        return None, None
    return a.get("value"), a.get("timestamp")


def _device_of(svc: dict):
    try:
        return svc["relationships"]["device"]["data"]["id"]
    except (KeyError, TypeError):
        return None


def parse_snapshot(doc: dict) -> dict:
    """JSON:API-document → platte snapshot.

    Vorm:
      {"valves":  {service_id: {"name", "activity", "activity_ts", "state",
                                "duration_s", "device"}},
       "sensors": {service_id: {"soil_hum", "soil_hum_ts", "soil_temp",
                                "amb_temp", "light", "device"}},
       "common":  {device_id: {"name", "battery", "battery_state", "rf"}}}
    """
    services = list(doc.get("included") or [])
    data = doc.get("data")
    if isinstance(data, list):
        services += data
    out = {"valves": {}, "sensors": {}, "common": {}}
    for svc in services:
        if not isinstance(svc, dict):
            continue
        kind = svc.get("type")
        sid = svc.get("id")
        if kind == "VALVE":
            activity, activity_ts = _attr(svc, "activity")
            duration, _ = _attr(svc, "duration")
            out["valves"][sid] = {
                "name": _attr(svc, "name")[0],
                "activity": activity,
                "activity_ts": activity_ts,
                "state": _attr(svc, "state")[0],
                "duration_s": duration if isinstance(duration, (int, float)) else None,
                "device": _device_of(svc),
            }
        elif kind == "SENSOR":
            hum, hum_ts = _attr(svc, "soilHumidity")
            soil_t, soil_t_ts = _attr(svc, "soilTemperature")
            out["sensors"][sid] = {
                "soil_hum": hum,
                "soil_hum_ts": hum_ts,
                "soil_temp": soil_t,
                "soil_temp_ts": soil_t_ts,
                "amb_temp": _attr(svc, "ambientTemperature")[0],
                "light": _attr(svc, "lightIntensity")[0],
                "device": _device_of(svc),
            }
        elif kind == "COMMON":
            device = _device_of(svc) or sid
            out["common"][device] = {
                "name": _attr(svc, "name")[0],
                "battery": _attr(svc, "batteryLevel")[0],
                "battery_state": _attr(svc, "batteryState")[0],
                "rf": _attr(svc, "rfLinkState")[0],
            }
    return out


def _command(token: str, app_key: str, service_id: str, command: str,
             seconds: int | None = None) -> None:
    attributes: dict = {"command": command}
    if seconds is not None:
        attributes["seconds"] = int(seconds)
    _request(
        requests.put,
        f"{API_BASE}/command/{service_id}",
        headers={**_api_headers(token, app_key),
                 "Content-Type": "application/vnd.api+json"},
        json={"data": {"id": "cmd-1", "type": "VALVE_CONTROL",
                       "attributes": attributes}},
    )


def start_valve(token: str, app_key: str, service_id: str, seconds: int) -> None:
    """START_SECONDS_TO_OVERRIDE — `seconds` moet een positief veelvoud van 60
    zijn (de aanroeper rondt af); de kraan sluit zichzelf na afloop, ook als
    dit script nooit meer draait — dát is de hardware-vangrail."""
    if seconds <= 0 or seconds % 60:
        raise ValueError(f"seconds moet een positief veelvoud van 60 zijn, kreeg {seconds}")
    _command(token, app_key, service_id, "START_SECONDS_TO_OVERRIDE", seconds)


def stop_valve(token: str, app_key: str, service_id: str) -> None:
    _command(token, app_key, service_id, "STOP_UNTIL_NEXT_TASK")
