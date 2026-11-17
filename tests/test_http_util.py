"""Tests voor http_util.get_json (gedeelde GET→JSON met retry/backoff)."""

import pytest
import requests

import http_util


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_succes_op_derde_poging(monkeypatch):
    pogingen = {"n": 0}

    def flaky(url, params=None, timeout=None):
        pogingen["n"] += 1
        if pogingen["n"] < 3:
            raise requests.ConnectionError("hiccup")
        return _Resp({"ok": True})

    monkeypatch.setattr(http_util.requests, "get", flaky)
    monkeypatch.setattr(http_util.time, "sleep", lambda s: None)
    assert http_util.get_json("https://x", attempts=3) == {"ok": True}
    assert pogingen["n"] == 3


def test_default_venster_vijf_pogingen(monkeypatch):
    """De default moet een korte storingsburst overleven: 5 pogingen,
    backoff 3+8+30+60s (~100s venster i.p.v. ~11s)."""
    pogingen = {"n": 0}
    slaap = []

    def kapot(url, params=None, timeout=None):
        pogingen["n"] += 1
        raise requests.ConnectionError("down")

    monkeypatch.setattr(http_util.requests, "get", kapot)
    monkeypatch.setattr(http_util.time, "sleep", slaap.append)
    with pytest.raises(requests.ConnectionError):
        http_util.get_json("https://x")
    assert pogingen["n"] == 5
    assert slaap == [3, 8, 30, 60]


def test_raist_na_laatste_poging(monkeypatch):
    pogingen = {"n": 0}

    def kapot(url, params=None, timeout=None):
        pogingen["n"] += 1
        raise requests.ConnectionError("down")

    monkeypatch.setattr(http_util.requests, "get", kapot)
    monkeypatch.setattr(http_util.time, "sleep", lambda s: None)
    with pytest.raises(requests.ConnectionError):
        http_util.get_json("https://x", attempts=3)
    assert pogingen["n"] == 3


class _Resp429:
    status_code = 429

    def __init__(self, reason):
        self._reason = reason

    def raise_for_status(self):
        raise requests.HTTPError("429 Client Error")

    def json(self):
        return {"error": True, "reason": self._reason}


def test_429_uurlimiet_raist_meteen_ratelimited(monkeypatch):
    """Uur-/daglimiet van het gedeelde runner-IP: herhalen vanaf hetzelfde IP is
    zinloos, dus geen backoff-pogingen maar meteen RateLimited."""
    pogingen = {"n": 0}
    slaap = []

    def limiet(url, params=None, timeout=None):
        pogingen["n"] += 1
        return _Resp429("Hourly API request limit exceeded. Please try again in the next hour.")

    monkeypatch.setattr(http_util.requests, "get", limiet)
    monkeypatch.setattr(http_util.time, "sleep", slaap.append)
    with pytest.raises(http_util.RateLimited) as exc:
        http_util.get_json("https://x")
    assert pogingen["n"] == 1
    assert slaap == []
    assert exc.value.rate_limited is True
    assert "Hourly" in str(exc.value)
    # Blijft een HTTPError: bestaande `except requests.RequestException`-fallbacks
    # bij de aanroepers vangen het nog steeds.
    assert isinstance(exc.value, requests.HTTPError)


def test_429_minuutlimiet_wacht_en_herstelt(monkeypatch):
    pogingen = {"n": 0}
    slaap = []

    def eenmaal_limiet(url, params=None, timeout=None):
        pogingen["n"] += 1
        if pogingen["n"] == 1:
            return _Resp429("Minutely API request limit exceeded. Please try again in one minute.")
        return _Resp({"ok": True})

    monkeypatch.setattr(http_util.requests, "get", eenmaal_limiet)
    monkeypatch.setattr(http_util.time, "sleep", slaap.append)
    assert http_util.get_json("https://x") == {"ok": True}
    assert slaap == [http_util.RATE_LIMIT_MINUTE_WAIT]


def test_429_zonder_leesbare_body_is_ratelimited(monkeypatch):
    class _Kaal(_Resp429):
        def json(self):
            raise ValueError("geen json")

    monkeypatch.setattr(http_util.requests, "get",
                        lambda url, params=None, timeout=None: _Kaal(""))
    monkeypatch.setattr(http_util.time, "sleep", lambda s: None)
    with pytest.raises(http_util.RateLimited):
        http_util.get_json("https://x")


def test_alleen_timeouts_markeert_retry_elsewhere(monkeypatch):
    """13–17 nov 2026: een runner die op alle pogingen timet-out, blijft dat ook
    na 25 min doen. De exceptie behoudt type en tekst, maar krijgt het merkteken
    waarmee run_guarded het aan een verse runner overlaat."""
    def traag(url, params=None, timeout=None):
        raise requests.ReadTimeout("Read timed out. (read timeout=20)")

    monkeypatch.setattr(http_util.requests, "get", traag)
    monkeypatch.setattr(http_util.time, "sleep", lambda s: None)
    with pytest.raises(requests.ReadTimeout) as exc:
        http_util.get_json("https://x")
    assert getattr(exc.value, "retry_elsewhere", False) is True


def test_gemengde_fouten_markeren_niet(monkeypatch):
    """Een 5xx tussen de timeouts door: de server zelf hapert, een andere
    runner helpt dan niet — gewone crash-afhandeling."""
    pogingen = {"n": 0}

    class _Resp500(_Resp):
        status_code = 500

        def raise_for_status(self):
            raise requests.HTTPError("500 Server Error")

    def gemengd(url, params=None, timeout=None):
        pogingen["n"] += 1
        if pogingen["n"] == 2:
            return _Resp500({})
        raise requests.ReadTimeout("Read timed out.")

    monkeypatch.setattr(http_util.requests, "get", gemengd)
    monkeypatch.setattr(http_util.time, "sleep", lambda s: None)
    with pytest.raises(requests.ReadTimeout) as exc:
        http_util.get_json("https://x")
    assert not getattr(exc.value, "retry_elsewhere", False)
