"""gardena_eval_fetch.py — haalt de gist-artefacten op die `gardena_sensor_eval.py`
nodig heeft, voor een CI-run met de gist-secrets.

`gardena_sensor_eval.py` is bewust "geen netwerk" (zuivere functies over lokale
bestanden) — dat blijft zo. Dit script is de dunne, aparte ophaal-laag ervoor:

- `docs/data.json` (het FAO-56-bodemmodel) leeft sinds de privatisering
  (aug 2026) in de privé artefact-gist (`ARTEFACT_GIST_ID`) — via de bestaande
  `artefact_io.read_json`, read-only.
- de twin2-maandshards (alleen voor de bodemtemperatuur-dempingsvergelijking
  tegen de buitenlucht) leven in de privé opening-Gist (`GIST_ID`) — via
  `gist_io.read_files`, read-only.

Privacy: een twin2-shard draagt naast `weather` ook `rooms` (per-kamer
temp/vocht op kwartierresolutie — gedragsdata, zie de banner in CLAUDE.md).
Dit script schrijft daarom bewust **alléén** het `weather`-veld naar schijf —
exact wat `gardena_sensor_eval.load_air_hours` gebruikt — en laat `rooms`
overal weg, ook in een eventueel CI-artefact.

Runner: `python tools/gardena_eval_fetch.py [--out-data PAD] [--out-twin-dir PAD]`.
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


def fetch_twin_weather(out_dir: str) -> int:
    """Alleen `weather` (buitentemp per uur) uit elke twin2-maandshard.
    Optioneel — ontbrekende creds laten alleen de dempingsvergelijking vervallen,
    de rest van het rapport draait door."""
    gist_id = os.getenv("GIST_ID")
    token = os.getenv("GIST_TOKEN") or os.getenv("GH_TOKEN")
    if not (gist_id and token):
        print("[fetch] geen GIST_ID/GIST_TOKEN — twin2-luchttemperatuur overgeslagen.")
        return 0
    try:
        files = gist_io.read_files(gist_id, token=token)
    except Exception as e:
        print(f"[fetch] twin2-shards lezen mislukt: {sanitize_error(e)}")
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
    ap.add_argument("--out-twin-dir", default=os.path.join(default_dir, "twin2"))
    args = ap.parse_args()

    ok = fetch_data(args.out_data)
    fetch_twin_weather(args.out_twin_dir)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
