"""Tests voor de gist-laag rond de sensor-evaluatie (`tools/gardena_eval_fetch.py`).

Sinds sep 2026 is de sensorreeks privé (de vochtreeks toont elke
bewateringsbeurt). Deze tests pinnen de twee randen die dat bewaken: de
shards komen uit de privé Gist in exact de vorm die de evaluatie leest, en het
rapport — dat de reeks draagt — gaat naar de privé artefact-gist en nooit naar
een publieke joblog of Actions-artefact.
"""
from __future__ import annotations

import importlib.util
import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_ROOT, "tools", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fetch = _load("gardena_eval_fetch")
ev = _load("gardena_sensor_eval")

# Synthetisch (vóór de installatie van de sensor) — geen echte meetwaarden in fixtures.
_ROWS = [{"t": "2026-07-01T00:00:00+00:00", "soil_hum": 31, "soil_temp": 12},
         {"t": "2026-07-01T01:00:00+00:00", "soil_hum": 33, "soil_temp": 11}]


def test_sensor_shards_komen_uit_de_gist_in_de_vorm_die_de_eval_leest(tmp_path, monkeypatch):
    monkeypatch.setenv("GIST_ID", "g")
    monkeypatch.setenv("GIST_TOKEN", "t")
    files = {
        "gardena_history_2026-07.json": json.dumps(
            {"schema": 1, "month": "2026-07", "rows": _ROWS}),
        "twin2_history_2026-07.json": json.dumps({"month": "2026-07", "rooms": {"x": {}}}),
        "gardena_state.json": "{}",
    }
    monkeypatch.setattr(fetch.gist_io, "read_files", lambda gid, token=None: files)
    assert fetch.fetch_sensor_shards(str(tmp_path)) == 1
    assert [p.name for p in tmp_path.iterdir()] == ["2026-07.json"]
    assert [r["t"] for r in ev.load_sensor_rows(str(tmp_path))] == [r["t"] for r in _ROWS]


def test_sensor_fetch_zonder_creds_haalt_niets(tmp_path, monkeypatch):
    monkeypatch.delenv("GIST_ID", raising=False)
    monkeypatch.setattr(fetch.gist_io, "read_files",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("geen HTTP")))
    assert fetch.fetch_sensor_shards(str(tmp_path)) == 0


def test_rapport_gaat_naar_de_privé_artefact_gist(tmp_path, monkeypatch):
    (tmp_path / "report.txt").write_text("rapport")
    (tmp_path / "report.json").write_text("{}")
    monkeypatch.setenv("ARTEFACT_GIST_ID", "a")
    monkeypatch.setenv("GIST_TOKEN", "t")
    written = {}
    monkeypatch.setattr(fetch.artefact_io.gist_io, "write_files",
                        lambda gid, files, token=None, timeout=20: written.update(files))
    assert fetch.publish_report(str(tmp_path)) is True
    assert written == {"gardena_sensor_eval.txt": "rapport",
                       "gardena_sensor_eval.json": "{}"}


def test_rapport_zonder_artefact_gist_wordt_niet_gepubliceerd(tmp_path, monkeypatch):
    (tmp_path / "report.txt").write_text("rapport")
    (tmp_path / "report.json").write_text("{}")
    monkeypatch.delenv("ARTEFACT_GIST_ID", raising=False)
    assert fetch.publish_report(str(tmp_path)) is False


def test_workflow_zet_het_rapport_niet_in_de_publieke_log():
    wf = open(os.path.join(_ROOT, ".github", "workflows", "gardena-sensor-eval.yml"),
              encoding="utf-8").read()
    assert "upload-artifact" not in wf
    assert '> "$RUNNER_TEMP/gardena_eval/report.txt"' in wf
    assert "--history-dir" in wf and "--out-sensor-dir" in wf
    assert "gardena_eval_fetch.py --publish" in wf
    assert "contents: read" in wf
