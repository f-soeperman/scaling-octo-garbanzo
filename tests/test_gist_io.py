"""Tests voor gist_io — gedeelde read-only Gist-helpers.

read_file raist bij netwerk-/HTTP-fouten (caller beslist); read_json is de
gracieuze variant die bij élke fout `default` teruggeeft. requests wordt
gemockt — geen netwerk.
"""

import pytest
import requests

import gist_io


class _Resp:
    def __init__(self, payload, status_ok=True, status_code=None):
        self._payload = payload
        self._status_ok = status_ok
        self.status_code = status_code or (200 if status_ok else 404)

    def raise_for_status(self):
        if not self._status_ok:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


# ── write_files: retry op 409 Conflict ───────────────────────────────────────────
# De artefact-gist heeft vier schrijvers op eigen cadans en binnen één run gaan
# PATCHes vlak na elkaar; twee die elkaar raken geven een 409 uit Gist's
# git-backend. Zonder retry crashte dat de hele iteratie (raam-adviseur 6× op
# rij, maai-adviseur 2×, sept 2026).

def test_write_files_retryt_op_409(monkeypatch):
    monkeypatch.setattr(gist_io.time, "sleep", lambda s: None)
    calls = []

    def fake_patch(url, headers=None, json=None, timeout=None):
        calls.append(json)
        if len(calls) < 3:
            return _Resp({}, status_ok=False, status_code=409)
        return _Resp({})

    monkeypatch.setattr(gist_io.requests, "patch", fake_patch)
    gist_io.write_files("gid", {"x.json": "{}"}, token="tok")
    assert len(calls) == 3
    assert calls[0] == {"files": {"x.json": {"content": "{}"}}}


def test_write_files_geeft_op_na_de_retries(monkeypatch):
    slaap = []
    monkeypatch.setattr(gist_io.time, "sleep", slaap.append)
    calls = []

    def fake_patch(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return _Resp({}, status_ok=False, status_code=409)

    monkeypatch.setattr(gist_io.requests, "patch", fake_patch)
    with pytest.raises(requests.HTTPError):
        gist_io.write_files("gid", {"x.json": "{}"})
    assert len(calls) == 1 + len(gist_io.WRITE_RETRY_DELAYS)
    assert slaap == list(gist_io.WRITE_RETRY_DELAYS)


def test_write_files_retryt_geen_andere_fout(monkeypatch):
    """Alleen een 409 is een 'probeer zo nog eens'; een 401/422 is meteen fout."""
    monkeypatch.setattr(gist_io.time, "sleep", lambda s: None)
    calls = []

    def fake_patch(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return _Resp({}, status_ok=False, status_code=401)

    monkeypatch.setattr(gist_io.requests, "patch", fake_patch)
    with pytest.raises(requests.HTTPError):
        gist_io.write_files("gid", {"x.json": "{}"})
    assert len(calls) == 1


def _gist(files: dict) -> dict:
    """Bouw een Gist-API-respons met {filename: {"content": ...}}."""
    return {"files": {name: {"content": c} for name, c in files.items()}}


def test_read_file_geeft_content(monkeypatch):
    monkeypatch.setattr(gist_io.requests, "get",
                        lambda *a, **k: _Resp(_gist({"x.json": "hallo"})))
    assert gist_io.read_file("gid", "x.json") == "hallo"


def test_read_file_ontbrekend_bestand_geeft_none(monkeypatch):
    monkeypatch.setattr(gist_io.requests, "get",
                        lambda *a, **k: _Resp(_gist({"ander.json": "{}"})))
    assert gist_io.read_file("gid", "x.json") is None


def test_read_file_raist_bij_http_fout(monkeypatch):
    monkeypatch.setattr(gist_io.requests, "get",
                        lambda *a, **k: _Resp({}, status_ok=False))
    with pytest.raises(requests.HTTPError):
        gist_io.read_file("gid", "x.json")


def test_read_file_stuurt_bearer_token_mee(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["headers"] = headers
        return _Resp(_gist({"x.json": "1"}))

    monkeypatch.setattr(gist_io.requests, "get", fake_get)
    gist_io.read_file("gid", "x.json", token="secret")
    assert captured["headers"]["Authorization"] == "Bearer secret"


def test_read_json_parset_inhoud(monkeypatch):
    monkeypatch.setattr(gist_io.requests, "get",
                        lambda *a, **k: _Resp(_gist({"d.json": '{"a": 1}'})))
    assert gist_io.read_json("gid", "d.json") == {"a": 1}


def test_read_json_default_bij_ontbrekend_bestand(monkeypatch):
    monkeypatch.setattr(gist_io.requests, "get",
                        lambda *a, **k: _Resp(_gist({"ander.json": "{}"})))
    assert gist_io.read_json("gid", "d.json", default={}) == {}


def test_read_json_default_bij_lege_content(monkeypatch):
    monkeypatch.setattr(gist_io.requests, "get",
                        lambda *a, **k: _Resp(_gist({"d.json": ""})))
    assert gist_io.read_json("gid", "d.json", default={"fallback": True}) == {"fallback": True}


def test_read_json_slikt_netwerkfout_en_geeft_default(monkeypatch):
    def kapot(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(gist_io.requests, "get", kapot)
    # Mag niet raisen: read_json is de gracieuze variant.
    assert gist_io.read_json("gid", "d.json", default=[]) == []


def test_read_json_default_bij_kapotte_json(monkeypatch):
    monkeypatch.setattr(gist_io.requests, "get",
                        lambda *a, **k: _Resp(_gist({"d.json": "{niet: geldig"})))
    assert gist_io.read_json("gid", "d.json", default=None) is None
