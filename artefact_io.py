"""artefact_io.py — de privé artefact-Gist voor de live bodem-/maai-artefacten.

`docs/data.json` en `docs/mowing_data.json` waren publieke Pages-artefacten met de
gedateerde handmatige-actie-logboeken erin (sproei- en maaibeurten, plus het
irrigatie-logboek integraal). Een meerweeks gat in zo'n logboek is een
afwezigheidssignaal, en de 15-min/uurlijkse commit-historie maakte elke
registratie voorgoed dateerbaar (privacy-deep-dive aug 2026). Beide artefacten
verhuizen daarom naar een eigen **privé Gist** (`ARTEFACT_GIST_ID`, auth = het
bestaande Gist-token `GIST_TOKEN`/`GH_TOKEN`):

- Secret gezet → lezen/schrijven via de Gist-API; er wordt géén lokaal bestand
  meer geschreven, dus de workflow-commit raakt `docs/` niet meer aan.
- Secret afwezig (bootstrap vóór het secret bestaat, tests, lokaal draaien) →
  het oude gedrag: het lokale pad. De migratie activeert zichzelf dus zodra het
  secret bestaat, zonder harde knip — en valt er ook veilig op terug.

Eén schrijver per bestand blijft gelden: `data.json` ← check_and_notify,
`mowing_data.json` ← mowing_advisor. De dashboards lezen de gist client-side
(localStorage `artefact_gist_id` + het bestaande token) en vallen terug op het
lokale bestand zolang dat nog bestaat.
"""

import json
import os

import requests

import gist_io


def _creds() -> tuple[str | None, str | None]:
    return (os.getenv("ARTEFACT_GIST_ID"),
            os.getenv("GIST_TOKEN") or os.getenv("GH_TOKEN"))


def gist_active() -> bool:
    gid, token = _creds()
    return bool(gid and token)


def read_json(filename: str, local_path: str, default=None):
    """Het artefact als geparsede JSON: uit de artefact-gist wanneer die
    geconfigureerd is, anders het lokale pad. Graceful → ``default``."""
    if gist_active():
        gid, token = _creds()
        return gist_io.read_json(gid, filename, token=token, default=default,
                                 label="artefact")
    try:
        with open(local_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def write_json_str(filename: str, local_path: str, payload: str) -> str:
    """Schrijf het artefact (gist-PATCH of lokaal bestand). Geeft een korte
    bestemmingsnaam voor de logregel. Gist-fouten raisen — het artefact is de
    kern-deliverable van de run, dus stil half-falen is erger dan een rode run
    (de workflows hebben een in-job herkansing)."""
    if gist_active():
        gid, token = _creds()
        r = requests.patch(f"https://api.github.com/gists/{gid}",
                           headers={"Accept": "application/vnd.github+json",
                                    "Authorization": f"Bearer {token}"},
                           json={"files": {filename: {"content": payload}}},
                           timeout=30)
        r.raise_for_status()
        return filename
    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(payload)
    return local_path
