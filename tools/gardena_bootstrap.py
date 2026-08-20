#!/usr/bin/env python3
"""gardena_bootstrap.py — eenmalige lokale ontdekking + Gist-config voor
Project 16 (bewatering-automaat). Spiegel van tado_auth_bootstrap.py.

Draai dit één keer lokaal nadat gateway, kranen en sensor in de GARDENA-app
gekoppeld zijn. Het script mint een token, haalt de locatie op, toont de
gevonden kranen/sensoren (apparaatnamen alléén in je terminal — die kunnen
persoonlijk zijn en horen nooit in Actions-logs), vraagt welke kraan het
gras (sproeier) en welke de struiken (druppelslang) is, en schrijft:

  - `gardena_config.json` (location_id + kraan-service-ids + sensor-id) —
    daarna is de config-schrijver klaar; alleen dit script schrijft dit bestand;
  - `garden_automation.json` — alleen gezaaid als het nog niet bestaat
    (een re-run mag live vlagstanden nooit overschrijven).

Vereist in de omgeving:
  GARDENA_APP_KEY, GARDENA_APP_SECRET  — Husqvarna Developer Portal-applicatie
  GIST_ID, GIST_TOKEN                  — de gedeelde Gist + PAT met gist-scope

Gebruik:
  GARDENA_APP_KEY=... GARDENA_APP_SECRET=... GIST_ID=... GIST_TOKEN=... \
    python tools/gardena_bootstrap.py
"""

import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gardena_api as ga  # noqa: E402
from gardena_control import CONFIG_FILE, FLAGS_FILE  # noqa: E402
from shared_const import utc_now_iso  # noqa: E402


def gist_read_file(gist_id: str, token: str, filename: str):
    r = requests.get(f"https://api.github.com/gists/{gist_id}",
                     headers={"Authorization": f"Bearer {token}",
                              "Accept": "application/vnd.github+json"},
                     timeout=20)
    r.raise_for_status()
    f = r.json().get("files", {}).get(filename)
    return None if f is None else f.get("content")


def gist_write_files(gist_id: str, token: str, files: dict) -> None:
    r = requests.patch(
        f"https://api.github.com/gists/{gist_id}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        json={"files": {fn: {"content": content} for fn, content in files.items()}},
        timeout=20,
    )
    r.raise_for_status()


def pick(prompt: str, options: list) -> str:
    while True:
        answer = input(prompt).strip()
        if answer in options:
            return answer
        print(f"  kies uit: {', '.join(options)}")


def main():
    for var in ("GARDENA_APP_KEY", "GARDENA_APP_SECRET", "GIST_ID", "GIST_TOKEN"):
        if not os.environ.get(var):
            print(f"Zet {var} in de omgeving.", file=sys.stderr)
            sys.exit(1)
    app_key = os.environ["GARDENA_APP_KEY"]
    gist_id, gist_token = os.environ["GIST_ID"], os.environ["GIST_TOKEN"]

    print("→ Token minten…")
    token = ga.mint_token(app_key, os.environ["GARDENA_APP_SECRET"])

    print("→ Locaties ophalen…")
    locations = ga.list_locations(token, app_key)
    if not locations:
        print("Geen locaties gevonden — is de gateway al gekoppeld in de "
              "GARDENA-app, en is de applicatie op het Developer Portal met "
              "hetzelfde GARDENA-account aangemaakt?", file=sys.stderr)
        sys.exit(1)
    location = locations[0]
    if len(locations) > 1:
        print("Meerdere locaties gevonden:")
        for i, loc in enumerate(locations):
            print(f"  [{i}] {loc.get('attributes', {}).get('name')} ({loc['id']})")
        idx = pick("Welke index? ", [str(i) for i in range(len(locations))])
        location = locations[int(idx)]
    location_id = location["id"]

    print("→ Apparaten ophalen…")
    snap = ga.parse_snapshot(ga.fetch_location(token, app_key, location_id))

    valves = snap.get("valves") or {}
    sensors = snap.get("sensors") or {}
    if not valves:
        print("Geen kranen (VALVE-services) gevonden.", file=sys.stderr)
        sys.exit(1)

    print("\nGevonden kranen (namen komen uit de app en blijven lokaal):")
    valve_ids = sorted(valves)
    for i, sid in enumerate(valve_ids):
        v = valves[sid]
        print(f"  [{i}] {v.get('name') or '(naamloos)'} — activity {v.get('activity')}, "
              f"state {v.get('state')}")
    indices = [str(i) for i in range(len(valve_ids))]
    lawn_idx = pick("Welke kraan is het GRAS (sproeier)? ", indices)
    shrubs_idx = pick("Welke kraan zijn de STRUIKEN (druppelslang)? ",
                      [i for i in indices if i != lawn_idx])

    sensor_id = None
    if sensors:
        sensor_ids = sorted(sensors)
        print("\nGevonden bodemsensoren:")
        for i, sid in enumerate(sensor_ids):
            s = sensors[sid]
            print(f"  [{i}] bodemvocht {s.get('soil_hum')}% · bodemtemp {s.get('soil_temp')}°C")
        idx = pick("Welke sensor archiveren? ", [str(i) for i in range(len(sensor_ids))])
        sensor_id = sensor_ids[int(idx)]
    else:
        print("\nGeen bodemsensor gevonden — config kan later opnieuw gezaaid worden.")

    config = {
        "schema": 1,
        "location_id": location_id,
        "valves": {"lawn": valve_ids[int(lawn_idx)],
                   "shrubs": valve_ids[int(shrubs_idx)]},
        "sensor_id": sensor_id,
        "created_at": utc_now_iso(),
    }
    files = {CONFIG_FILE: json.dumps(config, indent=2)}

    # Vlaggen alleen zaaien als ze nog niet bestaan — nooit live standen resetten.
    if not gist_read_file(gist_id, gist_token, FLAGS_FILE):
        files[FLAGS_FILE] = json.dumps(
            {"schema": 1, "auto_lawn": False, "paused": False,
             "updated_at": utc_now_iso()}, indent=2)

    print("\n→ Config naar de Gist schrijven…")
    gist_write_files(gist_id, gist_token, files)
    print(f"✅ Klaar. `{CONFIG_FILE}` staat in de Gist"
          + (f" en `{FLAGS_FILE}` is gezaaid (automaat uit, niet gepauzeerd)."
             if FLAGS_FILE in files else "."))
    print("De uurlijkse workflow pikt dit vanzelf op; test met een handmatige "
          "dispatch van gardena-control.yml (dry_run).")


if __name__ == "__main__":
    main()
