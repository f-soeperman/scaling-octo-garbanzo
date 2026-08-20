"""Tests voor gardena_api.py — snapshot-parse (JSON:API) en commando-vorm."""

import pytest

import gardena_api as ga

# Representatief JSON:API-document (vorm van GET /locations/{id}, spec v2):
# data = LOCATION, included = DEVICE + service-objecten met {value, timestamp}-
# verpakte attributen.
DOC = {
    "data": {
        "id": "loc-1", "type": "LOCATION",
        "attributes": {"name": "Tuin"},
        "relationships": {"devices": {"data": [{"id": "dev-1", "type": "DEVICE"}]}},
    },
    "included": [
        {"id": "dev-1", "type": "DEVICE"},
        {"id": "dev-1", "type": "COMMON",
         "attributes": {"name": {"value": "Irrigatie"},
                        "batteryLevel": {"value": 88},
                        "batteryState": {"value": "OK"},
                        "rfLinkState": {"value": "ONLINE"}},
         "relationships": {"device": {"data": {"id": "dev-1", "type": "DEVICE"}}}},
        {"id": "dev-1:1", "type": "VALVE",
         "attributes": {"name": {"value": "Kraan 1"},
                        "activity": {"value": "MANUAL_WATERING",
                                     "timestamp": "2026-08-14T05:00:00Z"},
                        "state": {"value": "OK"},
                        "duration": {"value": 1800}},
         "relationships": {"device": {"data": {"id": "dev-1", "type": "DEVICE"}}}},
        {"id": "dev-1:2", "type": "VALVE",
         "attributes": {"name": {"value": "Kraan 2"},
                        "activity": {"value": "CLOSED",
                                     "timestamp": "2026-08-13T21:00:00Z"},
                        "state": {"value": "OK"}},
         "relationships": {"device": {"data": {"id": "dev-1", "type": "DEVICE"}}}},
        {"id": "sens-1", "type": "SENSOR",
         "attributes": {"soilHumidity": {"value": 31, "timestamp": "2026-08-14T04:30:00Z"},
                        "soilTemperature": {"value": 18.4, "timestamp": "2026-08-14T04:30:00Z"},
                        "ambientTemperature": {"value": 20.1},
                        "lightIntensity": {"value": 0}},
         "relationships": {"device": {"data": {"id": "sens-dev", "type": "DEVICE"}}}},
        {"id": "sens-dev", "type": "COMMON",
         "attributes": {"batteryLevel": {"value": 92},
                        "batteryState": {"value": "OK"},
                        "rfLinkState": {"value": "ONLINE"}},
         "relationships": {"device": {"data": {"id": "sens-dev", "type": "DEVICE"}}}},
    ],
}


def test_snapshot_parse_op_json_api_fixture():
    snap = ga.parse_snapshot(DOC)
    v1 = snap["valves"]["dev-1:1"]
    assert v1["activity"] == "MANUAL_WATERING"
    assert v1["activity_ts"] == "2026-08-14T05:00:00Z"
    assert v1["duration_s"] == 1800
    assert v1["device"] == "dev-1"
    v2 = snap["valves"]["dev-1:2"]
    assert v2["activity"] == "CLOSED"
    assert v2["duration_s"] is None
    sensor = snap["sensors"]["sens-1"]
    assert sensor["soil_hum"] == 31 and sensor["soil_temp"] == 18.4
    assert sensor["device"] == "sens-dev"
    assert snap["common"]["dev-1"]["battery"] == 88
    assert snap["common"]["sens-dev"]["rf"] == "ONLINE"


def test_parse_verdraagt_ontbrekende_sensor_velden():
    # De huidige sensor-generatie (19040) kan ambient/light weglaten en de
    # exacte nesting is pas bij de eerste echte run geverifieerd — geen KeyError.
    doc = {"data": {"id": "loc", "type": "LOCATION"},
           "included": [
               {"id": "s", "type": "SENSOR",
                "attributes": {"soilHumidity": {"value": 40,
                                                "timestamp": "2026-08-14T04:00:00Z"}}},
               {"id": "v", "type": "VALVE", "attributes": {}},
               {"id": "c", "type": "COMMON"},
               "rommel",  # geen dict — mag niet crashen
           ]}
    snap = ga.parse_snapshot(doc)
    s = snap["sensors"]["s"]
    assert s["soil_hum"] == 40
    assert s["amb_temp"] is None and s["light"] is None and s["device"] is None
    v = snap["valves"]["v"]
    assert v["activity"] is None and v["duration_s"] is None


class _Resp:
    ok = True
    status_code = 202

    def json(self):
        return {"access_token": "tok"}


def test_command_body_vorm(monkeypatch):
    calls = []

    def fake_put(url, **kwargs):
        calls.append((url, kwargs))
        return _Resp()

    monkeypatch.setattr(ga.requests, "put", fake_put)
    ga.start_valve("tok", "appkey", "dev-1:1", 1800)
    url, kwargs = calls[0]
    assert url == f"{ga.API_BASE}/command/dev-1:1"
    body = kwargs["json"]["data"]
    assert body["type"] == "VALVE_CONTROL"
    assert body["attributes"] == {"command": "START_SECONDS_TO_OVERRIDE", "seconds": 1800}
    assert kwargs["headers"]["X-Api-Key"] == "appkey"
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    assert kwargs["headers"]["Content-Type"] == "application/vnd.api+json"

    ga.stop_valve("tok", "appkey", "dev-1:1")
    body = calls[1][1]["json"]["data"]
    assert body["attributes"] == {"command": "STOP_UNTIL_NEXT_TASK"}


def test_start_valve_eist_veelvoud_van_60(monkeypatch):
    monkeypatch.setattr(ga.requests, "put",
                        lambda *a, **k: pytest.fail("mag niet versturen"))
    with pytest.raises(ValueError):
        ga.start_valve("tok", "k", "sid", 90)
    with pytest.raises(ValueError):
        ga.start_valve("tok", "k", "sid", 0)


def test_http_fout_wordt_typed_error(monkeypatch):
    class Bad:
        ok = False
        status_code = 429

    monkeypatch.setattr(ga.requests, "get", lambda *a, **k: Bad())
    with pytest.raises(ga.GardenaApiError) as exc:
        ga.fetch_location("tok", "key", "loc-1")
    assert exc.value.status == 429
