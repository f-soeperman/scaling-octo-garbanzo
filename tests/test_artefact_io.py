"""Tests voor artefact_io — de privé artefact-gist voor data.json/mowing_data.json.

De kern is de zelf-activerende routering: zonder ARTEFACT_GIST_ID gedraagt alles
zich als vanouds (lokaal pad — ook het test-/bootstrap-pad), mét secret gaan
lees én schrijf via de Gist-API en wordt er geen lokaal bestand meer geschreven.
"""
import json

import artefact_io


def _clear_env(monkeypatch):
    for k in ("ARTEFACT_GIST_ID", "GIST_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(k, raising=False)


def test_lokale_modus_roundtrip(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    path = tmp_path / "docs" / "data.json"
    dest = artefact_io.write_json_str("data.json", str(path), '{"a": 1}')
    assert dest == str(path)
    assert json.loads(path.read_text()) == {"a": 1}
    assert artefact_io.read_json("data.json", str(path)) == {"a": 1}
    assert artefact_io.read_json("data.json", str(tmp_path / "weg.json"),
                                 default={}) == {}
    assert artefact_io.gist_active() is False


def test_gist_modus_leest_en_schrijft_via_de_api(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEFACT_GIST_ID", "abc123")
    monkeypatch.setenv("GIST_TOKEN", "tok")
    calls = {}

    def fake_read_json(gid, filename, token=None, default=None, label=None):
        calls["read"] = (gid, filename, token)
        return {"b": 2}

    class _Resp:
        def raise_for_status(self):
            pass

    def fake_patch(url, headers=None, json=None, timeout=None):
        calls["patch"] = (url, json)
        return _Resp()

    monkeypatch.setattr(artefact_io.gist_io, "read_json", fake_read_json)
    monkeypatch.setattr(artefact_io.requests, "patch", fake_patch)

    lokaal = tmp_path / "data.json"
    assert artefact_io.gist_active() is True
    assert artefact_io.read_json("data.json", str(lokaal)) == {"b": 2}
    assert calls["read"] == ("abc123", "data.json", "tok")

    dest = artefact_io.write_json_str("data.json", str(lokaal), '{"c": 3}')
    assert dest == "data.json"
    assert "abc123" in calls["patch"][0]
    assert calls["patch"][1] == {"files": {"data.json": {"content": '{"c": 3}'}}}
    # In gist-modus wordt er géén lokaal bestand (meer) geschreven — dat zou de
    # workflow-commit het artefact weer publiek in docs/ laten zetten.
    assert not lokaal.exists()


def test_gh_token_fallback(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ARTEFACT_GIST_ID", "abc123")
    monkeypatch.setenv("GH_TOKEN", "tok2")   # daily-check/mowing/gardena-naamgeving
    assert artefact_io.gist_active() is True
