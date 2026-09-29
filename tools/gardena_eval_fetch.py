"""gardena_eval_fetch.py — de gist-laag rond `gardena_sensor_eval.py`, voor een
CI-run met de gist-secrets: ophalen vóór de evaluatie, het rapport terugzetten erna.

`gardena_sensor_eval.py` is bewust "geen netwerk" (zuivere functies over lokale
bestanden) — dat blijft zo. Dit script is de dunne, aparte laag eromheen:

- `docs/data.json` (het FAO-56-bodemmodel) leeft sinds de privatisering
  (aug 2026) in de privé artefact-gist (`ARTEFACT_GIST_ID`) — via de bestaande
  `artefact_io.read_json`, read-only.
- de sensor-maandshards leven sinds sep 2026 als `gardena_history_<YYYY-MM>.json`
  in de privé Gist (`GIST_ID`, schrijver: gardena_control) — de vochtreeks toont
  elke bewateringsbeurt. Read-only opgehaald naar een lokale dir.
- de twin2-maandshards (alleen voor de bodemtemperatuur-dempingsvergelijking
  tegen de buitenlucht) leven in dezelfde privé Gist — via
  `gist_io.read_files`, read-only.
- `--publish DIR` zet het rapport (`report.txt` + `report.json` uit DIR) in de
  privé artefact-gist als `gardena_sensor_eval.txt/.json` (enige schrijver).
  Het rapport bevat de sensorreeks, dus het hoort niet in een publieke joblog
  of een Actions-artefact (dat elke ingelogde GitHub-gebruiker kan downloaden).

Privacy: een twin2-shard draagt naast `weather` ook `rooms` (per-kamer
temp/vocht op kwartierresolutie — gedragsdata, zie de banner in CLAUDE.md).
Dit script schrijft daarom bewust **alléén** het `weather`-veld naar schijf —
exact wat `gardena_sensor_eval.load_air_hours` gebruikt — en laat `rooms`
overal weg, ook in een eventueel CI-artefact.

Runner: `python tools/gardena_eval_fetch.py [--out-data PAD] [--out-sensor-dir PAD]
[--out-twin-dir PAD]`, daarna `python tools/gardena_eval_fetch.py --publish DIR`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import artefact_io                 # noqa: E402
import gist_io                     # noqa: E402
from notify import sanitize_error  # noqa: E402

TWIN_PREFIX = "twin2_history_"
SENSOR_PREFIX = "gardena_history_"
REPORT_FILES = {"report.txt": "gardena_sensor_eval.txt",
                "report.json": "gardena_sensor_eval.json"}


def fetch_data(out_path: str) -> bool:
    """Het bodemmodel-artefact naar `out_path`. False = geen bruikbare gist-creds
    (of leeg antwoord) — de eval kan hier niet zonder verder."""
    data = artefact_io.read_json("data.json", "docs/data.json")
    if data is None:
        print("[fetch] geen data.json (ARTEFACT_GIST_ID/GIST_TOKEN ontbreken, "
              "leeg, of de gist is niet leesbaar) — kan zonder niet verder.")
        return False
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"[fetch] data.json ({data.get('generated_at')}) -> {out_path}")
    return True


def _gist_files(label: str):
    """Alle bestanden uit de GIST_ID-gist, of None zonder creds/bij een fout."""
    gist_id = os.getenv("GIST_ID")
    token = os.getenv("GIST_TOKEN") or os.getenv("GH_TOKEN")
    if not (gist_id and token):
        print(f"[fetch] geen GIST_ID/GIST_TOKEN — {label} overgeslagen.")
        return None
    try:
        return gist_io.read_files(gist_id, token=token)
    except Exception as e:
        print(f"[fetch] {label} lezen mislukt: {sanitize_error(e)}")
        return None


def fetch_sensor_shards(out_dir: str) -> int:
    """De sensor-maandshards, ongewijzigd, als `<YYYY-MM>.json` in `out_dir` —
    precies de vorm die `gardena_sensor_eval.load_sensor_rows` leest."""
    files = _gist_files("sensor-shards")
    if files is None:
        return 0
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for name, content in files.items():
        if not (name.startswith(SENSOR_PREFIX) and name.endswith(".json")):
            continue
        try:
            shard = json.loads(content)
        except json.JSONDecodeError:
            continue
        month = shard.get("month") or name[len(SENSOR_PREFIX):-len(".json")]
        with open(os.path.join(out_dir, f"{month}.json"), "w", encoding="utf-8") as f:
            json.dump(shard, f)
        n += 1
    print(f"[fetch] {n} sensor-maandshard(s) -> {out_dir}")
    return n


def publish_report(report_dir: str) -> bool:
    """`report.txt`/`report.json` uit `report_dir` naar de privé artefact-gist.
    Zonder ARTEFACT_GIST_ID + token bewust géén lokale terugval: dan is er
    nergens een privé plek en blijft het rapport alleen op de runner."""
    if not artefact_io.gist_active():
        print("[publish] geen ARTEFACT_GIST_ID/GIST_TOKEN — rapport niet gepubliceerd.")
        return False
    for local, remote in REPORT_FILES.items():
        path = os.path.join(report_dir, local)
        if not os.path.exists(path):
            print(f"[publish] {local} ontbreekt — niets gepubliceerd.")
            return False
        with open(path, encoding="utf-8") as f:
            artefact_io.write_json_str(remote, path, f.read())
    print("[publish] rapport -> privé artefact-gist")
    return True


def fetch_twin_weather(out_dir: str) -> int:
    """Alleen `weather` (buitentemp per uur) uit elke twin2-maandshard.
    Optioneel — ontbrekende creds laten alleen de dempingsvergelijking vervallen,
    de rest van het rapport draait door."""
    files = _gist_files("twin2-luchttemperatuur")
    if files is None:
        return 0

    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for name, content in files.items():
        if not (name.startswith(TWIN_PREFIX) and name.endswith(".json")):
            continue
        try:
            shard = json.loads(content)
        except json.JSONDecodeError:
            continue
        month = shard.get("month") or name[len(TWIN_PREFIX):-len(".json")]
        stripped = {"month": month, "weather": shard.get("weather") or []}
        with open(os.path.join(out_dir, f"{month}.json"), "w", encoding="utf-8") as f:
            json.dump(stripped, f)
        n += 1
    print(f"[fetch] {n} twin2-maandshard(s) (alleen buitentemp) -> {out_dir}")
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    default_dir = os.path.join(os.getenv("RUNNER_TEMP", "/tmp"), "gardena_eval")
    ap.add_argument("--out-data", default=os.path.join(default_dir, "data.json"))
    ap.add_argument("--out-sensor-dir", default=os.path.join(default_dir, "sensor"))
    ap.add_argument("--out-twin-dir", default=os.path.join(default_dir, "twin2"))
    ap.add_argument("--publish", metavar="DIR", default=None,
                    help="alleen publiceren: report.txt/.json uit DIR naar de artefact-gist")
    args = ap.parse_args()

    if args.publish:
        if not publish_report(args.publish):
            raise SystemExit(1)
        return
    ok = fetch_data(args.out_data)
    # Zonder sensorrijen valt er niets te vergelijken — net zo hard als data.json.
    ok = fetch_sensor_shards(args.out_sensor_dir) > 0 and ok
    fetch_twin_weather(args.out_twin_dir)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
