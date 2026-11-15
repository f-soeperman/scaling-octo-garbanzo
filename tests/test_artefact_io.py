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

    def fake_read_json(gid, filename, token=None, default=None, label=None,
                       strict=False):
        calls["read"] = (gid, filename, token)
        return {"b": 2}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

    def fake_patch(url, headers=None, json=None, timeout=None):
        calls["patch"] = (url, json)
        return _Resp()

    monkeypatch.setattr(artefact_io.gist_io, "read_json", fake_read_json)
    monkeypatch.setattr(artefact_io.gist_io.requests, "patch", fake_patch)

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


def test_read_many_is_een_enkele_gist_call(monkeypatch):
    monkeypatch.setenv("ARTEFACT_GIST_ID", "abc123")
    monkeypatch.setenv("GIST_TOKEN", "tok")
    calls = []

    def fake_read_files(gid, token=None, timeout=20, names=None):
        calls.append(sorted(names))
        return {"a.json": '{"a": 1}', "kapot.json": "{nee"}

    monkeypatch.setattr(artefact_io.gist_io, "read_files", fake_read_files)
    out = artefact_io.read_many({"a.json": "x", "weg.json": "y", "kapot.json": "z"})
    assert out == {"a.json": {"a": 1}, "weg.json": None, "kapot.json": None}
    assert len(calls) == 1


def test_read_many_strict_raist_en_anders_niet(monkeypatch):
    import pytest

    monkeypatch.setenv("ARTEFACT_GIST_ID", "abc123")
    monkeypatch.setenv("GIST_TOKEN", "tok")

    def kapot(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(artefact_io.gist_io, "read_files", kapot)
    assert artefact_io.read_many({"a.json": "x"}) == {"a.json": None}
    with pytest.raises(OSError):
        artefact_io.read_many({"a.json": "x"}, strict=True)


def test_read_many_lokale_modus(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    p = tmp_path / "a.json"
    p.write_text('{"a": 1}')
    assert artefact_io.read_many({"a.json": str(p), "weg.json": str(tmp_path / "w")}) == {
        "a.json": {"a": 1}, "weg.json": None}


# ── Zelf-uitvoerende migratie + maand-shards (security-scan nov 2026) ─────────

class _FakeGist:
    """In-memory artefact-gist: vervangt de drie transportfuncties van gist_io."""

    def __init__(self, monkeypatch, files=None):
        self.files = dict(files or {})
        monkeypatch.setenv("ARTEFACT_GIST_ID", "abc123")
        monkeypatch.setenv("GIST_TOKEN", "tok")
        monkeypatch.setattr(artefact_io.gist_io, "read_file",
                            lambda gid, name, token=None, timeout=20: self.files.get(name))
        monkeypatch.setattr(artefact_io.gist_io, "read_files",
                            lambda gid, token=None, timeout=20, names=None: {
                                k: v for k, v in self.files.items() if names is None or k in names})
        monkeypatch.setattr(artefact_io.gist_io, "write_files",
                            lambda gid, files, token=None, timeout=20: self.files.update(files))


def test_state_migreert_van_gecommit_bestand_naar_de_gist(tmp_path, monkeypatch):
    """Eerste gist-run: de gecommitte kopie is het startpunt (geen verloren
    dag-geheugen → geen dubbel bericht), daarna is de gist de bron en is het
    lokale bestand weg."""
    gist = _FakeGist(monkeypatch)
    local = tmp_path / "soil_state.json"
    local.write_text('{"last_advice_date": "2026-01-02"}')
    assert artefact_io.read_json_migrating("soil_state.json", str(local)) == {
        "last_advice_date": "2026-01-02"}
    artefact_io.write_json_str("soil_state.json", str(local), '{"last_advice_date": "2026-01-03"}')
    assert artefact_io.retire_local(str(local)) is True
    assert not local.exists()
    assert json.loads(gist.files["soil_state.json"]) == {"last_advice_date": "2026-01-03"}
    assert artefact_io.read_json_migrating("soil_state.json", str(local)) == {
        "last_advice_date": "2026-01-03"}


def test_retire_local_doet_niets_zonder_gist(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    local = tmp_path / "state.json"
    local.write_text("{}")
    assert artefact_io.retire_local(str(local)) is False
    assert local.exists()


def test_shards_lokaal_roundtrip(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    d = str(tmp_path / "hist")
    assert artefact_io.load_shard("x", d, "2026-01") is None
    artefact_io.save_shards("x", d, {"2026-01": {"month": "2026-01", "rows": [{"t": "a"}]}})
    assert artefact_io.load_shard("x", d, "2026-01")["rows"] == [{"t": "a"}]
    assert [s["month"] for s in artefact_io.load_all_shards("x", d)] == ["2026-01"]
    assert artefact_io.migrate_shards("x", d, "rows", "t") == 0


def test_shard_migratie_is_een_unie_waarin_de_gist_wint(tmp_path, monkeypatch):
    d = tmp_path / "hist"
    d.mkdir()
    (d / "2026-01.json").write_text(json.dumps(
        {"month": "2026-01", "rows": [{"t": "a", "v": 1}, {"t": "b", "v": 1}]}))
    (d / "2026-02.json").write_text(json.dumps({"month": "2026-02", "rows": [{"t": "c", "v": 1}]}))
    gist = _FakeGist(monkeypatch, {
        "x_2026-01.json": json.dumps({"month": "2026-01", "rows": [{"t": "b", "v": 9}]}),
        "anders.json": "{}"})
    assert artefact_io.migrate_shards("x", str(d), "rows", "t") == 2
    assert list(d.iterdir()) == []
    jan = json.loads(gist.files["x_2026-01.json"])["rows"]
    assert jan == [{"t": "a", "v": 1}, {"t": "b", "v": 9}]
    assert [s["month"] for s in artefact_io.load_all_shards("x", str(d))] == ["2026-01", "2026-02"]
    assert artefact_io.migrate_shards("x", str(d), "rows", "t") == 0   # idempotent


def test_shard_migratie_laat_lokaal_staan_als_de_readback_niet_klopt(tmp_path, monkeypatch):
    d = tmp_path / "hist"
    d.mkdir()
    (d / "2026-01.json").write_text(json.dumps({"month": "2026-01", "rows": [{"t": "a"}]}))
    _FakeGist(monkeypatch)
    # Een schrijf die stil niets opslaat: de read-back moet dat vangen.
    monkeypatch.setattr(artefact_io.gist_io, "write_files",
                        lambda gid, files, token=None, timeout=20: None)
    import pytest
    with pytest.raises(RuntimeError):
        artefact_io.migrate_shards("x", str(d), "rows", "t")
    assert (d / "2026-01.json").exists()


def test_migrerende_state_lees_raist_op_een_gistfout(tmp_path, monkeypatch):
    """Na de migratie is er geen lokale kopie meer: een leesfout mag niet als
    "geen state" doorgaan (dan verdwijnt het dag-geheugen en gaat hetzelfde
    bericht nog eens uit)."""
    import pytest

    _FakeGist(monkeypatch)

    def kapot(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(artefact_io.gist_io, "read_file", kapot)
    with pytest.raises(OSError):
        artefact_io.read_json_migrating("soil_state.json", str(tmp_path / "weg.json"))
